# -*- coding: utf-8 -*-
"""P0 测试就绪度缺口：oracle、决策、失败、阻塞和证据有效期。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import gaps as G  # noqa: E402
from qa_skill_common import run_package as RP  # noqa: E402


class GapsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "run"

    def _pkg(self):
        return RP.load_package(self.run_dir)

    def _analyze(self):
        pkg = self._pkg()
        return G.analyze_gaps(
            pkg["contract"] or {}, pkg["coverage"] or {}, pkg["evidence"] or {},
            pkg["manifest"] or {}, pkg["run_state"] or {}, pkg["defects"] or {},
        )

    def _add_case(self, case_id, priority="P0", status="通过", **extra):
        payload = {
            "id": case_id, "priority": priority, "requirement_refs": ["R-01"],
            "oracle_mode": "ui", "status": status,
        }
        payload.update(extra)
        RP.upsert_case(self.run_dir, payload)

    def _add_evidence(self, case_id="TC-01"):
        path = self.run_dir / "evidence" / (case_id + ".txt")
        path.write_text(case_id, encoding="utf-8")
        return RP.add_evidence(self.run_dir, path, case_id=case_id, source="ui")

    def test_ready_package_has_no_blocking_gaps(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        RP.set_requirement_oracle(self.run_dir, "R-01", mode="ui", expected="保存成功")
        self._add_case("TC-01")
        self._add_evidence("TC-01")
        result = self._analyze()
        self.assertTrue(result["ready"])
        self.assertEqual(result["summary"]["blocking_total"], 0)
        self.assertEqual(result["summary"]["oracle_coverage"], 1.0)

    def test_empty_package_is_not_ready(self):
        RP.init_run_package(self.run_dir, "空运行包", mode="standard")
        result = self._analyze()
        self.assertFalse(result["ready"])
        self.assertIn("empty_scope", result["blocking_categories"])

    def test_missing_oracle_is_blocking_for_standard(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        self._add_case("TC-01")
        self._add_evidence("TC-01")
        result = self._analyze()
        self.assertFalse(result["ready"])
        self.assertIn("missing_oracle", result["blocking_categories"])

    def test_oracle_required_evidence_channels_are_checked(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        RP.set_requirement_oracle(self.run_dir, "R-01", mode="ui", expected="x",
                                  evidence=["ui", "api"])
        self._add_case("TC-01")
        self._add_evidence("TC-01")
        result = self._analyze()
        self.assertFalse(result["ready"])
        gap = result["categories"]["missing_oracle_evidence"][0]
        self.assertEqual(gap["missing"], ["api"])

    def test_missing_oracle_is_visible_but_not_blocking_for_quick(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="quick", requirements=["R-01"])
        self._add_case("TC-01")
        self._add_evidence("TC-01")
        result = self._analyze()
        self.assertTrue(result["ready"])
        self.assertEqual(result["summary"]["by_category"]["missing_oracle"], 1)

    def test_execution_and_evidence_gaps_are_classified(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        RP.set_requirement_oracle(self.run_dir, "R-01", mode="ui", expected="x")
        self._add_case("TC-01", status="未执行")
        self._add_case("TC-02", status="失败", note="仍失败")
        self._add_case("TC-03", status="阻塞", blocker_type="测试数据", note="缺少人员")
        result = self._analyze()
        self.assertEqual(result["categories"]["not_run"][0]["id"], "TC-01")
        self.assertEqual(result["categories"]["failed_cases"][0]["id"], "TC-02")
        self.assertEqual(result["categories"]["blocked_data"][0]["id"], "TC-03")
        self.assertTrue(any(x["id"] == "TC-02" for x in result["categories"]["missing_evidence"]))

    def test_exclusion_waives_requirement_and_case(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        self._add_case("TC-01", status="未执行")
        RP.merge_coverage_metadata(self.run_dir, exclusions=[{
            "requirement_ref": "R-01", "reason": "用户明确要求忽略",
        }])
        result = self._analyze()
        self.assertTrue(result["ready"])
        self.assertEqual(result["summary"]["waived"], 2)
        self.assertFalse(result["categories"]["not_run"])

    def test_stale_evidence_blocks_ready(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        RP.set_requirement_oracle(self.run_dir, "R-01", mode="ui", expected="预期 A")
        self._add_case("TC-01")
        self._add_evidence("TC-01")
        self.assertTrue(self._analyze()["ready"])
        RP.set_requirement_oracle(self.run_dir, "R-01", mode="ui", expected="预期 B")
        result = self._analyze()
        self.assertFalse(result["ready"])
        self.assertEqual(result["summary"]["by_category"]["stale_evidence"], 1)
        self.assertEqual(result["categories"]["stale_evidence"][0]["case_id"], "TC-01")

    def test_pending_decision_blocks_ready(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        RP.set_requirement_oracle(self.run_dir, "R-01", mode="ui", expected="x")
        self._add_case("TC-01")
        self._add_evidence("TC-01")
        RP.append_decision(self.run_dir, {
            "requirement_ids": ["R-01"], "status": "pending", "resolution": "等产品确认",
        })
        result = self._analyze()
        self.assertFalse(result["ready"])
        self.assertTrue(result["categories"]["pending_decision"])

    def test_expired_decision_blocks_ready(self):
        RP.init_run_package(self.run_dir, "示例功能", mode="standard", requirements=["R-01"])
        RP.set_requirement_oracle(self.run_dir, "R-01", mode="ui", expected="x")
        self._add_case("TC-01")
        self._add_evidence("TC-01")
        RP.append_decision(self.run_dir, {
            "requirement_ids": ["R-01"], "status": "confirmed",
            "resolution": "旧口径", "valid_until": "2000-01-01",
        })
        result = self._analyze()
        self.assertFalse(result["ready"])
        self.assertTrue(any("已超过有效期" in x["reason"]
                            for x in result["categories"]["pending_decision"]))


if __name__ == "__main__":
    unittest.main()
