# -*- coding: utf-8 -*-
"""L1 离线单测：分阶段运行、检查点恢复和失败分级。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common.phase_runner import (  # noqa: E402
    BLOCK, FAIL, PASS, BusinessCaseFailure, CaseGroupSpec, CaseResult, CaseSpec,
    InfrastructureAbort, PhaseRunner, PhaseSpec, RunState,
)


class TestPhaseRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / "state"
        self.state = RunState.load_or_create(self.state_dir, "run-1", "单元测试")

    def tearDown(self):
        self.tmp.cleanup()

    def test_checkpoint_skips_passed_and_retries_failed(self):
        calls = []
        phase = PhaseSpec("p1", cases=(
            CaseSpec("c1", lambda ctx, page: (calls.append("c1") or CaseResult(PASS, "ok"))),
            CaseSpec("c2", lambda ctx, page: (calls.append("c2") or CaseResult(FAIL, "bad"))),
        ))
        runner = PhaseRunner(None, self.state)
        runner.run([phase])
        self.assertEqual(calls, ["c1", "c2"])
        self.assertEqual(self.state.case_status("c1"), PASS)
        self.assertEqual(self.state.case_status("c2"), FAIL)

        calls.clear()
        phase2 = PhaseSpec("p1", cases=(
            CaseSpec("c1", lambda ctx, page: (calls.append("c1") or CaseResult(PASS, "ok"))),
            CaseSpec("c2", lambda ctx, page: (calls.append("c2") or CaseResult(PASS, "fixed"))),
        ))
        runner2 = PhaseRunner(None, self.state)
        runner2.run([phase2], resume=True)
        self.assertEqual(calls, ["c2"])
        self.assertEqual(self.state.case_status("c2"), PASS)

    def test_business_failure_continues_same_phase(self):
        calls = []

        def fail_business(ctx, page):
            calls.append("c1")
            raise BusinessCaseFailure("业务断言不符")

        def pass_next(ctx, page):
            calls.append("c2")
            return CaseResult(PASS, "ok")

        phase = PhaseSpec("p1", cases=(CaseSpec("c1", fail_business), CaseSpec("c2", pass_next)))
        PhaseRunner(None, self.state).run([phase])
        self.assertEqual(calls, ["c1", "c2"])
        self.assertEqual(self.state.case_status("c1"), FAIL)
        self.assertEqual(self.state.case_status("c2"), PASS)
        self.assertEqual(self.state.phase_status("p1"), FAIL)

    def test_infrastructure_stops_phase_and_blocks_dependent_phase(self):
        calls = []
        captured = []

        def infra(ctx, page):
            calls.append("c1")
            raise InfrastructureAbort("hidden tab")

        def never(ctx, page):
            calls.append("c2")
            return CaseResult(PASS)

        def independent(ctx, page):
            calls.append("c3")
            return CaseResult(PASS)

        def capture(**kwargs):
            captured.append(kwargs["case_id"])
            return {"screenshot": "failure.png", "json": "failure.json"}

        phases = [
            PhaseSpec("p1", cases=(CaseSpec("c1", infra), CaseSpec("c2", never))),
            PhaseSpec("p2", cases=(CaseSpec("c3", never),), depends_on=("p1",)),
            PhaseSpec("p3", cases=(CaseSpec("c4", independent),)),
        ]
        PhaseRunner(None, self.state, capture_failure=capture).run(phases)
        self.assertEqual(calls, ["c1", "c3"])
        self.assertEqual(captured, ["c1"])
        self.assertEqual(self.state.case_status("c1"), BLOCK)
        self.assertEqual(self.state.phase_status("p1"), BLOCK)
        self.assertEqual(self.state.phase_status("p2"), BLOCK)
        self.assertEqual(self.state.case_status("c4"), PASS)

    def test_data_ledger_persists_after_reload(self):
        phase = PhaseSpec("p1", cases=(CaseSpec(
            "c1",
            lambda ctx, page: (ctx.set_data("record_no", "TEST-001") or CaseResult(PASS)),
        ),))
        PhaseRunner(None, self.state).run([phase])
        reloaded = RunState.load_or_create(self.state_dir, "run-1", "单元测试")
        self.assertEqual(reloaded.get_data("record_no"), "TEST-001")
        ledger = json.loads(reloaded.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(ledger["records"]["record_no"], "TEST-001")

    def test_corrupt_state_falls_back_to_backup(self):
        self.state.set_data("x", 1)
        self.state.save()
        self.state.set_data("x", 2)
        self.state.state_path.write_text("{broken", encoding="utf-8")
        recovered = RunState.load_or_create(self.state_dir, "run-1", "单元测试")
        self.assertTrue(recovered.meta.get("loaded_from_backup"))
        self.assertEqual(recovered.get_data("x"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestPreflightAndLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = RunState.load_or_create(Path(self.tmp.name) / "state", "run-preflight", "预检与台账")

    def tearDown(self):
        self.tmp.cleanup()

    def test_preflight_failure_blocks_phase_before_cases(self):
        from qa_skill_common.preflight import PreflightCheck

        calls = []

        def fail_check(page):
            return {"ok": False, "reason": "必需控件缺失"}

        phase = PhaseSpec(
            "p1",
            cases=(CaseSpec("c1", lambda ctx, page: (calls.append("c1") or CaseResult(PASS))),),
            preflight=(PreflightCheck("preflight-1", fail_check),),
        )
        captured = []
        runner = PhaseRunner(None, self.state, capture_failure=lambda **kw: captured.append(kw["case_id"]) or {})
        runner.run([phase])
        self.assertEqual(calls, [])
        self.assertEqual(self.state.phase_status("p1"), BLOCK)
        self.assertEqual(captured, ["preflight"])

    def test_invalid_ledger_forces_resume_replay(self):
        calls = []

        def setup(ctx, page):
            calls.append(ctx.state.get_data("record_no"))
            ctx.set_data("record_no", "VALID-001")
            return CaseResult(PASS)

        phase = PhaseSpec("setup", cases=(CaseSpec("c1", setup),), provides_data=("record_no",))
        runner = PhaseRunner(None, self.state, validators={"record_no": lambda v: v == "VALID-001"})
        runner.run([phase])
        self.assertEqual(self.state.phase_status("setup"), PASS)

        self.state.set_data("record_no", "STALE-001")
        runner.run([phase], resume=True)
        self.assertEqual(calls, [None, "STALE-001"])
        self.assertEqual(self.state.get_data("record_no"), "VALID-001")

    def test_missing_required_ledger_blocks_consumer_phase(self):
        calls = []
        self.state.data_meta["record_no"] = {"required": True, "validator": "", "note": ""}
        phase = PhaseSpec(
            "consume",
            cases=(CaseSpec("c1", lambda ctx, page: (calls.append("c1") or CaseResult(PASS))),),
            requires_data=("record_no",),
        )
        PhaseRunner(None, self.state, validators={"record_no": lambda v: False}).run([phase])
        self.assertEqual(calls, [])
        self.assertEqual(self.state.phase_status("consume"), BLOCK)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestMicroCaseGroups(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = RunState.load_or_create(Path(self.tmp.name) / "state", "run-groups", "弹窗 micro-case")

    def tearDown(self):
        self.tmp.cleanup()

    def test_group_setup_reset_teardown_once_per_batch(self):
        calls = {"setup": 0, "reset": 0, "teardown": 0, "cases": []}

        def setup(ctx, page):
            calls["setup"] += 1
            return {"dialog": "add"}

        def reset(ctx, page):
            calls["reset"] += 1

        def teardown(ctx, page):
            calls["teardown"] += 1

        def case(cid):
            def _run(ctx, page):
                calls["cases"].append(cid)
                self.assertEqual(ctx.extras["groups"]["dialog"]["dialog"], "add")
                return CaseResult(PASS, cid)
            return _run

        group = CaseGroupSpec(
            "dialog", cases=(CaseSpec("m1", case("m1")), CaseSpec("m2", case("m2"))),
            setup=setup, reset=reset, teardown=teardown,
        )
        PhaseRunner(None, self.state).run([PhaseSpec("p1", groups=(group,))])
        self.assertEqual(calls, {"setup": 1, "reset": 2, "teardown": 1, "cases": ["m1", "m2"]})
        self.assertEqual(self.state.groups["dialog"]["status"], PASS)

    def test_group_business_failure_continues_next_micro_case(self):
        calls = []

        def fail_business(ctx, page):
            calls.append("m1")
            raise BusinessCaseFailure("字段校验不符")

        def pass_next(ctx, page):
            calls.append("m2")
            return CaseResult(PASS)

        group = CaseGroupSpec("dialog", cases=(CaseSpec("m1", fail_business), CaseSpec("m2", pass_next)))
        PhaseRunner(None, self.state).run([PhaseSpec("p1", groups=(group,))])
        self.assertEqual(calls, ["m1", "m2"])
        self.assertEqual(self.state.case_status("m1"), FAIL)
        self.assertEqual(self.state.case_status("m2"), PASS)
        self.assertEqual(self.state.groups["dialog"]["status"], FAIL)
        self.assertEqual(self.state.phase_status("p1"), FAIL)

    def test_group_infrastructure_stops_remaining_and_can_resume(self):
        calls = []

        def infra(ctx, page):
            calls.append("m1")
            raise InfrastructureAbort("dialog missing")

        def never(ctx, page):
            calls.append("m2")
            return CaseResult(PASS)

        group = CaseGroupSpec("dialog", cases=(CaseSpec("m1", infra), CaseSpec("m2", never)))
        PhaseRunner(None, self.state, capture_failure=lambda **kw: {}).run([PhaseSpec("p1", groups=(group,))])
        self.assertEqual(calls, ["m1"])
        self.assertEqual(self.state.case_status("m1"), BLOCK)
        self.assertEqual(self.state.case_status("m2"), BLOCK)
        self.assertEqual(self.state.phase_status("p1"), BLOCK)

        calls.clear()
        resumed = CaseGroupSpec("dialog", cases=(
            CaseSpec("m1", lambda ctx, page: (calls.append("m1") or CaseResult(PASS))),
            CaseSpec("m2", lambda ctx, page: (calls.append("m2") or CaseResult(PASS))),
        ))
        PhaseRunner(None, self.state).run([PhaseSpec("p1", groups=(resumed,))], resume=True)
        self.assertEqual(calls, ["m1", "m2"])
        self.assertEqual(self.state.groups["dialog"]["status"], PASS)
        self.assertEqual(self.state.phase_status("p1"), PASS)

    def test_group_setup_skipped_when_all_cases_passed(self):
        setup_calls = []

        def setup(ctx, page):
            setup_calls.append("setup")

        case = CaseSpec("m1", lambda ctx, page: CaseResult(PASS))
        group = CaseGroupSpec("dialog", cases=(case,), setup=setup)
        phases = [PhaseSpec("p1", groups=(group,))]
        PhaseRunner(None, self.state).run(phases)
        PhaseRunner(None, self.state).run(phases, resume=True)
        self.assertEqual(setup_calls, ["setup"])
