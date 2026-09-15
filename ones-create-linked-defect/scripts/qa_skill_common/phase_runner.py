# -*- coding: utf-8 -*-
"""通用分阶段运行器：单次登录、用例检查点、数据台账与恢复执行。

设计目标：
- 阶段/用例状态持久化到 run_state.json，每条用例执行后写盘；
- --resume 时跳过已通过用例，只重跑失败、阻塞和未执行项；
- 基础能力异常（定位/超时/连接）快停当前阶段并保存现场；
- 业务失败记录后继续，避免单条业务用例阻断同阶段后续用例；
- 测试数据统一写入 data_ledger.json，供恢复和报告使用。
"""
from __future__ import annotations

import json
import shutil
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .preflight import PreflightCheck, PreflightRunner

try:  # 未安装 Playwright 时仍可导入本模块做离线测试
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover
    class PlaywrightError(Exception):
        pass

    class PlaywrightTimeoutError(Exception):
        pass

PASS = "通过"
FAIL = "失败"
BLOCK = "阻塞"
UNCOVERED = "未覆盖"
OBSERVATION = "环境观察"
VALID_STATUSES = {PASS, FAIL, BLOCK, UNCOVERED, OBSERVATION}

BLOCKER_PRODUCT = "产品缺陷"
BLOCKER_TEST_DATA = "测试数据"
BLOCKER_SCRIPT = "脚本问题"

_STATUS_ALIASES = {
    "pass": PASS, "passed": PASS, "success": PASS, "ok": PASS, PASS: PASS,
    "fail": FAIL, "failed": FAIL, "failure": FAIL, FAIL: FAIL,
    "block": BLOCK, "blocked": BLOCK, "skip": BLOCK, "skipped": BLOCK, BLOCK: BLOCK,
    "uncovered": UNCOVERED, "not_covered": UNCOVERED, UNCOVERED: UNCOVERED,
    "observation": OBSERVATION, "env": OBSERVATION, OBSERVATION: OBSERVATION,
}


class InfrastructureAbort(RuntimeError):
    """定位/弹窗/连接等基础能力异常；由 Runner 捕获并快停当前阶段。"""


class BusinessCaseFailure(AssertionError):
    """明确的业务断言失败；记录后继续同阶段后续用例。"""


def normalize_status(value: Any) -> str:
    """把中英文状态统一为 通过/失败/阻塞。"""
    text = str(value or "").strip()
    status = _STATUS_ALIASES.get(text.lower())
    if status:
        return status
    raise ValueError(f"未知用例状态: {value!r}")


def classify_exception(exc: BaseException) -> str:
    """返回 infrastructure 或 business。"""
    if isinstance(exc, (InfrastructureAbort, PlaywrightError, PlaywrightTimeoutError,
                        ConnectionError, TimeoutError)):
        return "infrastructure"
    return "business"


def classify_blocker(exc: BaseException) -> str:
    """把失败映射为产品缺陷、测试数据或脚本问题。"""
    if classify_exception(exc) == "infrastructure":
        return BLOCKER_SCRIPT
    return BLOCKER_PRODUCT


@dataclass
class CaseResult:
    status: str
    note: str = ""
    evidence: str = ""
    actual: str = ""
    data: dict = field(default_factory=dict)
    blocker_type: str = ""

    def __post_init__(self):
        self.status = normalize_status(self.status)


@dataclass
class CaseSpec:
    id: str
    run: Callable[["RunContext", Any], Any]
    module: str = ""
    depends_on: tuple[str, ...] = ()
    optional: bool = False


@dataclass
class CaseGroupSpec:
    """共享一次 setup/teardown 的 micro-case 组（典型场景：同一弹窗内连续校验）。"""
    id: str
    cases: tuple[CaseSpec, ...] = field(default_factory=tuple)
    setup: Callable[["RunContext", Any], Any] | None = None
    reset: Callable[["RunContext", Any], None] | None = None
    teardown: Callable[["RunContext", Any], None] | None = None
    optional: bool = False


