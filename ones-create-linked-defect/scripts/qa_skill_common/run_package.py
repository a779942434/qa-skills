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

TERMINAL_DECISION_STATUSES = frozenset({"resolved", "approved", "confirmed", "waived", "rejected"})
WAIVED_DECISION_STATUSES = frozenset({"waived"})
VALID_ORACLE_MODES = frozenset({"ui", "api", "db", "mixed", "downstream"})


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


def _fingerprint(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _empty_oracle() -> dict[str, Any]:
    return {"mode": "", "expected": "", "precision": "", "evidence": []}


def _empty_requirement(ref: str) -> dict[str, Any]:
    return {
        "id": ref,
        "source": ref,
        "quote": "",
        "status": "undefined",
        "case_ids": [],
        "decision_ids": [],
        "oracle": _empty_oracle(),
        "data_dependencies": [],
        "updated_at": "",
    }


def normalize_requirement_record(record: dict[str, Any]) -> dict[str, Any]:
    """统一需求合同字段；兼容旧版只有 id/source/quote/status/case_ids 的合同。"""
    item = dict(record or {})
    rid = str(item.get("id") or item.get("requirement_ref") or "").strip()
    if not rid:
        raise ValueError("需求条款缺少 id")
    item["id"] = rid
    item["source"] = str(item.get("source") or rid)
    item["quote"] = str(item.get("quote") or "")
    item["status"] = str(item.get("status") or "undefined").lower()
    item["case_ids"] = _refs(item.get("case_ids"))
    item["decision_ids"] = _refs(item.get("decision_ids"))
    oracle = item.get("oracle")
    if isinstance(oracle, dict):
        merged = _empty_oracle()
        merged.update(oracle)
        merged["mode"] = str(merged.get("mode") or "").lower()
        merged["evidence"] = _refs(merged.get("evidence"))
        item["oracle"] = merged
    else:
        item["oracle"] = _empty_oracle()
        if item.get("oracle_mode"):
            item["oracle"]["mode"] = str(item.get("oracle_mode")).lower()
        if item.get("expected"):
            item["oracle"]["expected"] = str(item.get("expected"))
    deps = item.get("data_dependencies")
    item["data_dependencies"] = list(deps) if isinstance(deps, list) else _refs(deps)
    item["updated_at"] = str(item.get("updated_at") or "")
    return item


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
    snapshot = {
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
    snapshot["snapshot_id"] = _environment_id(snapshot)
    return snapshot


def _environment_id(environment: dict | None) -> str:
    env = environment or {}
    stable = {key: env.get(key, "") for key in (
        "base_url", "host", "tenant_alias", "role", "location_org",
        "config_fingerprint", "browser_profile_hash", "app_version",
    )}
    return _fingerprint(stable)


def init_run_package(
    run_dir: str | Path,
    feature: str,
    *,
    mode: str = "standard",
    requirements: Iterable[str] | None = None,
    force: bool = False,
    run_id: str = "",
    environment: dict | None = None,
    data_batch_id: str = "",
) -> dict[str, Any]:
    """初始化运行包；默认只补缺失文件，不覆盖已有状态。

    ``force=True`` 才会把标准包文件重置为初始值。这样 ``qa_case init``
    可以安全地重复执行，后续新增 runner/cases 也不会冲掉已有检查点。
    """
    paths = package_paths(run_dir)
    existing = [key for key in ("manifest", "contract", "coverage", "evidence", "defects")
                if paths[key].exists()]
    req_refs = [str(x).strip() for x in (requirements or []) if str(x).strip()]
    effective_run_id = run_id or f"{_slug(feature)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    env = dict(environment or environment_snapshot(""))
    env.setdefault("snapshot_id", _environment_id(env))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": effective_run_id,
        "feature": feature,
        "mode": mode,
        "requirement_refs": req_refs,
        "data_batch_id": str(data_batch_id or effective_run_id),
        "created_at": _now(),
        "started_at": "",
        "completed_at": "",
        "status": "initialized",
        "environment": env,
        "tooling": {
            "qa_case": True,
            "qa_action": False,
            "oracle": False,
            "phase_runner": False,
        },
    }
    contract = {
        "schema_version": SCHEMA_VERSION,
        "requirements": [_empty_requirement(ref) for ref in req_refs],
        "decisions": [],
        "updated_at": _now(),
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

    defaults = {
        "manifest": manifest,
        "contract": contract,
        "coverage": coverage,
        "evidence": evidence,
        "defects": defects,
    }
    for key, payload in defaults.items():
        if force or not paths[key].exists():
            _write_json(paths[key], payload)

    # 已存在包也允许追加新的需求引用；不重置 contract/coverage。
    if existing and not force:
        manifest_path = paths["manifest"]
        contract_path = paths["contract"]
        manifest_now = _read_json(manifest_path, {})
        contract_now = _read_json(contract_path, {"requirements": [], "decisions": []})
        manifest_refs = [str(x) for x in (manifest_now.get("requirement_refs") or [])]
        changed = False
        for ref in req_refs:
            if ref not in manifest_refs:
                manifest_refs.append(ref)
                changed = True
        if changed:
            manifest_now["requirement_refs"] = manifest_refs
            _write_json(manifest_path, manifest_now)
        reqs = list(contract_now.get("requirements") or [])
        known = {str(x.get("id") or "") for x in reqs}
        for ref in req_refs:
            if ref not in known:
                reqs.append(_empty_requirement(ref))
                changed = True
        if changed:
            contract_now["requirements"] = reqs
            _write_json(contract_path, contract_now)
    paths["evidence"].parent.mkdir(parents=True, exist_ok=True)
    return {
        "run_dir": str(paths["run_dir"]),
        "manifest": str(paths["manifest"]),
        "contract": str(paths["contract"]),
        "coverage": str(paths["coverage"]),
        "evidence": str(paths["evidence"]),
        "defects": str(paths["defects"]),
    }


def _refs(value: Any) -> list[str]:
    """把 requirement_refs / requirement 统一成去重字符串列表。"""
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


def normalize_case_record(record: dict[str, Any]) -> dict[str, Any]:
    """统一 exec / cases.json / coverage 的用例字段。"""
    item = dict(record or {})
    case_id = str(item.get("id") or item.get("case_id") or "").strip()
    if not case_id:
        raise ValueError("用例缺少 id")
    item["id"] = case_id
    item["priority"] = str(item.get("priority") or "P2").upper()
    refs = item.get("requirement_refs")
    if refs is None:
        refs = item.get("requirements")
    if refs is None:
        refs = item.get("requirement")
    if refs is None:
        refs = item.get("requirement_ref")
    if refs is None:
        refs = item.get("需求点")
    item["requirement_refs"] = _refs(refs)
    invs = item.get("invariant_ids")
    if invs is None:
        invs = item.get("invariants")
    item["invariant_ids"] = _refs(invs)
    item["oracle_mode"] = str(item.get("oracle_mode") or "ui").lower()
    item.setdefault("evidence_required", True)
    item.setdefault("status", "未执行")
    return item


def upsert_case(run_dir: str | Path, case: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    """把用例写入 coverage，并同步 contract 的 requirement -> case_ids 映射。

    ``force=False`` 用于 init/导入：只补缺失字段，不覆盖已执行状态。
    ``force=True`` 用于 exec 回写：更新状态、证据和备注，但需求引用仍做并集，
    避免一次 ad-hoc 执行把原有用例的覆盖关系冲掉。
    """
    paths = package_paths(run_dir)
    item = normalize_case_record(case)
    if not paths["coverage"].exists():
        init_run_package(run_dir, "ad-hoc", mode="quick",
                         requirements=item["requirement_refs"])
    coverage = _read_json(paths["coverage"], {
        "schema_version": SCHEMA_VERSION, "cases": [], "invariants": [], "exclusions": [],
    })
    cases = list(coverage.get("cases") or [])
    old = next((x for x in cases if str(x.get("id") or "") == item["id"]), None)
    if old is None:
        merged = item
        cases.append(merged)
    else:
        merged = dict(old)
        for key, value in item.items():
            if key == "requirement_refs":
                merged[key] = _refs(list(merged.get(key) or []) + list(value or []))
            elif key == "invariant_ids":
                merged[key] = _refs(list(merged.get(key) or []) + list(value or []))
            elif key == "evidence_ids":
                merged[key] = _refs(list(merged.get(key) or []) + list(value or []))
            elif force or key not in merged or merged.get(key) in (None, "", []):
                merged[key] = value
        for idx, current in enumerate(cases):
            if str(current.get("id") or "") == item["id"]:
                cases[idx] = merged
                break
    coverage["cases"] = cases
    _write_json(paths["coverage"], coverage)

    contract = _read_json(paths["contract"], {
        "schema_version": SCHEMA_VERSION, "requirements": [], "decisions": [],
    })
    requirements = list(contract.get("requirements") or [])
    by_id = {str(req.get("id") or ""): req for req in requirements}
    changed = False
    for ref in merged.get("requirement_refs") or []:
        req = by_id.get(ref)
        if req is None:
            req = normalize_requirement_record(_empty_requirement(ref))
            req["status"] = "defined"
            requirements.append(req)
            by_id[ref] = req
            changed = True
        else:
            req = normalize_requirement_record(req)
            by_id[ref] = req
            if str(req.get("status") or "").lower() in ("", "undefined"):
                req["status"] = "defined"
                changed = True
        ids = list(req.get("case_ids") or [])
        if item["id"] not in ids:
            ids.append(item["id"])
            changed = True
        req["case_ids"] = ids
        oracle = req.setdefault("oracle", _empty_oracle())
        mode = str(item.get("oracle_mode") or "").lower()
        if mode:
            current = str(oracle.get("mode") or "").lower()
            if not current:
                oracle["mode"] = mode
                changed = True
            elif current != mode and current != "mixed" and mode != "mixed":
                oracle["mode"] = "mixed"
                changed = True
        if changed:
            req["updated_at"] = _now()
    contract["requirements"] = list(by_id.values())
    if changed:
        contract["updated_at"] = _now()
    _write_json(paths["contract"], contract)
    return merged


def upsert_requirement(run_dir: str | Path, requirement: dict[str, Any], *,
                       force: bool = True) -> dict[str, Any]:
    """新增/更新一条需求合同；case_ids 始终取并集，避免覆盖已有映射。"""
    paths = package_paths(run_dir)
    if not paths["contract"].exists():
        init_run_package(run_dir, "ad-hoc", mode="quick")
    item = normalize_requirement_record(requirement)
    contract = _read_json(paths["contract"], {
        "schema_version": SCHEMA_VERSION, "requirements": [], "decisions": [],
    })
    requirements = list(contract.get("requirements") or [])
    old = next((x for x in requirements if str(x.get("id") or "") == item["id"]), None)
    if old is None:
        requirements.append(item)
        merged = item
    else:
        merged = normalize_requirement_record(old)
        for key, value in item.items():
            if key == "case_ids":
                merged[key] = _refs(list(merged.get(key) or []) + list(value or []))
            elif key == "decision_ids":
                merged[key] = _refs(list(merged.get(key) or []) + list(value or []))
            elif force or key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
        for idx, current in enumerate(requirements):
            if str(current.get("id") or "") == item["id"]:
                requirements[idx] = merged
                break
    merged["updated_at"] = _now()
    contract["requirements"] = requirements
    contract["updated_at"] = _now()
    _write_json(paths["contract"], contract)
    return merged


def merge_coverage_metadata(run_dir: str | Path, *, invariants: Iterable[dict] | None = None,
                            exclusions: Iterable[dict] | None = None) -> dict[str, Any]:
    """把生成技能 sidecar 中的不变量/排除项并入 coverage；按 id/需求点去重。"""
    paths = package_paths(run_dir)
    if not paths["coverage"].exists():
        init_run_package(run_dir, "ad-hoc", mode="quick")
    coverage = _read_json(paths["coverage"], {
        "schema_version": SCHEMA_VERSION, "cases": [], "invariants": [], "exclusions": [],
    })
    inv_by_id = {str(x.get("id") or ""): x for x in coverage.get("invariants") or []}
    for inv in invariants or []:
        if not isinstance(inv, dict):
            continue
        iid = str(inv.get("id") or "").strip()
        if not iid:
            continue
        current = inv_by_id.get(iid) or {}
        merged = dict(current)
        merged.update(inv)
        merged["case_ids"] = _refs(list(current.get("case_ids") or []) + list(inv.get("case_ids") or []))
        inv_by_id[iid] = merged
    ex_by_ref = {str(x.get("requirement_ref") or x.get("id") or ""): x
                 for x in coverage.get("exclusions") or []}
    for ex in exclusions or []:
        if not isinstance(ex, dict):
            continue
        ref = str(ex.get("requirement_ref") or ex.get("id") or "").strip()
        if not ref:
            continue
        current = ex_by_ref.get(ref) or {}
        merged = dict(current)
        merged.update(ex)
        ex_by_ref[ref] = merged
    coverage["invariants"] = list(inv_by_id.values())
    coverage["exclusions"] = list(ex_by_ref.values())
    _write_json(paths["coverage"], coverage)
    return coverage


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
            env = dict(value)
            env.setdefault("snapshot_id", _environment_id(env))
            manifest["environment"] = env
        else:
            manifest[key] = value
    if manifest.get("environment") and not manifest["environment"].get("snapshot_id"):
        manifest["environment"]["snapshot_id"] = _environment_id(manifest["environment"])
    if not manifest.get("data_batch_id") and manifest.get("run_id"):
        manifest["data_batch_id"] = manifest["run_id"]
    _write_json(paths["manifest"], manifest)
    return manifest


def append_decision(run_dir: str | Path, record: dict[str, Any]) -> dict:
    paths = package_paths(run_dir)
    if not paths["contract"].exists():
        init_run_package(run_dir, "ad-hoc", mode="quick")
    contract = _read_json(paths["contract"], {"schema_version": SCHEMA_VERSION, "requirements": [], "decisions": []})
    item = dict(record or {})
    refs = _refs(item.get("requirement_ids") or item.get("requirements") or
                 item.get("requirement_refs") or item.get("requirement_id"))
    if not refs:
        raise ValueError("决策必须关联至少一个需求点")
    status = str(item.get("status") or "open").lower()
    if status in TERMINAL_DECISION_STATUSES and not str(item.get("resolution") or "").strip():
        raise ValueError("已解决/已确认/已豁免/已驳回的决策必须填写 resolution")
    existing_ids = {str(x.get("id") or "") for x in contract.get("decisions") or []}
    seq = len(existing_ids) + 1
    while f"DEC-{seq:03d}" in existing_ids:
        seq += 1
    item["id"] = str(item.get("id") or f"DEC-{seq:03d}")
    item["requirement_ids"] = refs
    item["status"] = status
    item["resolution"] = str(item.get("resolution") or "")
    item["owner"] = str(item.get("owner") or "")
    item["source"] = str(item.get("source") or "")
    item["applies_to"] = str(item.get("applies_to") or "")
    item["valid_until"] = str(item.get("valid_until") or "")
    item.setdefault("created_at", _now())
    item["updated_at"] = _now()
    if status in TERMINAL_DECISION_STATUSES:
        item.setdefault("decided_at", _now())
    contract.setdefault("decisions", []).append(item)
    requirements = list(contract.get("requirements") or [])
    by_id = {str(req.get("id") or ""): req for req in requirements}
    for ref in refs:
        req = by_id.get(ref)
        if req is None:
            continue
        req = normalize_requirement_record(req)
        req["decision_ids"] = _refs(list(req.get("decision_ids") or []) + [item["id"]])
        if status in ("resolved", "approved", "confirmed"):
            req["status"] = "defined"
        elif status in WAIVED_DECISION_STATUSES:
            req["status"] = "waived"
        elif status == "rejected":
            req["status"] = "rejected"
        elif status in ("open", "pending"):
            if str(req.get("status") or "") in ("", "undefined", "ambiguous", "pending"):
                req["status"] = "pending"
        req["updated_at"] = _now()
        by_id[ref] = req
    contract["requirements"] = list(by_id.values())
    contract["updated_at"] = _now()
    _write_json(paths["contract"], contract)
    return item


def set_requirement_oracle(
    run_dir: str | Path,
    requirement_id: str,
    *,
    mode: str,
    expected: str,
    precision: str = "",
    evidence: Iterable[str] | None = None,
    source: str = "",
    quote: str = "",
    data_dependencies: Iterable[str] | None = None,
) -> dict:
    """设置需求的判定依据（oracle）；这是自动判缺陷的前置条件。"""
    rid = str(requirement_id or "").strip()
    if not rid:
        raise ValueError("requirement_id 不能为空")
    oracle_payload = {
        "mode": str(mode or "").lower(),
        "expected": str(expected or ""),
        "precision": str(precision or ""),
        "evidence": _refs(evidence),
    }
    if not oracle_payload["expected"]:
        raise ValueError("expected 不能为空")
    paths = package_paths(run_dir)
    if not paths["contract"].exists():
        init_run_package(run_dir, "ad-hoc", mode="quick", requirements=[rid])
    contract = _read_json(paths["contract"], {
        "schema_version": SCHEMA_VERSION, "requirements": [], "decisions": [],
    })
    requirements = list(contract.get("requirements") or [])
    target = next((x for x in requirements if str(x.get("id") or "") == rid), None)
    if target is None:
        target = normalize_requirement_record(_empty_requirement(rid))
        requirements.append(target)
    target = normalize_requirement_record(target)
    target["oracle"] = oracle_payload
    if source:
        target["source"] = str(source)
    if quote:
        target["quote"] = str(quote)
    if data_dependencies:
        target["data_dependencies"] = _refs(list(target.get("data_dependencies") or []) +
                                             list(data_dependencies))
    if str(target.get("status") or "") in ("", "undefined", "ambiguous"):
        target["status"] = "defined"
    target["updated_at"] = _now()
    for idx, current in enumerate(requirements):
        if str(current.get("id") or "") == rid:
            requirements[idx] = target
            break
    contract["requirements"] = requirements
    contract["updated_at"] = _now()
    _write_json(paths["contract"], contract)
    return target


def _decision_requirement_refs(decision: dict) -> list[str]:
    return _refs(decision.get("requirement_ids") or decision.get("requirements") or
                 decision.get("requirement_refs") or decision.get("requirement_id"))


def requirement_versions(contract: dict, requirement_ids: Iterable[str] | None = None) -> dict[str, str]:
    """计算需求条款 + 相关决策的稳定指纹，用于证据失效判断。"""
    contract = contract or {}
    include_all = requirement_ids is None
    wanted = set(_refs(requirement_ids))
    requirements = list(contract.get("requirements") or [])
    decisions = list(contract.get("decisions") or [])
    out: dict[str, str] = {}
    for req in requirements:
        rid = str(req.get("id") or "").strip()
        if not rid or (not include_all and rid not in wanted):
            continue
        normalized = normalize_requirement_record(req)
        relevant_decisions = [
            {k: d.get(k) for k in ("id", "status", "resolution", "owner", "source",
                                   "applies_to", "valid_until") if d.get(k) not in (None, "")}
            for d in decisions if rid in _decision_requirement_refs(d)
        ]
        relevant_decisions.sort(key=lambda d: str(d.get("id") or ""))
        out[rid] = _fingerprint({
            "requirement": {
                "id": rid,
                "source": normalized.get("source", ""),
                "quote": normalized.get("quote", ""),
                "status": normalized.get("status", ""),
                "oracle": normalized.get("oracle", {}),
                "data_dependencies": normalized.get("data_dependencies", []),
            },
            "decisions": relevant_decisions,
        })
    return out


def _case_requirement_refs(contract: dict, case_id: str) -> list[str]:
    refs: list[str] = []
    for req in (contract or {}).get("requirements") or []:
        if case_id in _refs(req.get("case_ids")):
            refs.append(str(req.get("id") or ""))
    return [x for x in refs if x]


def _parse_expiry(value: str) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if len(text) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def evidence_validity(item: dict, contract: dict | None = None,
                      manifest: dict | None = None) -> dict[str, Any]:
    """判断一条证据是否仍绑定当前需求版本、环境快照和数据批次。"""
    contract = contract or {}
    manifest = manifest or {}
    reasons: list[str] = []
    if item.get("invalidated") or str(item.get("status") or "").lower() in ("stale", "invalid"):
        reasons.append("证据已被显式标记失效")
    expiry = _parse_expiry(item.get("valid_until") or "")
    if expiry and datetime.now().astimezone() > expiry:
        reasons.append("证据已超过有效期")
    if reasons:
        return {"status": "stale", "reasons": reasons}

    binding = item.get("binding") or {}
    if not isinstance(binding, dict) or not binding:
        return {"status": "unbound", "reasons": ["证据没有版本/环境绑定"]}

    case_id = str(item.get("case_id") or "")
    bound_versions = binding.get("requirement_versions") or {}
    current_versions = requirement_versions(contract, list(bound_versions) or _case_requirement_refs(contract, case_id))
    if bound_versions or current_versions:
        if not bound_versions:
            return {"status": "unbound", "reasons": ["证据未绑定需求版本"]}
        for rid, version in bound_versions.items():
            current = current_versions.get(str(rid))
            if not current:
                reasons.append(f"需求条款已不存在: {rid}")
            elif current != version:
                reasons.append(f"需求版本已变化: {rid}")
    if reasons:
        return {"status": "stale", "reasons": reasons}

    env = manifest.get("environment") or {}
    current_env = env.get("snapshot_id") or _environment_id(env)
    bound_env = str(binding.get("environment_snapshot_id") or "")
    if not bound_env:
        return {"status": "unbound", "reasons": ["证据未绑定环境快照"]}
    if current_env and bound_env != current_env:
        reasons.append("环境快照已变化")

    current_batch = str(manifest.get("data_batch_id") or manifest.get("run_id") or "")
    bound_batch = str(binding.get("data_batch_id") or "")
    if bound_batch and current_batch and bound_batch != current_batch:
        reasons.append("数据批次已变化")

    current_page = str(manifest.get("page_fingerprint") or "")
    bound_page = str(binding.get("page_fingerprint") or "")
    if bound_page and current_page and bound_page != current_page:
        reasons.append("页面指纹已变化")

    if reasons:
        return {"status": "stale", "reasons": reasons}
    return {"status": "valid", "reasons": []}


def add_evidence(
    run_dir: str | Path,
    path: str | Path,
    *,
    case_id: str = "",
    defect_id: str = "",
    source: str = "ui",
    reproduction: dict | None = None,
    binding: dict | None = None,
    valid_until: str = "",
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
    contract = _read_json(package_paths(run_dir)["contract"], {"requirements": [], "decisions": []})
    manifest = _read_json(package_paths(run_dir)["manifest"], {})
    refs = _case_requirement_refs(contract, case_id)
    if not refs and defect_id:
        try:
            refs = _refs(find_defect(run_dir, defect_id).get("requirement_refs"))
        except Exception:
            refs = []
    auto_binding = {
        "requirement_versions": requirement_versions(contract, refs),
        "environment_snapshot_id": (manifest.get("environment") or {}).get("snapshot_id") or
                                   _environment_id(manifest.get("environment") or {}),
        "data_batch_id": str(manifest.get("data_batch_id") or manifest.get("run_id") or ""),
        "page_fingerprint": "",
    }
    auto_binding.update({k: v for k, v in (binding or {}).items() if v not in (None, "")})
    item = {
        "id": "EV-" + hashlib.sha256((rel + _now()).encode("utf-8")).hexdigest()[:12],
        "path": rel,
        "type": str(source or "ui").lower(),
        "case_id": case_id,
        "defect_id": defect_id,
        "captured_at": _now(),
        "sha256": _sha256(evidence_path),
        "reproduction": reproduction or {},
        "binding": auto_binding,
        "valid_until": str(valid_until or ""),
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
    stale_evidence = 0
    unbound_evidence = 0
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
        validity = evidence_validity(item, contract, manifest)
        if validity["status"] == "stale":
            stale_evidence += 1
            message = f"证据失效 {eid or raw_path}: {'; '.join(validity['reasons'])}"
            (errors if strict else warnings).append(message)
        elif validity["status"] == "unbound":
            unbound_evidence += 1
            warnings.append(f"证据未绑定版本 {eid or raw_path}: {'; '.join(validity['reasons'])}")

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
        "stale_evidence": stale_evidence,
        "unbound_evidence": unbound_evidence,
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
