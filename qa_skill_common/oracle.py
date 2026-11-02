# -*- coding: utf-8 -*-
"""测试结论判定树与缺陷准入门槛。

把“看到现象”转换成可审计的结论分类，避免把需求风险、环境问题或测试伪影
直接提交成实现缺陷。本模块只做纯逻辑判断，不依赖浏览器。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

CLASSIFICATIONS = (
    "implementation_defect",
    "requirement_risk",
    "environment_blocked",
    "test_artifact",
    "pass",
)
CONFIDENCES = ("high", "medium", "low")
SEVERITIES = ("P0", "P1", "P2", "P3")
DEFINED_REQUIREMENT_STATUSES = ("defined", "resolved", "confirmed", "confirmed_by_product")


def _channels(values: Iterable[str] | None) -> list[str]:
    out = []
    for item in values or ():
        text = str(item or "").strip().lower()
        if text and text not in out:
            out.append(text)
    return out


def normalize_reproducibility(value: Any) -> dict[str, Any]:
    """把 ``2/2``、``{"successes":2,"attempts":2}``、``2`` 归一化。"""
    if isinstance(value, dict):
        attempts = int(value.get("attempts") or value.get("total") or 0)
        successes = int(value.get("successes") or value.get("reproduced") or 0)
        deterministic = bool(value.get("deterministic_api") or value.get("deterministic"))
    elif isinstance(value, str):
        m = re.search(r"(\d+)\s*/\s*(\d+)", value)
        if m:
            successes, attempts = int(m.group(1)), int(m.group(2))
        else:
            successes = attempts = int(value) if value.isdigit() else 0
        deterministic = False
    else:
        successes = attempts = int(value or 0)
        deterministic = False
    return {
        "successes": successes,
        "attempts": attempts,
        "deterministic_api": deterministic,
    }


def reproduction_ok(value: Any) -> bool:
    repro = normalize_reproducibility(value)
    return bool(repro["deterministic_api"] or (
        repro["attempts"] >= 2 and repro["successes"] >= 2
    ))


def required_channels(severity: str = "P2", *, allow_single_channel: bool = False) -> int:
    if allow_single_channel:
        return 1
    return 2 if str(severity or "P2").upper() in ("P0", "P1") else 1


def assess(
    *,
    requirement_status: str = "defined",
    preconditions_ok: bool = True,
    evidence_channels: Iterable[str] | None = None,
    reproducibility: Any = None,
    actual_matches_expected: bool | None = None,
    invariant_ok: bool | None = None,
    severity: str = "P2",
    allow_single_channel: bool = False,
) -> dict[str, Any]:
    """按固定顺序判定结论分类与置信度。

    返回字段：``classification``、``confidence``、``fileable``、``reasons``、
    ``required_actions``。``fileable`` 只表示允许进入实现缺陷流程，不代表自动提 ONES。
    """
    reasons: list[str] = []
    actions: list[str] = []
    channels = _channels(evidence_channels)
    req_status = str(requirement_status or "undefined").strip().lower()
    needed = required_channels(severity, allow_single_channel=allow_single_channel)

    if req_status not in DEFINED_REQUIREMENT_STATUSES:
        classification = "requirement_risk"
        reasons.append("需求来源未明确或存在口径风险")
        actions.append("补充需求来源，并由产品/需求负责人确认口径")
    elif not preconditions_ok:
        classification = "environment_blocked"
        reasons.append("前置配置、数据或权限未满足")
        actions.append("补齐前置条件后重测，不直接报实现缺陷")
    elif len(channels) < needed:
        classification = "test_artifact"
        reasons.append(f"证据通道不足：{len(channels)}/{needed}")
        actions.append("补充 UI/API/DB/下游证据，或显式声明单通道测试模式")
    elif not reproduction_ok(reproducibility) and not allow_single_channel:
        classification = "test_artifact"
        reasons.append("未达到 2/2 或确定性接口复现")
        actions.append("按同一路径复测两次，或补确定性接口复现")
    elif actual_matches_expected is False:
        classification = "implementation_defect"
        reasons.append("预期明确、前置满足、证据可复现，且实测偏离预期")
        actions.append("补齐缺陷证据并进入缺陷门槛审核")
    elif invariant_ok is False:
        classification = "requirement_risk"
        reasons.append("实测可能符合当前口径，但违反业务不变量")
        actions.append("提交产品/业务确认，必要时形成需求变更或设计风险")
    else:
        classification = "pass"
        reasons.append("预期、前置、证据和复现均满足")

    if classification == "implementation_defect" and reproduction_ok(reproducibility):
        confidence = "high" if len(channels) >= 2 else "medium"
    elif classification in ("requirement_risk", "environment_blocked"):
        confidence = "medium" if req_status not in DEFINED_REQUIREMENT_STATUSES or not preconditions_ok else "low"
    elif classification == "pass":
        confidence = "high" if len(channels) >= needed and reproduction_ok(reproducibility) else "medium"
    else:
        confidence = "low"

    return {
        "classification": classification,
        "confidence": confidence,
        "fileable": classification == "implementation_defect" and confidence in ("high", "medium"),
        "reasons": reasons,
        "required_actions": actions,
        "requirement_status": req_status,
        "evidence_channels": channels,
        "reproducibility": normalize_reproducibility(reproducibility),
        "severity": str(severity or "P2").upper(),
    }


def validate_defect(record: dict[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """校验结构化缺陷是否允许进入 ONES。

    兼容两种证据表达：``evidence_ids`` 和 ``evidence_channels``。
    正式缺陷至少要有需求引用、证据和可复现方式；需求风险/环境阻塞不能走此接口。
    """
    errors: list[str] = []
    warnings: list[str] = []
    record = record or {}
    severity = str(record.get("severity_local") or record.get("severity") or "P2").upper()
    allow_single = bool(record.get("allow_single_channel"))
    needed = required_channels(severity, allow_single_channel=allow_single)

    for field in ("id", "title", "classification", "confidence", "requirement_refs",
                  "evidence_ids", "reproducibility", "environment", "expected", "actual", "steps"):
        if field not in record or record.get(field) in (None, "", [], {}):
            errors.append(f"缺少字段 {field}")

    if record.get("classification") != "implementation_defect":
        errors.append("只有 implementation_defect 才能进入正式缺陷流程")
    if str(record.get("confidence") or "").lower() not in ("high", "medium"):
        errors.append("缺陷置信度必须是 high 或 medium")
    if not record.get("requirement_refs"):
        errors.append("缺陷必须引用需求点/需求条款")
    if not record.get("evidence_ids"):
        errors.append("缺陷必须关联证据ID")

    channels = _channels(record.get("evidence_channels"))
    if len(channels) < needed:
        if not allow_single:
            errors.append(f"证据通道不足：{len(channels)}/{needed}")
        else:
            warnings.append("当前显式使用单通道模式，请确认是 API/SQL 确定性复现")

    repro = normalize_reproducibility(record.get("reproducibility"))
    if not reproduction_ok(repro) and not allow_single:
        errors.append("复现率未达到 2/2 或确定性 API 复现")

    if strict and record.get("status") in ("ready", "submitted", "verified"):
        if not record.get("ones_key"):
            warnings.append("结构化缺陷尚未记录 ONES 单号")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "required_channels": needed,
        "reproducibility": repro,
    }


def defect_fingerprint(record: dict[str, Any]) -> str:
    """生成稳定的缺陷指纹，用于去重和回归索引。"""
    raw = "|".join([
        str(record.get("feature") or "").strip().lower(),
        str(record.get("title") or "").strip().lower(),
        ",".join(sorted(str(x) for x in record.get("requirement_refs") or [])),
        str(record.get("root_cause") or "").strip().lower(),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
