# -*- coding: utf-8 -*-
"""运行包指标聚合测试。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import metrics  # noqa: E402
from qa_skill_common import run_package as RP  # noqa: E402
from qa_skill_common.phase_runner import RunState  # noqa: E402


class MetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run_dir = self.root / "run-a"
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        self.state = RunState.load_or_create(self.run_dir, "R1", "示例功能")
        self.state.mark_cleanup("clean")
        (self.run_dir / "judgements.jsonl").write_text('{"kind":"verdict","ok":true}\n', encoding="utf-8")
        (self.run_dir / "contract.json").write_text(json.dumps({
            "requirements": [{"id": "R-01", "status": "defined", "case_ids": ["TC-01"]}],
            "decisions": [],
        }, ensure_ascii=False), encoding="utf-8")
        (self.run_dir / "coverage.json").write_text(json.dumps({
            "cases": [{"id": "TC-01", "priority": "P1", "requirement_refs": ["R-01"],
                       "status": "通过", "evidence_required": True}],
            "invariants": [], "exclusions": [],
        }, ensure_ascii=False), encoding="utf-8")
        evidence = self.run_dir / "evidence" / "x.txt"
        evidence.write_text("x", encoding="utf-8")
        RP.add_evidence(self.run_dir, evidence, case_id="TC-01", source="api")

    def test_collects_summary_and_run(self):
        result = metrics.collect_metrics(self.root)
        self.assertEqual(result["summary"]["runs"], 1)
        self.assertEqual(result["summary"]["cases"], 1)
        self.assertEqual(result["summary"]["qa_action_adoption"], 1.0)
        self.assertEqual(result["summary"]["requirement_coverage_avg"], 1.0)
        self.assertEqual(result["runs"][0]["feature"], "示例功能")

    def test_since_filters_runs(self):
        result = metrics.collect_metrics(self.root, since="2999-01-01")
        self.assertEqual(result["summary"]["runs"], 0)

    def test_wall_time_is_aggregated(self):
        RP.update_manifest(
            self.run_dir,
            started_at="2026-11-02T10:00:00+08:00",
            completed_at="2026-11-02T10:00:05+08:00",
        )
        result = metrics.collect_metrics(self.root)
        self.assertEqual(result["summary"]["total_wall_time_ms"], 5000)
        self.assertEqual(result["runs"][0]["wall_time_ms"], 5000)

    def test_legacy_run_is_counted(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        (legacy / "run_state.json").write_text(json.dumps({
            "run_id": "L1", "feature": "旧功能",
            "cases": {"C1": {"status": "通过"}},
        }, ensure_ascii=False), encoding="utf-8")
        result = metrics.collect_metrics(self.root)
        self.assertEqual(result["summary"]["runs"], 2)
        self.assertEqual(result["summary"]["legacy_runs"], 1)


if __name__ == "__main__":
    unittest.main()
