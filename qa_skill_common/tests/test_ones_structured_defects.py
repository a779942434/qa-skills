# -*- coding: utf-8 -*-
"""结构化 defects.json 进入 ONES 前的门槛测试。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ones-create-linked-defect" / "scripts"))

import ones_submit_defects as ONE  # noqa: E402


class StructuredDefectsTest(unittest.TestCase):
    def _make(self, record, evidence_ids=("EV-1",)):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run = Path(tmp.name)
        (run / "evidence").mkdir()
        (run / "evidence" / "e.png").write_bytes(b"x")
        items = [{"id": eid, "path": "evidence/e.png", "type": "ui"} for eid in evidence_ids]
        (run / "evidence" / "index.json").write_text(
            json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
        (run / "defects.json").write_text(
            json.dumps({"schema_version": 1, "defects": [record]}, ensure_ascii=False),
            encoding="utf-8")
        return run / "defects.json"

    def _record(self, **updates):
        rec = {
            "id": "BUG-01", "title": "示例", "classification": "implementation_defect",
            "confidence": "high", "severity_local": "P1", "requirement_refs": ["R-01"],
            "evidence_ids": ["EV-1"], "evidence_channels": ["ui", "api"],
            "reproducibility": "2/2", "environment": "test", "expected": "成功",
            "actual": "失败", "steps": "1. 操作", "status": "ready",
        }
        rec.update(updates)
        return rec

    def test_complete_record_parses(self):
        path = self._make(self._record())
        bugs, _ = ONE.parse_defects_json(path)
        self.assertEqual(len(bugs), 1)
        self.assertEqual(bugs[0]["key"], "BUG-01")
        self.assertEqual(bugs[0]["evidence"], ["evidence/e.png"])

    def test_requirement_risk_is_rejected(self):
        path = self._make(self._record(classification="requirement_risk"))
        with self.assertRaises(SystemExit):
            ONE.parse_defects_json(path)

    def test_missing_evidence_id_is_rejected(self):
        path = self._make(self._record(evidence_ids=["EV-404"]))
        with self.assertRaises(SystemExit):
            ONE.parse_defects_json(path)


if __name__ == "__main__":
    unittest.main()
