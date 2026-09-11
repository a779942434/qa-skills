# -*- coding: utf-8 -*-
"""L1 离线单测：页面侦察的限量 / counts / 检索 / 分隔符归正 / 向后兼容。

不依赖浏览器与网络：用 FakePage 拦截 page.evaluate，断言「传参契约」与「输出契约」。
真正的 JS 行为由 L1.5（node 真实执行）与 L2（真实浏览器）覆盖。

运行：python3 -m unittest discover -s qa_skill_common/tests -t . -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import bbt_helpers as H              # noqa: E402
from qa_skill_common.recon_generic import recon_page as R  # noqa: E402

# 分隔符正则的两种「形态」——这是本文件最容易写错的地方，故显式区分：
#   RUNTIME: Python 已解析后、真正下发给 JS 的字符串（单反斜杠）
#   SOURCE : 源码文件里的字面文本（双反斜杠），因 Python 会再解析一层
REGEX_RUNTIME = r"replace(/[\n\t]+/g"
REGEX_SOURCE = r"replace(/[\\n\\t]+/g"


class FakePage:
    """记录 evaluate/goto/wait 调用的假 page。"""

    def __init__(self, ret=None):
        self._ret = ret if ret is not None else {}
        self.calls = []          # [(js, arg)]
        self.goto_calls = []
        self.timeouts = []

    def evaluate(self, js, arg=None):
        self.calls.append((js, arg))
        return self._ret

    def goto(self, url, **kw):
        self.goto_calls.append((url, kw))

    def wait_for_timeout(self, ms):
        self.timeouts.append(ms)


def sample_structure(**over):
    """构造一份侦察结果样本（默认已截断：counts.rows > len(rows)）。"""
    s = {
        "url": "http://mes.example.com/base/abc",
        "title": "客户档案",
        "buttons": ["新增", "导出", "查询"],
        "headers": ["客户编码", "客户名称", "状态"],
        "rows": ["C001 | 甲公司 | 启用", "C002 | 乙公司 | 停用"],
        "inputs": [{"ph": "请输入客户名称", "type": "text"}],
        "dialogs": [],
        "counts": {"buttons": 3, "headers": 3, "rows": 328, "inputs": 1, "dialogs": 0},
    }
    s.update(over)
    return s


class TestLimitContract(unittest.TestCase):
    """限量参数必须原样传给页面侧 JS（截断在浏览器内完成，不把全量拉回 Python）。"""

    def test_defaults_are_50_60_20_5(self):
        p = FakePage()
        H.recon_page_structure(p)
        self.assertEqual(p.calls[-1][1], [50, 60, 20, 5])

    def test_custom_max_rows(self):
        p = FakePage()
        H.recon_page_structure(p, max_rows=10)
        self.assertEqual(p.calls[-1][1][0], 10)

    def test_custom_all(self):
        p = FakePage()
        H.recon_page_structure(p, max_rows=5, max_buttons=3, max_inputs=1, max_dialogs=2)
        self.assertEqual(p.calls[-1][1], [5, 3, 1, 2])

    def test_non_positive_means_no_cap(self):
        """<=0 表示不截断，原样下传（由 JS 的 cap() 解释为取全部）。"""
        p = FakePage()
        H.recon_page_structure(p, max_rows=0, max_buttons=-1)
        arg = p.calls[-1][1]
        self.assertEqual(arg[0], 0)
        self.assertEqual(arg[1], -1)

    def test_js_carries_counts_and_cap_helper(self):
        """JS 里必须真的有 counts 与 cap 逻辑，而不是只有 Python 侧包装。"""
        p = FakePage()
        H.recon_page_structure(p)
        js = p.calls[-1][0]
        self.assertIn("counts", js)
        self.assertIn("cap(", js)
        self.assertIn("rows.slice(0, cap(maxRows))", js)

    def test_no_bare_newline_in_regex(self):
        """回归：`\\n` 必须是两个字符；写成真换行会让正则被截断成非法 JS。"""
        p = FakePage()
        H.recon_page_structure(p)
        js = p.calls[-1][0]
        for line in js.split("\n"):
            self.assertFalse(line.rstrip().endswith("replace(/"),
                             "正则被真实换行截断：" + repr(line))
        self.assertIn(REGEX_RUNTIME, js)


class TestReconOnce(unittest.TestCase):
    def test_passes_kwargs_through(self):
        p = FakePage()
        H.recon_once(p, "http://x/y", max_rows=7)
        self.assertEqual(p.calls[-1][1][0], 7)

    def test_default_kwargs(self):
        p = FakePage()
        H.recon_once(p, "http://x/y")
        self.assertEqual(p.calls[-1][1], [50, 60, 20, 5])


class TestFindInStructure(unittest.TestCase):
    def test_matches_across_fields(self):
        s = sample_structure()
        hits = R.find_in_structure(s, "公司")
        self.assertEqual([(k, i) for k, i, _ in hits], [("rows", 0), ("rows", 1)])

    def test_matches_buttons_headers_inputs(self):
        s = sample_structure()
        self.assertEqual([k for k, _, _ in R.find_in_structure(s, "新增")], ["buttons"])
        self.assertEqual([k for k, _, _ in R.find_in_structure(s, "客户编码")], ["headers"])
        self.assertEqual([k for k, _, _ in R.find_in_structure(s, "请输入")], ["inputs"])
        # "客户名称" 既在表头、也在输入框 placeholder —— 两处都应命中
        self.assertEqual([k for k, _, _ in R.find_in_structure(s, "客户名称")], ["headers", "inputs"])

    def test_no_hit(self):
        self.assertEqual(R.find_in_structure(sample_structure(), "不存在的东西"), [])

    def test_dict_item_is_serialized_not_crashed(self):
        """inputs 是 dict，检索时不能抛异常。"""
        hits = R.find_in_structure(sample_structure(), "text")
        self.assertEqual(hits[0][0], "inputs")


class TestRenderText(unittest.TestCase):
    def test_shows_truncation_hint(self):
        out = R.render_text(sample_structure())
        self.assertIn("行数: 328（显示前 2）", out)

    def test_no_hint_when_complete(self):
        s = sample_structure(counts={"buttons": 3, "headers": 3, "rows": 2, "inputs": 1, "dialogs": 0})
        out = R.render_text(s)
        self.assertIn("行数: 2", out)
        self.assertNotIn("显示前", out)

    def test_find_render_lists_hits(self):
        out = R.render_find(sample_structure(), "公司")
        self.assertIn("命中 2 项", out)
        self.assertIn("[行#0]", out)


class TestSeparatorNormalization(unittest.TestCase):
    """统一归正：展示用多行文本一律压成 ' | '。

    真实浏览器里：表格行 innerText 用 Tab 分隔、弹窗用换行分隔，
    因此正则必须同时覆盖 \\n 与 \\t，否则表格行永远不会被规整。
    """

    def test_recon_structure_covers_tab_and_newline(self):
        p = FakePage()
        H.recon_page_structure(p)
        self.assertIn(REGEX_RUNTIME, p.calls[-1][0])

    def test_dump_visible_dialogs_covers_tab_and_newline(self):
        p = FakePage([])
        H.dump_visible_dialogs(p)
        self.assertIn(REGEX_RUNTIME, p.calls[-1][0])

    def test_read_dialog_covers_tab_and_newline(self):
        p = FakePage(None)
        H.read_dialog(p)
        self.assertIn(REGEX_RUNTIME, p.calls[-1][0])

    def test_all_sources_normalized(self):
        """源码层面兜底：所有输出多行文本的脚本都用同一套正则。"""
        files = [
            "qa_skill_common/bbt_helpers.py",
            "qa_skill_common/bbt_osd_common.py",
            "qa_skill_common/recon_generic/recon_subtables.py",
            "qa_skill_common/recon_generic/recon_dialog.py",
        ]
        for rel in files:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertIn(REGEX_SOURCE, text, "{0} 未统一分隔符正则".format(rel))


class TestBackwardCompat(unittest.TestCase):
    """老调用方只依赖这些键，改造后必须全部保留。"""

    OLD_KEYS = ("url", "title", "buttons", "headers", "rows", "inputs", "dialogs")

    def test_all_old_keys_present(self):
        p = FakePage(sample_structure())
        s = H.recon_page_structure(p)
        for k in self.OLD_KEYS:
            self.assertIn(k, s)

    def test_counts_is_additive_only(self):
        p = FakePage(sample_structure())
        s = H.recon_page_structure(p)
        self.assertIn("counts", s)
        self.assertEqual(set(s) - set(self.OLD_KEYS), {"counts"})

    def test_old_positional_call_still_works(self):
        """老代码可能写 recon_page_structure(page) 或 recon_page_structure(page, 100)。"""
        p = FakePage()
        H.recon_page_structure(p, 100)
        self.assertEqual(p.calls[-1][1][0], 100)


class TestRenderJson(unittest.TestCase):
    def test_structure_is_json_serializable(self):
        s = sample_structure()
        self.assertEqual(json.loads(json.dumps(s, ensure_ascii=False))["counts"]["rows"], 328)


if __name__ == "__main__":
    unittest.main(verbosity=2)
