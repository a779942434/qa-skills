# -*- coding: utf-8 -*-
"""标准运行包初始化、证据索引和综合审计测试。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import run_package as RP  # noqa: E402
from qa_skill_common.phase_runner import RunState  # noqa: E402


class InitAndEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "run"

    def test_init_creates_standard_files_and_state(self):
        paths = RP.init_run_package(self.run_dir, "示例功能", mode="standard",
                                    requirements=["#205602"])
        for key in ("manifest", "contract", "coverage", "evidence", "defects"):
            self.assertTrue(Path(paths[key]).exists(), key)
        state = RunState.load_or_create(self.run_dir, "R1", "示例功能")
        state.mark_cleanup("clean")
        self.assertTrue((self.run_dir / "run_state.json").exists())
        self.assertTrue((self.run_dir / "data_ledger.json").exists())

    def test_init_refuses_existing_without_force(self):
        RP.init_run_package(self.run_dir, "示例功能")
        with self.assertRaises(FileExistsError):
            RP.init_run_package(self.run_dir, "示例功能")

    def test_add_evidence_hashes_and_deduplicates(self):
        RP.init_run_package(self.run_dir, "示例功能")
        evidence_file = self.run_dir / "evidence" / "shot.png"
        evidence_file.write_bytes(b"fake-png")
        first = RP.add_evidence(self.run_dir, evidence_file, case_id="TC-01", source="ui")
        second = RP.add_evidence(self.run_dir, evidence_file, case_id="TC-01", source="ui")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["path"], "evidence/shot.png")
        self.assertEqual(len(first["sha256"]), 64)

    def test_append_decision_is_persisted(self):
        RP.init_run_package(self.run_dir, "示例功能")
        rec = RP.append_decision(self.run_dir, {
            "requirement_ids": ["R-01"], "status": "resolved",
            "resolution": "按产品口径 A",
        })
        data = json.loads((self.run_dir / "contract.json").read_text(encoding="utf-8"))
        self.assertEqual(data["decisions"][0]["id"], rec["id"])
        self.assertEqual(data["decisions"][0]["resolution"], "按产品口径 A")

    def test_legacy_package_is_warning_not_crash(self):
        (self.run_dir).mkdir(parents=True, exist_ok=True)
        (self.run_dir / "run_state.json").write_text("{}", encoding="utf-8")
        audit = RP.audit_run_package(self.run_dir, strict=True)
        self.assertTrue(audit["summary"]["legacy"])
        self.assertTrue(any("legacy" in w for w in audit["warnings"]))


class StrictAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "run"
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        self.state = RunState.load_or_create(self.run_dir, "R2", "示例功能")
        self.state.mark_cleanup("clean")

    def _write(self, name, payload):
        (self.run_dir / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_strict_audit_passes_complete_package(self):
        contract = {
            "schema_version": 1,
            "requirements": [{"id": "R-01", "status": "defined", "case_ids": ["TC-01"]}],
            "decisions": [],
        }
        coverage = {
            "schema_version": 1,
            "cases": [{"id": "TC-01", "priority": "P0", "requirement_refs": ["R-01"],
                       "invariant_ids": ["I-01"], "oracle_mode": "ui",
                       "evidence_required": True, "status": "通过"}],
            "invariants": [{"id": "I-01", "case_ids": ["TC-01"]}],
            "exclusions": [],
        }
        self._write("contract.json", contract)
        self._write("coverage.json", coverage)
        evidence_file = self.run_dir / "evidence" / "shot.png"
        evidence_file.write_bytes(b"evidence")
        ev = RP.add_evidence(self.run_dir, evidence_file, case_id="TC-01", source="ui")
        self._write("defects.json", {"schema_version": 1, "defects": []})
        # 判定日志存在，且没有 UI 判定缺失
        (self.run_dir / "judgements.jsonl").write_text(
            json.dumps({"kind": "verdict", "ok": True}) + "\n", encoding="utf-8")
        audit = RP.audit_run_package(self.run_dir, strict=True)
        self.assertTrue(audit["ok"], audit)
        self.assertEqual(audit["summary"]["evidence_items"], 1)
        self.assertEqual(ev["case_id"], "TC-01")

    def test_strict_audit_catches_missing_evidence(self):
        contract = {"schema_version": 1,
                    "requirements": [{"id": "R-01", "status": "defined", "case_ids": ["TC-01"]}],
                    "decisions": []}
        coverage = {"schema_version": 1,
                    "cases": [{"id": "TC-01", "priority": "P0", "requirement_refs": ["R-01"],
                               "status": "通过"}],
                    "invariants": [], "exclusions": []}
        self._write("contract.json", contract)
        self._write("coverage.json", coverage)
        (self.run_dir / "judgements.jsonl").write_text("{}\n", encoding="utf-8")
        audit = RP.audit_run_package(self.run_dir, strict=True)
        self.assertFalse(audit["ok"])
        self.assertTrue(any("证据" in e for e in audit["errors"]))

    def test_defect_gate_blocks_requirement_risk(self):
        rec = {
            "id": "BUG-01", "title": "风险", "classification": "requirement_risk",
            "confidence": "high", "severity_local": "P1", "requirement_refs": ["R-01"],
            "evidence_ids": ["EV-1"], "evidence_channels": ["ui", "api"],
            "reproducibility": "2/2", "environment": "test", "expected": "x",
            "actual": "y", "steps": "1", "status": "ready",
        }
        self._write("defects.json", {"schema_version": 1, "defects": [rec]})
        audit = RP.audit_run_package(self.run_dir, strict=False)
        self.assertFalse(audit["ok"])
        self.assertTrue(any("implementation_defect" in e for e in audit["errors"]))


if __name__ == "__main__":
    unittest.main()
