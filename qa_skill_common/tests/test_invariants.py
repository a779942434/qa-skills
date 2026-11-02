# -*- coding: utf-8 -*-
"""MES 通用不变量测试。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import invariants as I  # noqa: E402


class BuiltinInvariantTest(unittest.TestCase):
    def test_sum(self):
        self.assertTrue(I.check_sum(100, [40, 60])["passed"])
        self.assertFalse(I.check_sum(100, [40, 59])["passed"])

    def test_non_negative(self):
        self.assertTrue(I.check_non_negative(0)["passed"])
        self.assertFalse(I.check_non_negative(-1)["passed"])

    def test_unique(self):
        self.assertTrue(I.check_unique(["A", "B"])["passed"])
        self.assertEqual(I.check_unique(["A", "A"])["duplicates"], ["A"])

    def test_time_order(self):
        self.assertTrue(I.check_time_order("2026-01-01", "2026-01-01")["passed"])
        self.assertFalse(I.check_time_order("2026-01-02", "2026-01-01")["passed"])

    def test_state_transition(self):
        allowed = {"待审核": ["已审核"], "已审核": ["已生产"]}
        self.assertTrue(I.check_state_transition("待审核", "已审核", allowed)["passed"])
        self.assertFalse(I.check_state_transition("待审核", "已生产", allowed)["passed"])

    def test_preserved_quantity(self):
        self.assertTrue(I.check_preserved_quantity(10, 10.0000001)["passed"])
        self.assertFalse(I.check_preserved_quantity(10, 9.9)["passed"])


class EvaluateTest(unittest.TestCase):
    def test_evaluate_keeps_failure_and_exception(self):
        specs = [
            I.InvariantSpec("I1", "非负", "quantity", "P1", lambda ctx: True),
            I.InvariantSpec("I2", "失败", "quantity", "P1", lambda ctx: False),
            I.InvariantSpec("I3", "异常", "quantity", "P1", lambda ctx: 1 / 0),
        ]
        results = I.evaluate(specs, None)
        self.assertTrue(results[0]["passed"])
        self.assertFalse(results[1]["passed"])
        self.assertFalse(results[2]["passed"])
        self.assertIn("ZeroDivisionError", results[2]["error"])


if __name__ == "__main__":
    unittest.main()
