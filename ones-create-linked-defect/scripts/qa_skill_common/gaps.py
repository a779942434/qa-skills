# -*- coding: utf-8 -*-
"""测试就绪度缺口：回答“还有什么没测/没通过/证据已过期”。

与 audit 的区别：
- audit 检查运行包结构和覆盖门禁；
- gaps 输出仍需人工决策的剩余风险，并区分阻塞、待确认、失败、证据失效和明确豁免。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from . import coverage as coverage_mod
from . import run_package

CATEGORY_KEYS = (
    "empty_scope",
    "missing_oracle",
    "missing_oracle_evidence",
    "pending_decision",
    "orphan_requirement",
    "not_run",
    "uncovered",
    "blocked_env",
    "blocked_data",
    "blocked_other",
    "failed_cases",
    "missing_evidence",
    "stale_evidence",
    "unbound_evidence",
    "waived",
)

BLOCKING_KEYS = tuple(k for k in CATEGORY_KEYS if k != "waived")
PASS_STATUSES = frozenset({"通过", "pass"})
FAIL_STATUSES = frozenset({"失败", "fail"})
UNCOVERED_STATUSES = frozenset({"未覆盖", "uncovered"})
NOT_RUN_STATUSES = frozenset({"", "未执行", "not_run", "pending_run"})
BLOCKED_STATUSES = frozenset({"阻塞", "blocked", "环境观察", "observation"})
RUN_EVIDENCE_STATUSES = frozenset({"通过", "pass", "失败", "fail", "阻塞", "blocked", "环境观察", "observation"})
RESOLVED_DECISION_STATUSES = frozenset({"resolved", "approved", "confirmed"})


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _refs(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, dict):
        values = [value.get("id") or value.get("requirement_ref") or ""]
    else:
        values = list(value)
    out: list[str] = []
    for item in values:
        ref = str(item or "").strip()
        if ref and ref not in out:
            out.append(ref)
    return out


def _decision_refs(decision: dict) -> list[str]:
    return _refs(decision.get("requirement_ids") or decision.get("requirements") or
                 decision.get("requirement_refs") or decision.get("requirement_id"))


def _oracle_present(req: dict) -> bool:
    oracle = req.get("oracle")
    if isinstance(oracle, dict) and _lower(oracle.get("mode")) and str(oracle.get("expected") or "").strip():
        return True
    # 兼容旧合同字段
    return bool(_lower(req.get("oracle_mode")) and str(req.get("expected") or "").strip())


def _expired(value: Any) -> bool:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return False
    try:
        stamp = datetime.fromisoformat(text)
    except Exception:
        return False
    if len(text) == 10:
        stamp = stamp.replace(hour=23, minute=59, second=59)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return datetime.now().astimezone() > stamp


def _blocker_category(case: dict) -> str:
    text = " ".join(str(x or "") for x in (
        case.get("blocker_type"), case.get("blocker_reason"), case.get("note"), case.get("classification")
    )).lower()
    if any(word in text for word in ("环境", "登录", "网络", "environment")):
        return "blocked_env"
    if any(word in text for word in ("测试数据", "数据", "造数", "data")):
        return "blocked_data"
    return "blocked_other"


def _case_label(case: dict, *, reason: str = "") -> dict:
    return {
        "id": str(case.get("id") or ""),
        "priority": str(case.get("priority") or "P2").upper(),
        "requirements": _refs(case.get("requirement_refs")),
        "status": str(case.get("status") or ""),
        "reason": reason or str(case.get("note") or case.get("blocker_reason") or ""),
    }


def analyze_gaps(contract: dict, coverage: dict, evidence: dict, manifest: dict,
                 run_state: Any = None, defects: dict | None = None) -> dict[str, Any]:
    """聚合可解释的剩余风险；返回全部条目和按类别摘要。"""
    contract = contract or {}
    coverage = coverage or {}
    manifest = manifest or {}
    cases = coverage_mod.normalize_cases(coverage, run_state)
    requirements = list(contract.get("requirements") or [])
    decisions = list(contract.get("decisions") or [])
    exclusions = list(coverage.get("exclusions") or [])
    evidence_items = list((evidence or {}).get("items") or [])
    mode = str(manifest.get("mode") or "quick").lower()
    categories: dict[str, list[dict]] = {key: [] for key in CATEGORY_KEYS}

    if not requirements:
        categories["empty_scope"].append({"id": "run", "reason": "运行包没有需求条款"})
    if not cases:
        categories["empty_scope"].append({"id": "run", "reason": "运行包没有用例"})

    waived_refs: dict[str, str] = {}
    resolved_refs: set[str] = set()
    for decision in decisions:
        status = _lower(decision.get("status"))
        refs = _decision_refs(decision)
        expired = _expired(decision.get("valid_until"))
        if status in RESOLVED_DECISION_STATUSES and not expired:
            resolved_refs.update(refs)
        elif status in RESOLVED_DECISION_STATUSES and expired:
            categories["pending_decision"].append({
                "id": str(decision.get("id") or ""),
                "requirements": refs,
                "reason": "决策已超过有效期",
                "source": "contract.decisions",
            })
        elif status == "waived" and not expired:
            for ref in refs:
                waived_refs[ref] = str(decision.get("resolution") or "决策已豁免")
            categories["waived"].append({
                "id": str(decision.get("id") or ""),
                "requirements": refs,
                "reason": str(decision.get("resolution") or "决策已豁免"),
                "source": "contract.decisions",
            })
        elif status == "waived" and expired:
            categories["pending_decision"].append({
                "id": str(decision.get("id") or ""),
                "requirements": refs,
                "reason": "豁免已超过有效期",
                "source": "contract.decisions",
            })
        elif status in ("open", "pending"):
            categories["pending_decision"].append({
                "id": str(decision.get("id") or ""),
                "requirements": refs,
                "reason": str(decision.get("resolution") or "决策尚未关闭"),
                "source": "contract.decisions",
            })
    for exclusion in exclusions:
        ref = str(exclusion.get("requirement_ref") or exclusion.get("id") or "").strip()
        if ref:
            waived_refs[ref] = str(exclusion.get("reason") or "已排除")
            categories["waived"].append({
                "id": ref,
                "requirements": [ref],
                "reason": str(exclusion.get("reason") or "已排除"),
                "source": "coverage.exclusions",
            })

    requirement_ids = set()
    oracle_total = 0
    oracle_present = 0
    for req in requirements:
        rid = str(req.get("id") or "").strip()
        if not rid:
            continue
        requirement_ids.add(rid)
        status = _lower(req.get("status") or "undefined")
        if status in ("waived", "rejected"):
            waived_refs.setdefault(rid, "需求状态为 {}".format(status))
            categories["waived"].append({
                "id": rid,
                "requirements": [rid],
                "reason": "需求状态为 {}".format(status),
                "source": "contract.requirements",
            })
            continue
        if rid in waived_refs:
            continue
        oracle_total += 1
        if _oracle_present(req):
            oracle_present += 1
        else:
            categories["missing_oracle"].append({
                "id": rid,
                "requirements": [rid],
                "reason": "缺少可执行判定依据（oracle.mode + oracle.expected）",
            })
        if status in coverage_mod.UNDEFINED_STATUSES and rid not in resolved_refs and rid not in waived_refs:
            categories["pending_decision"].append({
                "id": rid,
                "requirements": [rid],
                "reason": "需求状态为 {}，且没有已确认决策".format(status or "undefined"),
                "source": "contract.requirements",
            })
        if not _refs(req.get("case_ids")) and rid not in waived_refs and rid not in resolved_refs:
            categories["orphan_requirement"].append({
                "id": rid,
                "requirements": [rid],
                "reason": "需求条款未映射用例、排除项或已确认决策",
            })

    evidence_by_case: dict[str, list[dict]] = {}
    evidence_types_by_req: dict[str, set[str]] = {}
    for item in evidence_items:
        cid = str(item.get("case_id") or "")
        if cid:
            evidence_by_case.setdefault(cid, []).append(item)
        etype = _lower(item.get("type"))
        if not etype:
            continue
        channels = {"ui", "api", "db", "downstream"} if etype == "mixed" else {etype}
        case = cases.get(cid) or {}
        for ref in _refs(case.get("requirement_refs")):
            evidence_types_by_req.setdefault(ref, set()).update(channels)

    for req in requirements:
        rid = str(req.get("id") or "").strip()
        if not rid or rid in waived_refs:
            continue
        oracle = req.get("oracle") or {}
        required_channels = set(_lower(x) for x in (oracle.get("evidence") or []) if _lower(x))
        if not required_channels:
            continue
        actual_channels = evidence_types_by_req.get(rid, set())
        missing = sorted(required_channels - actual_channels)
        if missing:
            categories["missing_oracle_evidence"].append({
                "id": rid,
                "requirements": [rid],
                "required": sorted(required_channels),
                "actual": sorted(actual_channels),
                "missing": missing,
                "reason": "oracle 要求的证据通道未满足",
            })

    for case in cases.values():
        cid = str(case.get("id") or "")
        refs = _refs(case.get("requirement_refs"))
        case_waived = bool(refs) and all(ref in waived_refs for ref in refs)
        if case_waived:
            categories["waived"].append({
                "id": cid,
                "requirements": refs,
                "reason": "; ".join(waived_refs[ref] for ref in refs),
                "source": "coverage.cases",
            })
            continue
        status = _lower(case.get("status"))
        if status in PASS_STATUSES:
            pass
        elif status in FAIL_STATUSES:
            categories["failed_cases"].append(_case_label(case, reason=str(case.get("note") or "失败待复验")))
        elif status in UNCOVERED_STATUSES:
            categories["uncovered"].append(_case_label(case, reason=str(case.get("note") or "未覆盖")))
        elif status in NOT_RUN_STATUSES:
            categories["not_run"].append(_case_label(case, reason=str(case.get("note") or "尚未执行")))
        elif status in BLOCKED_STATUSES:
            categories[_blocker_category(case)].append(_case_label(case, reason=str(case.get("note") or "阻塞")))
        elif status in ("待确认", "pending"):
            categories["pending_decision"].append(_case_label(case, reason=str(case.get("note") or "用例待确认")))
        else:
            categories["not_run"].append(_case_label(case, reason="状态未识别：{}".format(status or "空")))

        required = str(case.get("evidence_required", True)).lower() not in ("false", "0", "no")
        if status in RUN_EVIDENCE_STATUSES and required and not evidence_by_case.get(cid):
            categories["missing_evidence"].append(_case_label(case, reason="要求证据但未记录"))

    invalid_evidence: dict[str, dict[str, dict]] = {"stale": {}, "unbound": {}}
    for item in evidence_items:
        validity = run_package.evidence_validity(item, contract, manifest)
        status = validity["status"]
        if status not in invalid_evidence:
            continue
        eid = str(item.get("id") or item.get("path") or "")
        cid = str(item.get("case_id") or "")
        did = str(item.get("defect_id") or "")
        key = cid or did or eid
        group = invalid_evidence[status].setdefault(key, {
            "id": cid or did or key,
            "case_id": cid,
            "defect_id": did,
            "evidence_ids": [],
            "count": 0,
            "reasons": [],
        })
        if eid:
            group["evidence_ids"].append(eid)
        group["count"] += 1
        for reason in validity.get("reasons") or []:
            if reason not in group["reasons"]:
                group["reasons"].append(reason)
    categories["stale_evidence"] = list(invalid_evidence["stale"].values())
    categories["unbound_evidence"] = list(invalid_evidence["unbound"].values())

    by_category = {key: len(categories[key]) for key in CATEGORY_KEYS}
    blocking_keys = list(BLOCKING_KEYS)
    if mode not in ("standard", "deep"):
        blocking_keys = [key for key in blocking_keys if key != "missing_oracle"]
    blocking_total = sum(by_category[key] for key in blocking_keys)
    oracle_coverage = round(oracle_present / oracle_total, 4) if oracle_total else 0.0
    summary = {
        "ready": blocking_total == 0,
        "blocking_total": blocking_total,
        "by_category": by_category,
        "requirements": len(requirements),
        "cases": len(cases),
        "evidence": len(evidence_items),
        "stale_evidence_items": sum(x.get("count", 0) for x in categories["stale_evidence"]),
        "unbound_evidence_items": sum(x.get("count", 0) for x in categories["unbound_evidence"]),
        "oracle_coverage": oracle_coverage,
        "waived": by_category["waived"],
    }
    actions = []
    action_map = (
        ("empty_scope", "先建立需求条款与用例，空运行包不算 ready"),
        ("missing_oracle", "为 R-xx 补 oracle.mode / oracle.expected"),
        ("missing_oracle_evidence", "补齐 oracle 要求的 UI/API/DB/下游证据通道"),
        ("pending_decision", "关闭待确认决策并记录 owner/source"),
        ("blocked_env", "修环境或记录环境阻塞原因"),
        ("blocked_data", "补造数配方并验证前置条件"),
        ("failed_cases", "复验失败用例，未修复前不得判定 ready"),
        ("stale_evidence", "重跑受影响用例或作废过期证据"),
        ("unbound_evidence", "重跑证据以绑定需求/环境版本"),
        ("not_run", "执行剩余用例"),
        ("uncovered", "补覆盖或记录明确豁免"),
    )
    for key, text in action_map:
        if by_category[key]:
            actions.append(text)
    return {
        "schema_version": 1,
        "mode": mode,
        "ready": blocking_total == 0,
        "blocking_categories": [key for key in blocking_keys if by_category[key]],
        "summary": summary,
        "next_actions": actions[:5],
        "categories": categories,
    }


def analyze_run_package(run_dir: str) -> tuple[dict, dict]:
    """读取运行包并分析缺口；供 CLI 使用，避免门面直接触碰状态文件。"""
    pkg = run_package.load_package(run_dir)
    result = analyze_gaps(
        pkg.get("contract") or {}, pkg.get("coverage") or {}, pkg.get("evidence") or {},
        pkg.get("manifest") or {}, pkg.get("run_state") or {}, pkg.get("defects") or {},
    )
    return pkg, result
