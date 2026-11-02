# -*- coding: utf-8 -*-
"""需求、用例、风险和不变量覆盖审计。

设计上不解析 Markdown：用例生成技能负责产出结构化 sidecar，运行器负责把
CaseSpec 元数据写入 run_state，本模块只审计两者的映射是否完整。
"""
from __future__ import annotations

from typing import Any

VALID_PRIORITIES = ("P0", "P1", "P2", "P3")
UNDEFINED_STATUSES = ("undefined", "ambiguous", "conflict", "changed", "pending")
EXECUTED_STATUSES = ("通过", "失败", "环境观察", "pass", "fail", "observation")


def _state_cases(run_state: Any) -> dict[str, dict]:
    if not run_state:
        return {}
    if hasattr(run_state, "cases"):
        return dict(run_state.cases or {})
    if isinstance(run_state, dict):
        return dict(run_state.get("cases") or {})
    return {}


def _decisions(contract: dict) -> list[dict]:
    return list((contract or {}).get("decisions") or [])


def _decision_resolved(contract: dict, requirement_id: str) -> bool:
    for decision in _decisions(contract):
        refs = decision.get("requirement_ids") or decision.get("requirements") or []
        if requirement_id not in refs:
            continue
        if str(decision.get("status") or "").lower() in ("resolved", "waived", "approved", "confirmed"):
            return True
    return False


def normalize_cases(coverage: dict, run_state: Any = None) -> dict[str, dict]:
    cases: dict[str, dict] = {}
    for item in (coverage or {}).get("cases") or []:
        cid = str(item.get("id") or "").strip()
        if cid:
            cases[cid] = dict(item)
    for cid, rec in _state_cases(run_state).items():
        item = cases.setdefault(str(cid), {"id": str(cid)})
        item.setdefault("priority", rec.get("priority") or "P2")
        item.setdefault("requirement_refs", rec.get("requirement_refs") or [])
        item.setdefault("invariant_ids", rec.get("invariant_ids") or [])
        item.setdefault("oracle_mode", rec.get("oracle_mode") or "ui")
        item.setdefault("evidence_required", rec.get("evidence_required", True))
        item["status"] = rec.get("status") or item.get("status") or ""
        if rec.get("note"):
            item["note"] = rec.get("note")
        if rec.get("blocker_type"):
            item["blocker_type"] = rec.get("blocker_type")
        if rec.get("classification"):
            item["classification"] = rec.get("classification")
        if rec.get("confidence"):
            item["confidence"] = rec.get("confidence")
    return cases


def audit_coverage(contract: dict, coverage: dict, run_state: Any = None, *, strict: bool = False) -> dict:
    """审计 ``需求原文 → R-xx → 用例/排除/决策`` 和风险/不变量映射。"""
    contract = contract or {}
    coverage = coverage or {}
    errors: list[str] = []
    warnings: list[str] = []
    requirements = list(contract.get("requirements") or [])
    cases = normalize_cases(coverage, run_state)
    exclusions = list(coverage.get("exclusions") or [])
    invariants = list(coverage.get("invariants") or [])

    req_ids = []
    for req in requirements:
        rid = str(req.get("id") or "").strip()
        if not rid:
            errors.append("存在缺少 id 的需求条款")
            continue
        req_ids.append(rid)
        status = str(req.get("status") or "defined").lower()
        referenced = list(req.get("case_ids") or [])
        excluded = any(str(x.get("requirement_ref") or x.get("id") or "") == rid for x in exclusions)
        resolved = _decision_resolved(contract, rid)
        if status in UNDEFINED_STATUSES and not resolved:
            (errors if strict else warnings).append(f"{rid}: 需求状态为 {status}，但缺少已解决决策")
        if not referenced and not excluded and not resolved:
            (errors if strict else warnings).append(f"{rid}: 未映射用例、排除项或已解决决策")
        for cid in referenced:
            if str(cid) not in cases:
                errors.append(f"{rid}: 引用了不存在的用例 {cid}")

    if strict and not requirements:
        errors.append("缺少需求条款：standard/deep 运行不能是空合同")

    seen = set()
    for cid, case in cases.items():
        if cid in seen:
            errors.append(f"重复用例ID: {cid}")
        seen.add(cid)
        priority = str(case.get("priority") or "P2").upper()
        if priority not in VALID_PRIORITIES:
            errors.append(f"{cid}: 非法优先级 {priority}")
        refs = list(case.get("requirement_refs") or [])
        if not refs:
            errors.append(f"{cid}: 孤儿用例，未引用需求点")
        for rid in refs:
            if req_ids and str(rid) not in req_ids:
                errors.append(f"{cid}: 引用了不存在的需求点 {rid}")
        status = str(case.get("status") or "")
        if strict and priority in ("P0", "P1") and status not in EXECUTED_STATUSES:
            if status not in ("阻塞", "blocked"):
                errors.append(f"{cid}: P0/P1 用例尚未执行或未记录阻塞原因")
            elif not case.get("note") and not case.get("blocker_reason"):
                errors.append(f"{cid}: P0/P1 用例阻塞但未写原因")

    inv_case_ids = set(cases)
    for inv in invariants:
        iid = str(inv.get("id") or "").strip()
        if not iid:
            errors.append("存在缺少 id 的不变量")
            continue
        mapped = list(inv.get("case_ids") or [])
        if not mapped:
            (errors if strict else warnings).append(f"{iid}: 未映射到任何用例或检查点")
        for cid in mapped:
            if str(cid) not in inv_case_ids:
                errors.append(f"{iid}: 引用了不存在的用例 {cid}")

    excluded_refs = set()
    for ex in exclusions:
        rid = str(ex.get("requirement_ref") or ex.get("id") or "")
        if not rid or not ex.get("reason"):
            errors.append("排除项必须包含 requirement_ref 和 reason")
        else:
            excluded_refs.add(rid)

    clause_total = len(requirements)
    clause_mapped = 0
    for req in requirements:
        rid = str(req.get("id") or "")
        if req.get("case_ids") or rid in excluded_refs or _decision_resolved(contract, rid):
            clause_mapped += 1
    invariant_total = len(invariants)
    invariant_mapped = sum(1 for inv in invariants if inv.get("case_ids"))
    high_risk = [c for c in cases.values() if str(c.get("priority") or "P2").upper() in ("P0", "P1")]
    high_risk_done = [c for c in high_risk if str(c.get("status") or "") in EXECUTED_STATUSES]
    warnings_list = [
        c["id"] for c in high_risk
        if str(c.get("evidence_required", True)).lower() not in ("false", "0", "no")
    ]
    summary = {
        "requirements": clause_total,
        "requirements_mapped": clause_mapped,
        "requirement_coverage": round(clause_mapped / clause_total, 4) if clause_total else 0.0,
        "cases": len(cases),
        "p0_p1_cases": len(high_risk),
        "p0_p1_executed": len(high_risk_done),
        "invariants": invariant_total,
        "invariants_mapped": invariant_mapped,
        "invariant_coverage": round(invariant_mapped / invariant_total, 4) if invariant_total else 0.0,
        "evidence_required_cases": warnings_list,
    }
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "cases": cases,
        "requirements": requirements,
        "invariants": invariants,
        "exclusions": exclusions,
    }