@dataclass
class PhaseSpec:
    id: str
    cases: tuple[CaseSpec, ...] = field(default_factory=tuple)
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    setup: Callable[["RunContext", Any], None] | None = None
    teardown: Callable[["RunContext", Any], None] | None = None
    preflight: tuple[PreflightCheck, ...] = ()
    groups: tuple[CaseGroupSpec, ...] = ()
    provides_data: tuple[str, ...] = ()
    requires_data: tuple[str, ...] = ()


@dataclass
class RunContext:
    state: "RunState"
    page: Any = None
    extras: dict = field(default_factory=dict)

    @property
    def data(self) -> dict:
        return self.state.data

    def set_data(self, key: str, value: Any, **kwargs) -> None:
        self.state.set_data(key, value, **kwargs)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_case_result(raw: Any) -> CaseResult:
    """兼容 CaseResult / dict / tuple / 字符串 四类返回值。"""
    if isinstance(raw, CaseResult):
        return raw
    if isinstance(raw, dict):
        return CaseResult(
            status=raw.get("status") or raw.get("结果"),
            note=raw.get("note") or raw.get("备注") or raw.get("actual") or "",
            evidence=raw.get("evidence") or raw.get("证据") or "",
            actual=raw.get("actual") or raw.get("实际结果") or "",
            data=raw.get("data") or {},
            blocker_type=raw.get("blocker_type") or raw.get("阻塞类型") or "",
        )
    if isinstance(raw, (tuple, list)):
        values = list(raw) + [None, None, None]
        return CaseResult(status=values[0], evidence=values[1] or "", note=values[2] or "", actual=values[2] or "")
    return CaseResult(status=raw)


