# -*- coding: utf-8 -*-
"""L1 离线单测：判定入口 qa_action（对抗性：探测失败/不符预期都不能算通过）。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import qa_action as A  # noqa: E402
from qa_skill_common import bbt_helpers as H  # noqa: E402


class ControlTest(unittest.TestCase):
    # ---- 对抗性 1：多选必须走行为判定，且不符预期要 ok=False ----
    def test_multi_ok(self):
        with mock.patch.object(H, "select_is_multiple", return_value=True):
            r = A.control(None, object(), "multi")
        self.assertTrue(r["ok"])
        self.assertEqual(r["actual"], "multi")

    def test_multi_but_actually_single(self):
        with mock.patch.object(H, "select_is_multiple", return_value=False):
            r = A.control(None, object(), "multi")
        self.assertFalse(r["ok"], "多选预期碰到单选必须判失败")
        self.assertEqual(r["actual"], "single")

    def test_single_ok(self):
        with mock.patch.object(H, "select_is_multiple", return_value=False):
            r = A.control(None, object(), "single")
        self.assertTrue(r["ok"])

    # ---- 对抗性 2：探测异常不得静默放过 ----
    def test_probe_exception_is_failure(self):
        with mock.patch.object(H, "select_is_multiple", side_effect=RuntimeError("boom")):
            r = A.control(None, object(), "multi")
        self.assertFalse(r["ok"])
        self.assertEqual(r["actual"], "unknown")

    def test_multi_needs_two_values(self):
        r = A.control(None, object(), "multi", values=["only-one"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "probe_needs_two_values")

    # ---- 其他类型委托 assert_control_type ----
    def test_delegates_to_assert_control_type(self):
        with mock.patch.object(H, "assert_control_type", return_value={"ok": True, "actual": "input"}):
            r = A.control(None, object(), "input")
        self.assertTrue(r["ok"])
        self.assertEqual(r["expect"], "input")


class VerdictTest(unittest.TestCase):
    def test_match_when_expect_silent(self):
        fake = {"ok": False, "reason": "silent", "signals": {"toasts": [], "form_errors": []}}
        with mock.patch.object(H, "judge_action", return_value=dict(fake)):
            r = A.verdict(None, lambda: None, expect="silent")
        self.assertTrue(r["match"])
        self.assertIn("signals", r, "原始四源信号不得丢失")

    def test_not_match_when_blocked(self):
        with mock.patch.object(H, "judge_action", return_value={"ok": False, "reason": "blocked"}):
            r = A.verdict(None, lambda: None, expect="silent")
        self.assertFalse(r["match"], "有 toast 的拦截不得被当成静默无反馈")

    def test_no_expect_returns_plain(self):
        with mock.patch.object(H, "judge_action", return_value={"ok": True, "reason": "success"}):
            r = A.verdict(None, lambda: None)
        self.assertNotIn("match", r)


class EmitVerdictTest(unittest.TestCase):
    def test_small_payload_returns_text(self):
        out = A.emit_verdict({"ok": True, "reason": "success", "extra": "x" * 10})
        self.assertIsInstance(out, str)
        self.assertIn("success", out)


if __name__ == "__main__":
    unittest.main()
