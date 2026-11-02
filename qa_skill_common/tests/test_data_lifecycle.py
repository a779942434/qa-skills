# -*- coding: utf-8 -*-
"""数据配方元数据和清理报告测试。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import data_cleanup, data_factory  # noqa: E402


class DataRecipeTest(unittest.TestCase):
    def test_recipe_has_lifecycle_metadata(self):
        recipe = data_factory.default_registry().get("委外计划排产-零件默认生成")
        self.assertTrue(recipe.cleanup)
        self.assertEqual(recipe.owner, "qa")
        self.assertTrue(recipe.batch_prefix)
        self.assertFalse(recipe.irreversible)
        self.assertIn("cleanup", recipe.to_dict())


class CleanupTest(unittest.TestCase):
    def test_cleanup_report_detects_diff(self):
        report = data_cleanup.cleanup_report(
            "示例", {"待用": ["A"]}, {"待用": ["A", "B"]}, recovered=True,
        )
        self.assertEqual(report["status"], "retained")
        self.assertTrue(report["diff"])

    def test_cleanup_ledger_writes_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cleanup.json"
            data_cleanup.write_cleanup_ledger(
                p, "示例", {"待用": []}, {"待用": []}, records={"created": []},
                recovered=True, note="ok",
            )
            data = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "restored")
            self.assertTrue(data["recovered"])

    def test_unrecovered_is_explicit(self):
        report = data_cleanup.cleanup_report("示例", {}, {}, recovered=False, note="需保留")
        self.assertEqual(report["status"], "not_restored")
        self.assertFalse(report["recovered"])


if __name__ == "__main__":
    unittest.main()