class RunState:
    """run_state.json + data_ledger.json 的读写与状态查询。"""

    SCHEMA_VERSION = 1

    def __init__(self, state_dir: str | Path, run_id: str, feature: str = "", data: dict | None = None):
        self.state_dir = Path(state_dir).expanduser()
        self.state_path = self.state_dir / "run_state.json"
        self.backup_path = self.state_dir / "run_state.json.bak"
        self.ledger_path = self.state_dir / "data_ledger.json"
        self.data = data.get("data", {}) if data else {}
        self.data_meta = data.get("data_meta", {}) if data else {}
        self.run_id = data.get("run_id", run_id) if data else run_id
        self.feature = data.get("feature", feature) if data else feature
        self.started_at = data.get("started_at", _now()) if data else _now()
        self.updated_at = data.get("updated_at", _now()) if data else _now()
        self.cases: dict[str, dict] = data.get("cases", {}) if data else {}
        self.groups: dict[str, dict] = data.get("groups", {}) if data else {}
        self.phases: dict[str, dict] = data.get("phases", {}) if data else {}
        self.meta: dict = data.get("meta", {}) if data else {}

    @classmethod
    def load_or_create(cls, state_dir: str | Path, run_id: str, feature: str = ""):
        state_dir = Path(state_dir).expanduser()
        state_path = state_dir / "run_state.json"
        backup_path = state_dir / "run_state.json.bak"
        for candidate in (state_path, backup_path):
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                state = cls(state_dir, run_id, feature, data=data)
                if candidate == backup_path:
                    state.meta["loaded_from_backup"] = True
                return state
            except Exception:
                continue
        state = cls(state_dir, run_id, feature)
        state.meta["created_new"] = True
        return state

    def to_dict(self) -> dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": self.run_id,
            "feature": self.feature,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "phases": self.phases,
            "groups": self.groups,
            "cases": self.cases,
            "data": self.data,
            "data_meta": self.data_meta,
            "meta": self.meta,
        }

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        if self.state_path.exists():
            try:
                shutil.copy2(self.state_path, self.backup_path)
            except Exception:
                pass
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.state_path)
        self._save_ledger()

    def _save_ledger(self) -> None:
        ledger = {
            "run_id": self.run_id,
            "feature": self.feature,
            "updated_at": self.updated_at,
            "records": self.data,
            "metadata": self.data_meta,
        }
        self.ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_data(self, key: str, value: Any, validator: Callable[[Any], Any] | None = None,
                 required: bool = True, note: str = "") -> None:
        self.data[key] = value
        if validator is not None or required or note:
            self.data_meta[key] = {
                "required": bool(required),
                "validator": getattr(validator, "__name__", type(validator).__name__) if validator else "",
                "note": note or "",
            }
        self.save()

    def validate_data(self, validators: dict[str, Callable[[Any], Any]] | None = None) -> dict:
        """校验业务台账；返回 {ok, checked, invalid, skipped, details}。

        只有注册了 validator 的 key 才会真正执行外部存在性检查；没有 validator 的必填 key
        记为 skipped，不会伪报失败。
        """
        validators = validators or {}
        keys = set(validators)
        keys.update(k for k, meta in self.data_meta.items() if meta.get("required", True))
        result = {"ok": True, "checked": [], "invalid": [], "skipped": [], "details": {}}
        for key in sorted(keys):
            if key not in self.data:
                result["invalid"].append(key)
                result["details"][key] = {"ok": False, "reason": "台账缺少数据"}
                continue
            fn = validators.get(key)
            if not fn:
                result["skipped"].append(key)
                result["details"][key] = {"ok": None, "reason": "未注册 validator"}
                continue
            try:
                raw = fn(self.data[key])
                if isinstance(raw, dict):
                    ok = bool(raw.get("ok"))
                    detail = raw
                else:
                    ok = bool(raw)
                    detail = {"ok": ok}
            except Exception as exc:
                ok = False
                detail = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
            result["checked"].append(key)
            result["details"][key] = detail
            if not ok:
                result["invalid"].append(key)
        result["ok"] = not result["invalid"]
        self.meta["ledger_validation"] = result
        self.save()
        return result

    def get_data(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def case_status(self, case_id: str) -> str | None:
        rec = self.cases.get(case_id) or {}
        return rec.get("status")

    def phase_status(self, phase_id: str) -> str | None:
        rec = self.phases.get(phase_id) or {}
        return rec.get("status")

    def mark_case(self, case_id: str, phase_id: str, status: str, note: str = "",
                  evidence: str = "", actual: str = "", data: dict | None = None,
                  blocker_type: str = "") -> None:
        status = normalize_status(status)
        previous = self.cases.get(case_id) or {}
        attempts = int(previous.get("attempts", 0)) + 1
        self.cases[case_id] = {
            "case_id": case_id,
            "phase_id": phase_id,
            "status": status,
            "note": note or "",
            "evidence": evidence or "",
            "actual": actual or note or "",
            "blocker_type": blocker_type or "",
            "attempts": attempts,
            "updated_at": _now(),
        }
        if data:
            self.data.setdefault("case_data", {})[case_id] = data
        self.save()

    def mark_group(self, group_id: str, phase_id: str, status: str, note: str = "") -> None:
        status = normalize_status(status)
        prev = self.groups.get(group_id) or {}
        self.groups[group_id] = {
            "group_id": group_id,
            "phase_id": phase_id,
            "status": status,
            "note": note or "",
            "attempts": int(prev.get("attempts", 0)) + 1,
            "updated_at": _now(),
        }
        self.save()

    def mark_phase(self, phase_id: str, status: str, note: str = "") -> None:
        status = normalize_status(status)
        prev = self.phases.get(phase_id) or {}
        self.phases[phase_id] = {
            "phase_id": phase_id,
            "status": status,
            "note": note or "",
            "attempts": int(prev.get("attempts", 0)) + 1,
            "updated_at": _now(),
        }
        self.save()

    def results_for_report(self) -> list[dict]:
        return [
            {
                "id": cid,
                "模块": rec.get("phase_id", ""),
                "结果": rec.get("status", BLOCK),
                "阻塞类型": rec.get("blocker_type", ""),
                "证据": rec.get("evidence", ""),
                "备注": rec.get("note", ""),
            }
            for cid, rec in self.cases.items()
        ]

    def summary(self) -> dict:
        counts = {PASS: 0, FAIL: 0, BLOCK: 0, UNCOVERED: 0, OBSERVATION: 0}
        for rec in self.cases.values():
            status = rec.get("status", BLOCK)
            if status not in counts:
                status = BLOCK
            counts[status] += 1
        return {
            "run_id": self.run_id,
            "feature": self.feature,
            "total": len(self.cases),
            "passed": counts[PASS],
            "failed": counts[FAIL],
            "blocked": counts[BLOCK],
            "uncovered": counts[UNCOVERED],
            "observations": counts[OBSERVATION],
            "blocker_types": {
                key: sum(1 for rec in self.cases.values() if rec.get("blocker_type") == key)
                for key in (BLOCKER_PRODUCT, BLOCKER_TEST_DATA, BLOCKER_SCRIPT)
            },
            "phases": self.phases,
        }


class PhaseRunner:
    """按阶段执行 CaseSpec，并在每个用例后落检查点。"""

    def __init__(self, page: Any, state: RunState, context: RunContext | None = None,
                 capture_failure: Callable[..., dict] | None = None, logger: Callable[[str], None] = print,
                 validators: dict[str, Callable[[Any], Any]] | None = None):
        self.page = page
        self.state = state
        self.context = context or RunContext(state=state, page=page)
        self.context.page = page
        self.capture_failure = capture_failure
        self.log = logger
        self.validators = validators or {}

    def run(self, phases: Iterable[PhaseSpec], resume: bool = False,
            selected_phase: str | None = None) -> dict:
        phase_list = list(phases)
        seen = set()
        for phase in phase_list:
            all_cases = list(phase.cases)
            for group in phase.groups:
                all_cases.extend(group.cases)
            for case in all_cases:
                if case.id in seen:
                    raise ValueError(f"重复用例ID: {case.id}")
                seen.add(case.id)
        run_set = self._resolve_phase_selection(phase_list, selected_phase)
        for phase in phase_list:
            if phase.id not in run_set:
                continue
            ledger = self.state.validate_data(self.validators)
            invalid_data = set(ledger.get("invalid", []))
            phase_invalid = bool(set(phase.provides_data) & invalid_data)
            required_invalid = (set(phase.requires_data) & invalid_data) - set(phase.provides_data)
            if required_invalid:
                note = f"数据台账失效: {', '.join(sorted(required_invalid))}"
                self.state.mark_phase(phase.id, BLOCK, note)
                self.log(f"[phase:{phase.id}] {BLOCK} {note}")
                continue
            if resume and self.state.phase_status(phase.id) == PASS and not phase_invalid:
                self.log(f"[phase:{phase.id}] 已完成，跳过")
                continue
            missing = [d for d in phase.depends_on if self.state.phase_status(d) != PASS]
            if missing:
                note = f"依赖阶段未通过: {', '.join(missing)}"
                self.state.mark_phase(phase.id, BLOCK, note)
                self.log(f"[phase:{phase.id}] {BLOCK} {note}")
                continue
            self._run_phase(phase, resume=resume, force_replay=phase_invalid)
        self.state.save()
        return self.state.summary()

    def _resolve_phase_selection(self, phases: list[PhaseSpec], selected_phase: str | None) -> set[str]:
        if not selected_phase:
            return {p.id for p in phases}
        by_id = {p.id: p for p in phases}
        if selected_phase not in by_id:
            raise ValueError(f"未知阶段: {selected_phase}")
        required = set()
        stack = [selected_phase]
        while stack:
            pid = stack.pop()
            if pid in required:
                continue
            required.add(pid)
            for dep in by_id[pid].depends_on:
                if dep not in by_id:
                    raise ValueError(f"阶段 {pid} 依赖未知阶段: {dep}")
                stack.append(dep)
        return required

    def _run_phase(self, phase: PhaseSpec, resume: bool, force_replay: bool = False) -> None:
        self.log(f"[phase:{phase.id}] 开始" + ("（台账失效，强制重跑）" if force_replay else ""))
        if phase.preflight:
            report = PreflightRunner().run(self.page, phase.preflight)
            self.state.meta.setdefault("preflight", {})[phase.id] = report.to_dict()
            if not report.ok:
                self._handle_infrastructure(
                    phase.id, "preflight", InfrastructureAbort(report.summary()), phase,
                )
                return
        if phase.setup:
            try:
                phase.setup(self.context, self.page)
            except Exception as exc:
                self._handle_infrastructure(phase.id, "<setup>", exc, phase)
                return

        blocked = False
        for case in self._pending_cases(phase.cases, resume, force_replay):
            if self._run_one_case(case, phase, resume=False, force_replay=force_replay):
                blocked = True
                break
        for group in phase.groups:
            if blocked:
                break
            if self._run_group(group, phase, resume=resume, force_replay=force_replay):
                blocked = True

        if phase.teardown:
            try:
                phase.teardown(self.context, self.page)
            except Exception as exc:
                note = f"teardown失败: {type(exc).__name__}: {exc}"
                self.state.meta.setdefault("teardown_errors", {})[phase.id] = note
        if not blocked:
            phase_cases = list(phase.cases)
            for group in phase.groups:
                phase_cases.extend(group.cases)
            statuses = [self.state.cases.get(c.id, {}).get("status") for c in phase_cases]
            if BLOCK in statuses:
                status = BLOCK
            elif FAIL in statuses:
                status = FAIL
            elif UNCOVERED in statuses:
                status = UNCOVERED
            elif OBSERVATION in statuses:
                status = OBSERVATION
            else:
                status = PASS
            self.state.mark_phase(phase.id, status)
            self.log(f"[phase:{phase.id}] {status}")
        self.state.save()

    def _pending_cases(self, cases: tuple[CaseSpec, ...], resume: bool, force_replay: bool):
        pending = []
        for case in cases:
            if resume and not force_replay and self.state.case_status(case.id) == PASS:
                self.log(f"[{case.id}] 已完成，跳过")
                continue
            pending.append(case)
        return pending

    def _run_one_case(self, case: CaseSpec, phase: PhaseSpec, resume: bool,
                      force_replay: bool = False) -> bool:
        """返回 True 表示基础异常，调用方应停止当前阶段。"""
        if resume and not force_replay and self.state.case_status(case.id) == PASS:
            self.log(f"[{case.id}] 已完成，跳过")
            return False
        missing = [d for d in case.depends_on if self.state.case_status(d) != PASS]
        if missing:
            note = f"依赖用例未通过: {', '.join(missing)}"
            self.state.mark_case(case.id, phase.id, BLOCK, note=note, blocker_type=BLOCKER_TEST_DATA)
            self.log(f"[{case.id}] {BLOCK} {note}")
            return False
        try:
            result = normalize_case_result(case.run(self.context, self.page))
            self.state.mark_case(
                case.id, phase.id, result.status, note=result.note,
                evidence=result.evidence, actual=result.actual, data=result.data,
                blocker_type=result.blocker_type,
            )
            self.log(f"[{case.id}] {result.status} {result.note}")
            return False
        except Exception as exc:
            if classify_exception(exc) == "infrastructure":
                self._handle_infrastructure(phase.id, case.id, exc, phase)
                return True
            note = f"{type(exc).__name__}: {exc}"
            self.state.mark_case(case.id, phase.id, FAIL, note=note, actual=note,
                                 blocker_type=classify_blocker(exc))
            self.log(f"[{case.id}] {FAIL} {note}")
            return False

    def _run_group(self, group: CaseGroupSpec, phase: PhaseSpec, resume: bool,
                   force_replay: bool = False) -> bool:
        """返回 True 表示基础异常，调用方应停止当前阶段。"""
        pending = self._pending_cases(group.cases, resume, force_replay)
        group_rec = self.state.groups.get(group.id) or {}
        if not pending:
            if group_rec.get("status") == PASS:
                self.log(f"[group:{group.id}] 已完成，跳过")
                return False
            # 上次 setup/teardown 失败但用例已通过：重跑整组以完成确定性收尾。
            pending = list(group.cases)
        self.log(f"[group:{group.id}] 开始（{len(pending)} 个 micro-case）")
        try:
            setup_result = group.setup(self.context, self.page) if group.setup else None
            self.context.extras.setdefault("groups", {})[group.id] = setup_result
        except Exception as exc:
            note = f"group setup失败: {type(exc).__name__}: {exc}"
            self._handle_infrastructure(phase.id, group.id, InfrastructureAbort(note), phase)
            for case in pending:
                if self.state.case_status(case.id) != PASS:
                    self.state.mark_case(case.id, phase.id, BLOCK, note=note)
            self.state.mark_group(group.id, phase.id, BLOCK, note)
            return True

        blocked = False
        for case in pending:
            if group.reset:
                try:
                    group.reset(self.context, self.page)
                except Exception as exc:
                    note = f"group reset失败: {type(exc).__name__}: {exc}"
                    self._handle_infrastructure(phase.id, group.id, InfrastructureAbort(note), phase)
                    for rest in pending:
                        if self.state.case_status(rest.id) != PASS:
                            self.state.mark_case(rest.id, phase.id, BLOCK, note=note)
                    self.state.mark_group(group.id, phase.id, BLOCK, note)
                    blocked = True
                    break
            if self._run_one_case(case, phase, resume=False, force_replay=force_replay):
                for rest in pending:
                    if self.state.case_status(rest.id) != PASS:
                        self.state.mark_case(rest.id, phase.id, BLOCK, note="group 因基础异常中止")
                self.state.mark_group(group.id, phase.id, BLOCK, note="group 因基础异常中止")
                blocked = True
                break

        if group.teardown:
            try:
                group.teardown(self.context, self.page)
            except Exception as exc:
                note = f"group teardown失败: {type(exc).__name__}: {exc}"
                self.state.meta.setdefault("group_teardown_errors", {})[group.id] = note
                self.state.mark_group(group.id, phase.id, BLOCK, note)
                self.state.mark_phase(phase.id, BLOCK, note)
                return True
        if not blocked:
            statuses = [self.state.case_status(c.id) for c in group.cases]
            if BLOCK in statuses:
                status = BLOCK
            elif FAIL in statuses:
                status = FAIL
            elif UNCOVERED in statuses:
                status = UNCOVERED
            elif OBSERVATION in statuses:
                status = OBSERVATION
            else:
                status = PASS
            self.state.mark_group(group.id, phase.id, status)
            self.log(f"[group:{group.id}] {status}")
        return blocked

    def _handle_infrastructure(self, phase_id: str, case_id: str, exc: Exception, phase: PhaseSpec) -> None:
        note = f"基础能力异常快停: {type(exc).__name__}: {exc}"
        trace = traceback.format_exc(limit=4)
        if self.capture_failure:
            context_extras = getattr(self.context, "extras", {}) or {}
            watcher = context_extras.get("watcher")
            network_recent = watcher.recent(30) if watcher and hasattr(watcher, "recent") else []
            try:
                diag = self.capture_failure(
                    page=self.page,
                    name=f"{case_id}_infrastructure",
                    case_id=case_id,
                    error=exc,
                    extra={
                        "traceback": trace,
                        "phase": phase_id,
                        "network_recent": network_recent,
                    },
                )
            except Exception as cap_exc:
                diag = {"screenshot": "", "json": "", "capture_error": str(cap_exc)}
        else:
            diag = {}
        self.state.mark_case(
            case_id, phase_id, BLOCK,
            note=note + (f"; 现场={diag.get('json', '')}" if diag.get("json") else ""),
            evidence=diag.get("screenshot", ""),
            actual=note,
            blocker_type=BLOCKER_SCRIPT,
        )
        self.state.mark_phase(phase_id, BLOCK, note=note)
        self.log(f"[{case_id}] {BLOCK} {note}")


__all__ = [
    "PASS", "FAIL", "BLOCK", "UNCOVERED", "OBSERVATION",
    "BLOCKER_PRODUCT", "BLOCKER_TEST_DATA", "BLOCKER_SCRIPT",
    "InfrastructureAbort", "BusinessCaseFailure",
    "CaseResult", "CaseSpec", "CaseGroupSpec", "PhaseSpec", "RunContext", "RunState", "PhaseRunner",
    "normalize_status", "normalize_case_result", "classify_exception", "classify_blocker",
]
