# -*- coding: utf-8 -*-
"""需求、风险和不变量覆盖审计测试。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import coverage  # noqa: E402


class CoverageAuditTest(unittest.TestCase):
    def test_complete_mapping_passes(self):
        contract = {"requirements": [
            {"id": "R-01", "status": "defined", "case_ids": ["TC-01"]}
        ], "decisions": []}
        cov = {
            "cases": [{"id": "TC-01", "priority": "P0", "requirement_refs": ["R-01"],
                       "invariant_ids": ["I-01"], "status": "通过"}],
            "invariants": [{"id": "I-01", "case_ids": ["TC-01"]}],
            "exclusions": [],
        }
        result = coverage.audit_coverage(contract, cov, strict=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["summary"]["requirement_coverage"], 1.0)
        self.assertEqual(result["summary"]["invariant_coverage"], 1.0)

    def test_missing_case_is_error(self):
        contract = {"requirements": [{"id": "R-01", "status": "defined", "case_ids": []}],
                    "decisions": []}
        result = coverage.audit_coverage(contract, {}, strict=True)
        self.assertFalse(result["ok"])
        self.assertTrue(any("R-01" in e for e in result["errors"]))

    def test_open_ambiguity_is_error_in_strict(self):
        contract = {"requirements": [{"id": "R-01", "status": "ambiguous", "case_ids": ["TC-01"]}],
                    "decisions": []}
        cov = {"cases": [{"id": "TC-01", "priority": "P1", "requirement_refs": ["R-01"],
                          "status": "通过"}], "invariants": [], "exclusions": []}
        result = coverage.audit_coverage(contract, cov, strict=True)
        self.assertFalse(result["ok"])
        self.assertTrue(any("缺少已解决决策" in e for e in result["errors"]))

    def test_resolved_decision_satisfies_ambiguity(self):
        contract = {
            "requirements": [{"id": "R-01", "status": "ambiguous", "case_ids": []}],
            "decisions": [{"requirement_ids": ["R-01"], "status": "resolved", "resolution": "按 A"}],
        }
        result = coverage.audit_coverage(contract, {}, strict=True)
        self.assertTrue(result["ok"], result)

    def test_exclusion_requires_reason(self):
        contract = {"requirements": [{"id": "R-01", "status": "defined", "case_ids": []}],
                    "decisions": []}
        cov = {"exclusions": [{"requirement_ref": "R-01", "reason": "需求未定义"}],
               "cases": [], "invariants": []}
        result = coverage.audit_coverage(contract, cov, strict=True)
        self.assertTrue(result["ok"], result)


if __name__ == "__main__":
    unittest.main()
