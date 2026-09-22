# -*- coding: utf-8 -*-
"""L1 离线单测：输出限长契约（判定字段永不截断）。

运行：python3 -m unittest discover -s qa_skill_common/tests -t . -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import output as O  # noqa: E402


def _big_elements(n=200):
    return [{"i": i, "text": "x" * 40} for i in range(n)]


class TestEmit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def test_under_budget_is_passthrough(self):
        payload = {"toasts": ["ok"], "elements": [{"i": 0}]}
        text = O.emit(payload, kind="t", max_chars=2000)
        self.assertEqual(json.loads(text), payload)

    def test_over_budget_truncates_observe_keeps_signals(self):
        payload = {
            "toasts": ["请选择生成方式"],
            "form_errors": ["生产订单分班号必填"],
            "http": [{"url": "/api/x", "status": 400, "ms": 12}],
            "elements": _big_elements(),
        }
        text = O.emit(payload, kind="t", max_chars=400, out_dir=self.out, name="c1")
        got = json.loads(text)
        # 判定字段完整（红线：判定信号不得因省 token 被截断）
        self.assertEqual(got["toasts"], ["请选择生成方式"])
        self.assertEqual(got["form_errors"], ["生产订单分班号必填"])
        self.assertEqual(got["http"], [{"url": "/api/x", "status": 400, "ms": 12}])
        # 观察字段被截断，且给出 counts / omitted / full_path
        self.assertTrue(got["truncated"])
        self.assertLess(len(got["elements"]), 200)
        self.assertEqual(got["counts"]["elements"], 200)
        self.assertIn("elements", got["omitted"])
        self.assertTrue(Path(got["full_path"]).exists())
        self.assertLessEqual(len(text), 400)

    def test_signals_never_dropped_even_when_over_budget(self):
        """不可截断部分本身超预算时，保判据并标 over_budget。"""
        payload = {"toasts": ["T" * 600], "elements": [{"i": i} for i in range(50)]}
        text = O.emit(payload, kind="t", max_chars=100)
        got = json.loads(text)
        self.assertIn("T" * 600, text)          # 判据完整保留
        self.assertTrue(got.get("over_budget"))
        self.assertEqual(got["budget"], 100)

    def test_full_bypasses_truncation(self):
        payload = {"elements": _big_elements(50), "toasts": []}
        text = O.emit(payload, kind="t", max_chars=100, full=True)
        self.assertEqual(json.loads(text), payload)

    def test_unknown_keys_are_not_truncated_by_default(self):
        """安全默认：白名单外的新字段一律完整保留。"""
        payload = {"brand_new_field": ["y" * 30] * 100, "elements": _big_elements(50)}
        text = O.emit(payload, kind="t", max_chars=500)
        got = json.loads(text)
        self.assertEqual(len(got["brand_new_field"]), 100)
        self.assertTrue(got["truncated"])

    def test_emit_signals_alias(self):
        payload = {"toasts": ["a"], "rows": _big_elements()}
        text = O.emit_signals(payload, max_chars=300, out_dir=self.out, name="s1")
        got = json.loads(text)
        self.assertEqual(got["toasts"], ["a"])

    def test_full_path_written_even_without_out_dir(self):
        payload = {"elements": _big_elements()}
        got = json.loads(O.emit(payload, kind="t", max_chars=200))
        self.assertNotIn("full_path", got)      # 无 out_dir 时不落盘也不报错


class TestSummarize(unittest.TestCase):
    def test_summarize_gives_totals(self):
        s = O.summarize({"rows": list(range(50)), "url": "u"})
        self.assertEqual(s["rows"]["total"], 50)
        self.assertEqual(len(s["rows"]["head"]), 10)
        self.assertEqual(s["url"], "u")


if __name__ == "__main__":
    unittest.main()
