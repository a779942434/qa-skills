# -*- coding: utf-8 -*-
"""oracle 判定树与缺陷准入门槛测试。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import oracle  # noqa: E402


class AssessTest(unittest.TestCase):
    def test_requirement_risk_wins_first(self):
        r = oracle.assess(requirement_status="ambiguous", preconditions_ok=True,
                          evidence_channels=["ui", "api"], reproducibility="2/2")
        self.assertEqual(r["classification"], "requirement_risk")
        self.assertFalse(r["fileable"])

    def test_environment_blocked(self):
        r = oracle.assess(preconditions_ok=False)
        self.assertEqual(r["classification"], "environment_blocked")
        self.assertFalse(r["fileable"])

    def test_single_signal_is_test_artifact_for_p1(self):
        r = oracle.assess(severity="P1", evidence_channels=["ui"], reproducibility="2/2")
        self.assertEqual(r["classification"], "test_artifact")
        self.assertFalse(r["fileable"])

    def test_deterministic_api_single_channel_is_allowed(self):
        r = oracle.assess(severity="P1", evidence_channels=["api"],
                          allow_single_channel=True,
                          reproducibility={"attempts": 1, "successes": 1,
                                           "deterministic_api": True},
                          actual_matches_expected=False)
        self.assertEqual(r["classification"], "implementation_defect")
        self.assertTrue(r["fileable"])
        self.assertEqual(r["confidence"], "medium")

    def test_p1_two_sources_two_reproductions_is_fileable(self):
        r = oracle.assess(severity="P1", evidence_channels=["ui", "api"],
                          reproducibility="2/2", actual_matches_expected=False)
        self.assertEqual(r["classification"], "implementation_defect")
        self.assertTrue(r["fileable"])
        self.assertEqual(r["confidence"], "high")

    def test_invariant_failure_is_requirement_risk(self):
        r = oracle.assess(evidence_channels=["ui", "api"], reproducibility="2/2",
                          actual_matches_expected=True, invariant_ok=False)
        self.assertEqual(r["classification"], "requirement_risk")


class DefectGateTest(unittest.TestCase):
    def _record(self, **updates):
        rec = {
            "id": "BUG-001",
            "title": "示例缺陷",
            "classification": "implementation_defect",
            "confidence": "high",
            "severity_local": "P1",
            "requirement_refs": ["R-01"],
            "evidence_ids": ["EV-1", "EV-2"],
            "evidence_channels": ["ui", "api"],
            "reproducibility": "2/2",
            "environment": "test",
            "expected": "成功",
            "actual": "失败",
            "steps": "1. 操作",
            "status": "ready",
        }
        rec.update(updates)
        return rec

    def test_complete_record_passes(self):
        r = oracle.validate_defect(self._record())
        self.assertTrue(r["ok"], r)

    def test_requirement_risk_cannot_be_submitted(self):
        r = oracle.validate_defect(self._record(classification="requirement_risk"))
        self.assertFalse(r["ok"])
        self.assertTrue(any("implementation_defect" in e for e in r["errors"]))

    def test_missing_evidence_fails(self):
        r = oracle.validate_defect(self._record(evidence_ids=[], evidence_channels=[]))
        self.assertFalse(r["ok"])
        self.assertTrue(any("证据" in e for e in r["errors"]))

    def test_single_attempt_fails_for_p1(self):
        r = oracle.validate_defect(self._record(reproducibility="1/2"))
        self.assertFalse(r["ok"])
        self.assertTrue(any("2/2" in e for e in r["errors"]))

    def test_fingerprint_is_stable_and_keyed(self):
        a = oracle.defect_fingerprint(self._record())
        b = oracle.defect_fingerprint(self._record(title="另一个标题"))
        self.assertEqual(a, oracle.defect_fingerprint(self._record()))
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
