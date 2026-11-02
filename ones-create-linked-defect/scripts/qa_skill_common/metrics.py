# -*- coding: utf-8 -*-
"""运行包指标聚合：采纳率、覆盖率、质量门槛和效率摘要。

输出是稳定的 JSON 结构，供 CLI、周报和后续本地看板复用；不依赖外部服务。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import coverage as coverage_mod
from . import oracle
from . import run_package


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.combine(date.fromisoformat(value), datetime.min.time())
    except Exception:
        return None


def _run_dirs(root: Path, since: datetime | None = None) -> list[Path]:
    found: set[Path] = set()
    for pattern in ("manifest.json", "run_state.json", "data_ledger.json"):
        for path in root.rglob(pattern):
            if path.is_file():
                found.add(path.parent)
    out = []
    for run_dir in sorted(found):
        # 过滤前端构建产物等“同名 manifest.json”目录；真实运行至少应有
        # run_state/data_ledger，或标准运行包的 contract.json。
        if not ((run_dir / run_package.RUN_STATE).exists()
                or (run_dir / run_package.DATA_LEDGER).exists()
                or (run_dir / run_package.CONTRACT).exists()):
            continue
        stamp = None
        manifest = _read_json(run_dir / run_package.MANIFEST, {})
        raw = manifest.get("created_at")
        if raw:
            try:
                stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                stamp = None
        if stamp is None:
            try:
                stamp = datetime.fromtimestamp(run_dir.stat().st_mtime)
            except Exception:
                stamp = None
        if since and stamp and stamp < since:
            continue
        out.append(run_dir)
    return out


def _judgement_count(run_dir: Path) -> int:
    path = run_dir / run_package.JUDGEMENTS
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except Exception:
        return 0


def _normalize_repro(value: Any) -> dict:
    return oracle.normalize_reproducibility(value)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _wall_time_ms(manifest: dict, state: dict) -> int:
    start = _parse_time(manifest.get("started_at") or state.get("started_at"))
    end = _parse_time(manifest.get("completed_at") or state.get("updated_at"))
    if start and end and end >= start:
        return int((end - start).total_seconds() * 1000)
    return 0


def collect_metrics(root: str | Path = "runs", *, since: str | None = None) -> dict[str, Any]:
    root = Path(root).expanduser()
    since_dt = _parse_since(since)
    runs = []
    for run_dir in _run_dirs(root, since_dt):
        pkg = run_package.load_package(run_dir)
        manifest = pkg["manifest"] or {}
        state = pkg["run_state"] or {}
        contract = pkg["contract"] or {}
        coverage = pkg["coverage"] or {}
        cov = coverage_mod.audit_coverage(contract, coverage, state, strict=False)
        cases = cov["cases"]
        statuses = [str(c.get("status") or "") for c in cases.values()]
        defects = list((pkg["defects"] or {}).get("defects") or [])
        evidence_items = list((pkg["evidence"] or {}).get("items") or [])
        judgement_count = _judgement_count(run_dir)
        ui_cases = [c for c in cases.values()
                    if str(c.get("oracle_mode") or "ui").lower() == "ui"
                    and str(c.get("status") or "") in coverage_mod.EXECUTED_STATUSES]
        qa_case_used = bool(manifest.get("tooling", {}).get("qa_case"))
        qa_action_used = judgement_count > 0
        evidence_cases = {str(item.get("case_id")) for item in evidence_items if item.get("case_id")}
        eligible_defects = 0
        invalid_defects = 0
        reproducible = 0
        for d in defects:
            gate = oracle.validate_defect(d, strict=False)
            if gate["ok"]:
                eligible_defects += 1
            if d.get("classification") != "implementation_defect":
                invalid_defects += 1
            if oracle.reproduction_ok(d.get("reproducibility")):
                reproducible += 1
        duration_ms = 0
        for rec in (state.get("cases") or {}).values():
            try:
                duration_ms += int(rec.get("duration_ms") or 0)
            except Exception:
                pass
        runs.append({
            "run_dir": str(run_dir),
            "run_id": manifest.get("run_id") or state.get("run_id", ""),
            "feature": manifest.get("feature") or state.get("feature", ""),
            "mode": manifest.get("mode") or "legacy",
            "legacy": pkg["legacy"],
            "cases": len(cases),
            "passed": statuses.count("通过") + statuses.count("pass"),
            "failed": statuses.count("失败") + statuses.count("fail"),
            "blocked": statuses.count("阻塞") + statuses.count("blocked"),
            "uncovered": statuses.count("未覆盖") + statuses.count("uncovered"),
            "requirement_coverage": cov["summary"]["requirement_coverage"],
            "invariant_coverage": cov["summary"]["invariant_coverage"],
            "qa_case_used": bool(qa_case_used),
            "qa_action_used": bool(qa_action_used),
            "ui_cases": len(ui_cases),
            "judgements": judgement_count,
            "evidence_items": len(evidence_items),
            "evidence_case_coverage": round(len(evidence_cases) / len(cases), 4) if cases else 0.0,
            "defects": len(defects),
            "eligible_defects": eligible_defects,
            "invalid_defects": invalid_defects,
            "reproducible_defects": reproducible,
            "duration_ms": duration_ms,
            "wall_time_ms": _wall_time_ms(manifest, state),
        })
    total_cases = sum(r["cases"] for r in runs)
    total_defects = sum(r["defects"] for r in runs)
    total_invalid = sum(r["invalid_defects"] for r in runs)
    total_eligible = sum(r["eligible_defects"] for r in runs)
    total_repro = sum(r["reproducible_defects"] for r in runs)
    new_runs = [r for r in runs if not r["legacy"]]
    summary = {
        "runs": len(runs),
        "new_schema_runs": len(new_runs),
        "legacy_runs": sum(1 for r in runs if r["legacy"]),
        "cases": total_cases,
        "defects": total_defects,
        "qa_case_adoption": round(sum(1 for r in new_runs if r["qa_case_used"]) / len(new_runs), 4) if new_runs else 0.0,
        "qa_action_adoption": round(sum(1 for r in new_runs if r["qa_action_used"]) / len(new_runs), 4) if new_runs else 0.0,
        "requirement_coverage_avg": round(sum(r["requirement_coverage"] for r in new_runs) / len(new_runs), 4) if new_runs else 0.0,
        "invariant_coverage_avg": round(sum(r["invariant_coverage"] for r in new_runs) / len(new_runs), 4) if new_runs else 0.0,
        "invalid_defect_rate": round(total_invalid / total_defects, 4) if total_defects else 0.0,
        "defect_gate_pass_rate": round(total_eligible / total_defects, 4) if total_defects else 0.0,
        "defect_reproducibility_rate": round(total_repro / total_defects, 4) if total_defects else 0.0,
        "duration_ms": sum(r["duration_ms"] for r in runs),
        "total_wall_time_ms": sum(r["wall_time_ms"] for r in runs),
        "avg_wall_time_ms": round(sum(r["wall_time_ms"] for r in new_runs) / len(new_runs), 0) if new_runs else 0,
    }
    return {"schema_version": 1, "root": str(root), "since": since or "", "summary": summary, "runs": runs}


def render_text(result: dict[str, Any]) -> str:
    s = result.get("summary") or {}
    lines = [
        "# 测试助手指标摘要",
        "",
        f"- 运行数：{s.get('runs', 0)}（legacy {s.get('legacy_runs', 0)}）",
        f"- 用例数：{s.get('cases', 0)}",
        f"- qa_case 采纳率：{s.get('qa_case_adoption', 0):.1%}",
        f"- qa_action 采纳率：{s.get('qa_action_adoption', 0):.1%}",
        f"- 需求覆盖率均值：{s.get('requirement_coverage_avg', 0):.1%}",
        f"- 不变量覆盖率均值：{s.get('invariant_coverage_avg', 0):.1%}",
        f"- 无效缺陷率：{s.get('invalid_defect_rate', 0):.1%}",
        f"- 缺陷门槛通过率：{s.get('defect_gate_pass_rate', 0):.1%}",
        f"- 缺陷可复现率：{s.get('defect_reproducibility_rate', 0):.1%}",
    ]
    return "\n".join(lines)
