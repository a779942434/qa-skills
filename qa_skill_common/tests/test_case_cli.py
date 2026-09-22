# -*- coding: utf-8 -*-
"""L1 离线单测：qa_case CLI 门面（单行 JSON 契约 / resume 语义 / 结论回流）。

不依赖浏览器：只覆盖 status / report / 参数错误三条不需要页面的路径。

运行：python3 -m unittest discover -s qa_skill_common/tests -t . -v
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import case_cli as C                    # noqa: E402
from qa_skill_common import page_registry as REG              # noqa: E402
from qa_skill_common.phase_runner import RunState             # noqa: E402


def _call(argv):
    """跑一次 CLI，返回 (rc, stdout)。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = C.main(argv)
    return rc, buf.getvalue()


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)

    def test_status_single_line_json(self):
        rc, out = _call(["status", "--run-dir", str(self.run_dir)])
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)      # 单行契约
        self.assertLessEqual(len(out), C.MAX_STDOUT_CHARS)
        payload = json.loads(out)
        self.assertEqual(payload["total"], 0)

    def test_status_reflects_recorded_cases(self):
        st = RunState(self.run_dir, "R1", "月度工序计划")
        st.mark_case("C01", "core", "通过")
        st.mark_case("C02", "core", "失败", blocker_type="产品缺陷")
        rc, out = _call(["status", "--run-dir", str(self.run_dir)])
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["passed"], 1)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(payload["blocker_types"]["产品缺陷"], 1)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)

    def _seed(self):
        st = RunState(self.run_dir, "R1", "委外发料明细")
        st.mark_case("C01", "生成", "通过", evidence="gen.png")
        st.mark_case("C02", "审核", "失败", note="未生成发料明细",
                     blocker_type="产品缺陷")
        (self.run_dir / "conclusions.json").write_text(json.dumps({
            "meta": {"环境": "t-dog", "范围": "零件委外"},
            "结论": ["零件委外审核后不生成委外发料明细（P1）"],
            "问题": [{"id": "BUG-01", "标题": "审核后无发料明细", "级别": "P1"}],
            "未覆盖": ["导入"],
            "证据": ["gen.png"],
        }, ensure_ascii=False), encoding="utf-8")

    def test_report_renders_from_structured_data(self):
        self._seed()
        rc, out = _call(["report", "--run-dir", str(self.run_dir)])
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        text = Path(payload["report"]).read_text(encoding="utf-8")
        self.assertIn("委外发料明细", text)
        self.assertIn("业务结论", text)                    # 结论回流渲染
        self.assertIn("零件委外审核后不生成委外发料明细", text)
        self.assertIn("通过 1", text)
        self.assertIn("失败 1", text)

    def test_report_is_idempotent_on_data_change(self):
        """只改结论数据再重渲染 —— 不手写 markdown。"""
        self._seed()
        _call(["report", "--run-dir", str(self.run_dir)])
        p = self.run_dir / "conclusions.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["结论"] = ["结论已更新：零件委外仍未修复（P1）"]
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        rc, out = _call(["report", "--run-dir", str(self.run_dir)])
        text = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("结论已更新", text)
        self.assertNotIn("不生成委外发料明细（P1）", text)

    def test_report_without_conclusions_still_works(self):
        st = RunState(self.run_dir, "R2", "无结论功能")
        st.mark_case("C01", "core", "通过")
        rc, out = _call(["report", "--run-dir", str(self.run_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue(Path(json.loads(out)["report"]).exists())


class TestErrors(unittest.TestCase):
    def test_missing_steps_file_returns_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = _call(["exec", "--steps", str(Path(tmp) / "nope.json"),
                             "--run-dir", tmp])
        self.assertEqual(rc, 2)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertIn("不存在", payload["error"])

    def test_invalid_steps_json_returns_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "steps.json"
            bad.write_text("{ not json", encoding="utf-8")
            rc, out = _call(["exec", "--steps", str(bad), "--run-dir", tmp])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out)["status"], "error")

    def test_missing_spec_returns_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = _call(["run", "--spec", str(Path(tmp) / "nope.py"),
                             "--run-dir", tmp])
        self.assertEqual(rc, 2)
        self.assertIn("不存在", json.loads(out)["error"])

    def test_all_errors_stay_within_stdout_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = _call(["exec", "--steps", str(Path(tmp) / ("x" * 300 + ".json")),
                             "--run-dir", tmp])
        self.assertLessEqual(len(out), C.MAX_STDOUT_CHARS)


class TestRegistryNavigation(unittest.TestCase):
    """P1-3：命中 verified 才直接 goto，且必须过一致性校验。"""

    HOST = "http://t-dafu.ob.shuyilink.com"
    FEAT = "月度工序计划"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch("qa_skill_common.paths.workspace_root",
                       return_value=Path(self.tmp.name))
        self.addCleanup(p.stop)
        p.start()

    def _page(self, title, url="http://t-dafu.ob.shuyilink.com/plan/monthly/index"):
        class P:
            def __init__(self):
                self.url = url
            def title(self):
                return title
        return P()

    def test_verified_and_matching_title_uses_direct_goto(self):
        REG.upsert_page(self.HOST, self.FEAT, url=self.HOST + "/plan/monthly/index",
                        verified=True, title="月度工序计划", probe_verdict="element-plus")
        calls = []
        page = self._page("月度工序计划")
        landed, note = C._land(page, self.HOST + "/x", self.FEAT,
                               lambda pg, u: calls.append(u))
        self.assertEqual(calls, [self.HOST + "/plan/monthly/index"])
        self.assertIn("直接 goto", note)
        self.assertEqual(REG.get_page(self.HOST, self.FEAT)["hits"], 2)  # upsert + record_hit

    def test_stale_entry_falls_back_and_downgrades(self):
        REG.upsert_page(self.HOST, self.FEAT, url=self.HOST + "/plan/old/index",
                        verified=True, title="旧标题", probe_verdict="element-plus")
        calls = []
        page = self._page("完全不同的页面")
        with mock.patch("qa_skill_common.bbt_osd_common.goto_feature",
                        return_value=self.HOST + "/plan/new/index") as gf:
            landed, note = C._land(page, self.HOST + "/x", self.FEAT,
                                   lambda pg, u: calls.append(u))
        self.assertTrue(gf.called or calls)                # 有回退动作
        self.assertIn("失效", note)
        entry = REG.get_page(self.HOST, self.FEAT)
        self.assertFalse(entry["verified"])                # 已降级
        self.assertTrue(entry["stale"])

    def test_unverified_entry_never_direct_goto(self):
        REG.upsert_page(self.HOST, self.FEAT, url=self.HOST + "/maybe", verified=False)
        calls = []
        page = self._page("月度工序计划")
        with mock.patch("qa_skill_common.bbt_osd_common.goto_feature", return_value=None):
            C._land(page, self.HOST + "/x", self.FEAT, lambda pg, u: calls.append(u))
        self.assertNotIn(self.HOST + "/maybe", calls)      # 不会被信任

    def test_pages_subcommand_renders_registry(self):
        REG.upsert_page(self.HOST, self.FEAT, url=self.HOST + "/a", verified=True)
        rc, out = _call(["pages", "--url", self.HOST + "/x"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertIn("月度工序计划", payload["registry"])


class TestParserWiring(unittest.TestCase):
    def test_subcommands_present(self):
        ap = C.build_parser()
        for cmd in ("exec", "run", "status", "report", "pages"):
            self.assertEqual(ap.parse_args([cmd] + _required(cmd)).command, cmd)


def _required(cmd):
    return {"exec": ["--steps", "s.json"], "run": ["--spec", "r.py"],
            "status": ["--run-dir", "."], "report": ["--run-dir", "."],
            "pages": ["--url", "http://x"]}[cmd]


if __name__ == "__main__":
    unittest.main()
