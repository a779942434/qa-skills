# -*- coding: utf-8 -*-
"""标准测试运行包：初始化、读写、证据索引、缺陷主账与审计。

运行包只使用本地 JSON/JSONL，不新增外部服务。历史运行目录没有这些文件时，
读取函数返回 legacy 视图，审计只给警告，不破坏旧目录。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import coverage as coverage_mod
from . import oracle

SCHEMA_VERSION = 1
MANIFEST = "manifest.json"
CONTRACT = "contract.json"
COVERAGE = "coverage.json"
EVIDENCE_INDEX = "evidence/index.json"
DEFECTS = "defects.json"
RUN_STATE = "run_state.json"
DATA_LEDGER = "data_ledger.json"
JUDGEMENTS = "judgements.jsonl"
CONCLUSIONS = "conclusions.json"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path, default: Any, errors: list[str] | None = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        if errors is not None:
            errors.append(f"JSON解析失败 {path.name}: {type(exc).__name__}")
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _slug(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", str(text or "run")).strip("-")
    return clean or "run"


def package_paths(run_dir: str | Path) -> dict[str, Path]:
    run_dir = Path(run_dir).expanduser()
    return {
        "run_dir": run_dir,
        "manifest": run_dir / MANIFEST,
        "contract": run_dir / CONTRACT,
        "coverage": run_dir / COVERAGE,
        "evidence": run_dir / EVIDENCE_INDEX,
        "defects": run_dir / DEFECTS,
        "run_state": run_dir / RUN_STATE,
        "data_ledger": run_dir / DATA_LEDGER,
        "judgements": run_dir / JUDGEMENTS,
        "conclusions": run_dir / CONCLUSIONS,
    }


def environment_snapshot(
    base_url: str = "",
    *,
    tenant_alias: str = "",
    role: str = "",
    location_org: str = "",
    config_fingerprint: str = "",
    browser_profile: str = "",
    app_version: str = "",
) -> dict[str, Any]:
    """生成不含凭据的环境快照；profile 只保存哈希。"""
    host = ""
    if base_url:
        try:
            from urllib.parse import urlparse
            host = urlparse(base_url).hostname or ""
        except Exception:
            host = ""
    profile_hash = hashlib.sha256(str(browser_profile).encode("utf-8")).hexdigest()[:16] if browser_profile else ""
    return {
        "base_url": base_url,
        "host": host,
        "tenant_alias": tenant_alias,
        "role": role,
        "location_org": location_org,
        "config_fingerprint": config_fingerprint,
        "browser_profile_hash": profile_hash,
        "app_version": app_version,
        "captured_at": _now(),
    }


def init_run_package(
    run_dir: str | Path,
    feature: str,
    *,
    mode: str = "standard",
    requirements: Iterable[str] | None = None,
    force: bool = False,
    run_id: str = "",
    environment: dict | None = None,
) -> dict[str, Any]:
    """初始化运行包；默认拒绝覆盖已有文件。"""
    paths = package_paths(run_dir)
    existing = [key for key in ("manifest", "contract", "coverage", "evidence", "defects")
                if paths[key].exists()]
    if existing and not force:
        raise FileExistsError("运行包已存在: " + ", ".join(existing))
    req_refs = [str(x).strip() for x in (requirements or []) if str(x).strip()]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id or f"{_slug(feature)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "feature": feature,
        "mode": mode,
        "requirement_refs": req_refs,
        "created_at": _now(),
        "started_at": "",
        "completed_at": "",
        "status": "initialized",
        "environment": environment or environment_snapshot(""),
        "tooling": {
            "qa_case": True,
            "qa_action": False,
            "oracle": False,
            "phase_runner": False,
        },
    }
    contract = {
        "schema_version": SCHEMA_VERSION,
        "requirements": [
            {
                "id": ref,
                "source": ref,
                "quote": "",
                "status": "undefined",
                "case_ids": [],
            }
            for ref in req_refs
        ],
        "decisions": [],
    }
    coverage = {
        "schema_version": SCHEMA_VERSION,
        "cases": [],
        "invariants": [],
        "exclusions": [],
        "summary": {},
    }
    evidence = {"schema_version": SCHEMA_VERSION, "items": []}
    defects = {"schema_version": SCHEMA_VERSION, "defects": []}

    _write_json(paths["manifest"], manifest)
    _write_json(paths["contract"], contract)
    _write_json(paths["coverage"], coverage)
    _write_json(paths["evidence"], evidence)
    _write_json(paths["defects"], defects)
    paths["evidence"].parent.mkdir(parents=True, exist_ok=True)
    return {
        "run_dir": str(paths["run_dir"]),
        "manifest": str(paths["manifest"]),
        "contract": str(paths["contract"]),
        "coverage": str(paths["coverage"]),
        "evidence": str(paths["evidence"]),
        "defects": str(paths["defects"]),
    }


def load_package(run_dir: str | Path) -> dict[str, Any]:
    paths = package_paths(run_dir)
    parse_errors: list[str] = []
    manifest = _read_json(paths["manifest"], {}, parse_errors)
    contract = _read_json(paths["contract"], {"schema_version": SCHEMA_VERSION, "requirements": [], "decisions": []}, parse_errors)
    coverage = _read_json(paths["coverage"], {"schema_version": SCHEMA_VERSION, "cases": [], "invariants": [], "exclusions": []}, parse_errors)
    evidence = _read_json(paths["evidence"], {"schema_version": SCHEMA_VERSION, "items": []}, parse_errors)
    defects = _read_json(paths["defects"], {"schema_version": SCHEMA_VERSION, "defects": []}, parse_errors)
    run_state = _read_json(paths["run_state"], {}, parse_errors)
    package_complete = all(
        paths[key].exists() for key in ("manifest", "contract", "coverage", "evidence", "defects")
    )
    return {
        "run_dir": str(paths["run_dir"]),
        "manifest": manifest,
        "contract": contract,
        "coverage": coverage,
        "evidence": evidence,
        "defects": defects,
        "run_state": run_state,
        "paths": {k: str(v) for k, v in paths.items()},
        "legacy": not package_complete,
        "parse_errors": parse_errors,
    }


def update_manifest(run_dir: str | Path, **updates) -> dict:
    paths = package_paths(run_dir)
    manifest = _read_json(paths["manifest"], {})
    for key, value in updates.items():
        if key == "tooling" and isinstance(value, dict):
            manifest.setdefault("tooling", {}).update(value)
        elif key == "environment" and isinstance(value, dict):
            manifest["environment"] = value
        else:
            manifest[key] = value
    _write_json(paths["manifest"], manifest)
    return manifest


def append_decision(run_dir: str | Path, record: dict[str, Any]) -> dict:
    paths = package_paths(run_dir)
    contract = _read_json(paths["contract"], {"schema_version": SCHEMA_VERSION, "requirements": [], "decisions": []})
    item = dict(record or {})
    item.setdefault("id", f"DEC-{len(contract.get('decisions') or []) + 1:03d}")
    item.setdefault("status", "open")
    item.setdefault("created_at", _now())
    contract.setdefault("decisions", []).append(item)
    _write_json(paths["contract"], contract)
    return item


def add_evidence(
    run_dir: str | Path,
    path: str | Path,
    *,
    case_id: str = "",
    defect_id: str = "",
    source: str = "ui",
    reproduction: dict | None = None,
) -> dict:
    """把证据加入 index；路径优先保存为 run-dir 相对路径。"""
    run_dir = Path(run_dir).expanduser()
    evidence_path = Path(path).expanduser()
    if not evidence_path.is_absolute():
        candidate = run_dir / evidence_path
        if candidate.exists():
            evidence_path = candidate
        elif not evidence_path.exists():
            evidence_path = candidate
    if not evidence_path.exists():
        raise FileNotFoundError(str(evidence_path))
    try:
        rel = str(evidence_path.resolve().relative_to(run_dir.resolve()))
    except Exception:
        rel = str(evidence_path.resolve())
    items_path = package_paths(run_dir)["evidence"]
    index = _read_json(items_path, {"schema_version": SCHEMA_VERSION, "items": []})
    item = {
        "id": "EV-" + hashlib.sha256((rel + _now()).encode("utf-8")).hexdigest()[:12],
        "path": rel,
        "type": str(source or "ui").lower(),
        "case_id": case_id,
        "defect_id": defect_id,
        "captured_at": _now(),
        "sha256": _sha256(evidence_path),
        "reproduction": reproduction or {},
    }
    items = index.setdefault("items", [])
    # 同一路径同一 case 的重复记录不重复追加
    for old in items:
        if old.get("path") == rel and old.get("case_id") == case_id:
            old.update({k: v for k, v in item.items() if k != "id"})
            _write_json(items_path, index)
            return old
    items.append(item)
    _write_json(items_path, index)
    return item


def update_defect(run_dir: str | Path, defect_id: str, updates: dict[str, Any]) -> dict:
    paths = package_paths(run_dir)
    data = _read_json(paths["defects"], {"schema_version": SCHEMA_VERSION, "defects": []})
    target = str(defect_id or "").strip().lower()
    for rec in data.get("defects") or []:
        if str(rec.get("id") or "").strip().lower() == target:
            rec.update(updates or {})
            rec.setdefault("updated_at", _now())
            _write_json(paths["defects"], data)
            return rec
    raise KeyError(f"未找到缺陷 {defect_id}")


def find_defect(run_dir: str | Path, defect_id: str) -> dict:
    data = _read_json(package_paths(run_dir)["defects"], {"defects": []})
    target = str(defect_id or "").strip().lower()
    for rec in data.get("defects") or []:
        if str(rec.get("id") or "").strip().lower() == target:
            return rec
    raise KeyError(f"未找到缺陷 {defect_id}")


def _resolve_path(run_dir: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else run_dir / p


def audit_run_package(run_dir: str | Path, *, strict: bool = False) -> dict[str, Any]:
    """综合审计运行包；历史目录只给 legacy 警告。"""
    run_dir = Path(run_dir).expanduser()
    pkg = load_package(run_dir)
    errors: list[str] = list(pkg.get("parse_errors") or [])
    warnings: list[str] = []
    if pkg["legacy"]:
        warnings.append("legacy 运行目录：缺少标准运行包文件，按只读兼容处理")
    manifest = pkg["manifest"] or {}
    contract = pkg["contract"] or {}
    coverage = pkg["coverage"] or {}
    run_state = pkg["run_state"] or {}
    mode = str(manifest.get("mode") or "quick").lower()
    if manifest and mode in ("standard", "deep"):
        if not manifest.get("environment"):
            (errors if strict else warnings).append("standard/deep 运行缺少环境快照")
        if not manifest.get("requirement_refs"):
            (errors if strict else warnings).append("standard/deep 运行缺少 requirement_refs")

    cov = coverage_mod.audit_coverage(contract, coverage, run_state, strict=strict)
    errors.extend(cov["errors"])
    warnings.extend(cov["warnings"])

    evidence_items = list((pkg["evidence"] or {}).get("items") or [])
    evidence_by_case: dict[str, list[dict]] = {}
    evidence_by_id: dict[str, dict] = {}
    for item in evidence_items:
        eid = str(item.get("id") or "")
        if eid:
            evidence_by_id[eid] = item
        cid = str(item.get("case_id") or "")
        if cid:
            evidence_by_case.setdefault(cid, []).append(item)
        raw_path = item.get("path") or ""
        if raw_path and not _resolve_path(run_dir, raw_path).exists():
            errors.append(f"证据文件不存在: {raw_path}")
        if item.get("sha256") and raw_path:
            actual = _resolve_path(run_dir, raw_path)
            if actual.exists():
                if _sha256(actual) != item.get("sha256"):
                    errors.append(f"证据哈希不匹配: {raw_path}")

    for case in cov["cases"].values():
        cid = str(case.get("id") or "")
        priority = str(case.get("priority") or "P2").upper()
        required = str(case.get("evidence_required", True)).lower() not in ("false", "0", "no")
        if required and priority in ("P0", "P1") and not evidence_by_case.get(cid):
            (errors if strict else warnings).append(f"{cid}: P0/P1 用例缺少证据")
        elif required and not evidence_by_case.get(cid):
            warnings.append(f"{cid}: 未记录证据")

    defects = list((pkg["defects"] or {}).get("defects") or [])
    for defect in defects:
        status = str(defect.get("status") or "draft").lower()
        if status not in ("ready", "submitted", "verified", "closed"):
            if strict:
                warnings.append(f"{defect.get('id', '')}: 草稿缺陷未参与正式门槛")
            continue
        gate = oracle.validate_defect(defect, strict=strict)
        errors.extend(f"{defect.get('id', '')}: {e}" for e in gate["errors"])
        warnings.extend(f"{defect.get('id', '')}: {w}" for w in gate["warnings"])
        for eid in defect.get("evidence_ids") or []:
            if eid not in evidence_by_id:
                errors.append(f"{defect.get('id', '')}: 证据ID不存在 {eid}")

    ledger_path = package_paths(run_dir)["data_ledger"]
    ledger = _read_json(ledger_path, {})
    records = ledger.get("records") or {}
    if records:
        cleanup = ledger.get("cleanup") or {}
        if not cleanup.get("status"):
            (errors if strict else warnings).append("data_ledger 有测试数据但缺少 cleanup.status")
        elif cleanup.get("status") not in ("clean", "restored", "retained", "not_required"):
            (errors if strict else warnings).append(f"测试数据清理状态异常: {cleanup.get('status')}")

    jg_total = 0
    jg_path = package_paths(run_dir)["judgements"]
    if jg_path.exists():
        with jg_path.open("r", encoding="utf-8") as f:
            jg_total = sum(1 for line in f if line.strip())
    ui_cases = [c for c in cov["cases"].values()
                if str(c.get("oracle_mode") or "ui").lower() == "ui"
                and str(c.get("status") or "") in coverage_mod.EXECUTED_STATUSES]
    if strict and ui_cases and jg_total == 0:
        errors.append("存在 UI 判定用例但没有 judgements.jsonl 记录")

    summary = {
        "mode": mode,
        "legacy": pkg["legacy"],
        "requirements": cov["summary"]["requirements"],
        "requirement_coverage": cov["summary"]["requirement_coverage"],
        "cases": cov["summary"]["cases"],
        "p0_p1_cases": cov["summary"]["p0_p1_cases"],
        "invariants": cov["summary"]["invariants"],
        "invariant_coverage": cov["summary"]["invariant_coverage"],
        "evidence_items": len(evidence_items),
        "defects": len(defects),
        "judgements": jg_total,
        "cleanup_status": (ledger.get("cleanup") or {}).get("status", ""),
    }
    return {
        "ok": not errors,
        "structure_ok": not bool(pkg.get("parse_errors")),
        "strict": bool(strict),
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "coverage": cov,
    }
