# -*- coding: utf-8 -*-
"""站点/页面注册表：跨会话复用「直达 URL + 关键等待 + 选择器 + 已踩坑」。

存于 <workspace_root>/sites/<host>.json（本机产物，不入 git）。

为什么要它：实测同一功能会在 4 个会话里被反复测试，每次重新侦察。
本模块把「首次侦察」的结论固化下来，让第 2 次起直接直达。

**两级可信度**（避免把失败路径固化下来）：
  - ``verified=True``：该 URL 被验证可达并落地到目标页 → 允许直接 goto
  - ``verified=False``：仅观测到（例如一次 400/超时后的中间页）→ 只作线索，
    命中后仍走 ``goto_feature`` 搜索并按结果回写

**一致性校验**（防止改版后旧 URL 仍返回 200 却是错页面）：
  命中 ``verified=True`` 并 goto 后，必须校验「归一化标题一致」或
  「组件库判定一致且为已知库」；不一致则标 ``stale``、降级为
  ``verified=False``，回退走 goto_feature 重侦察。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

# 这些判定不算「可靠组件库判定」，不能单独用于一致性校验
UNRELIABLE_VERDICTS = frozenset({"", "unknown", "custom", "mixed"})


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def host_of(url: str) -> str:
    """从 URL 提取站点标识（scheme://netloc）；非法则返回空串。"""
    s = str(url or "").strip()
    m = re.match(r"^(https?://[^/]+)", s, re.IGNORECASE)
    return m.group(1).rstrip("/").lower() if m else ""


def cache_key(base: str, feature: str) -> str:
    """功能直达缓存（``.cache/features.json``）key 构造的**唯一入口**。

    口径 ``<站点根>|<功能名>``：站点根优先取 ``host_of()`` 的结果（已小写 +
    去尾斜杠）；``host_of`` 认不出（如裸 host）时退化为原始串的
    ``strip().rstrip("/").lower()``。

    注册表同步与 ``goto_feature`` 必须共用本函数——两处各写一遍就会漂移出
    「写入用小写、读取用原样」这类不命中（G6）。
    """
    host = host_of(base) or str(base or "").strip().rstrip("/").lower()
    return "{}|{}".format(host, feature)


def _safe_host(host: str) -> str:
    s = re.sub(r"[^\w\-.]+", "_", str(host or ""), flags=re.UNICODE).strip("_")
    return s[:120] or "unknown-host"


def sites_dir() -> Path:
    from . import paths
    return paths.workspace_root() / "sites"


def registry_path(host: str) -> Path:
    return sites_dir() / (_safe_host(host) + ".json")


def load(host: str) -> dict:
    """读取注册表；不存在或损坏时返回空骨架（**不抛错**）。"""
    base = {"schema_version": SCHEMA_VERSION, "host": host, "updated_at": "", "pages": {}}
    p = registry_path(host)
    if not p.exists():
        return base
    try:
        data = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return base
    if not isinstance(data, dict):
        return base
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("host", host)
    data.setdefault("pages", {})
    if not isinstance(data["pages"], dict):
        data["pages"] = {}
    return data


def save(host: str, data: dict) -> Path:
    """原子写入注册表；返回路径。"""
    p = registry_path(host)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["schema_version"] = SCHEMA_VERSION
    data["host"] = host
    data["updated_at"] = _now()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def get_page(host: str, feature: str):
    """取某功能的注册条目；不存在返回 None。"""
    if not host or not feature:
        return None
    return (load(host).get("pages") or {}).get(feature)


def _feature_cache_sync(host: str, feature: str, url: str) -> None:
    """同步写 .cache/features.json，保持 goto_feature 的直达缓存一致。"""
    if not (host and feature and url):
        return
    try:
        from . import paths
        p = paths.workspace_root() / ".cache" / "features.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        data[cache_key(host, feature)] = url
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def upsert_page(host: str, feature: str, *, url: str, verified: bool,
                title=None, probe_verdict=None, fingerprint=None,
                waits=None, selectors=None, gotchas=None) -> Path:
    """新增或更新一个页面条目。

    - ``verified=True`` 仅在「URL 被验证可达且落到目标页」时传入。
    - 未显式给出的字段保持原值（不覆盖已有情报）。
    - **``hits`` 不在这里累加**（唯一写入者是 ``record_hit``）；``verified_at`` 只在
      verified=True 时刷新。
    """
    data = load(host)
    pages = data.setdefault("pages", {})
    entry = pages.get(feature) or {"hits": 0, "first_seen": _now()}
    entry["url"] = url or entry.get("url", "")
    entry["verified"] = bool(verified)
    if title:
        entry["title"] = title
    if probe_verdict:
        entry["probe_verdict"] = probe_verdict
    if fingerprint:
        entry["fingerprint"] = fingerprint
    if waits:
        entry["waits"] = waits
    if selectors:
        entry["selectors"] = {**(entry.get("selectors") or {}), **selectors}
    if gotchas:
        merged = list(entry.get("gotchas") or [])
        for g in gotchas:
            if g not in merged:
                merged.append(g)
        entry["gotchas"] = merged
    # hits 是「验证成功的复用命中次数」，唯一写入者是 record_hit()——
    # 本函数只登记/刷新元数据，绝不累加，否则一次 exec 会被计两次（G1）。
    entry.setdefault("hits", 0)
    entry["last_seen"] = _now()
    if verified:
        entry["verified_at"] = _now()
    entry.pop("stale", None)
    pages[feature] = entry
    path = save(host, data)
    if entry["url"]:
        _feature_cache_sync(host, feature, entry["url"])
    return path


def record_hit(host: str, feature: str) -> None:
    """只累加命中次数（失败不抛错）。"""
    try:
        data = load(host)
        entry = (data.get("pages") or {}).get(feature)
        if not entry:
            return
        entry["hits"] = int(entry.get("hits") or 0) + 1
        entry["last_seen"] = _now()
        save(host, data)
    except Exception:
        pass


def mark_stale(host: str, feature: str, reason: str = "") -> None:
    """标记条目失效并降级可信度（一致性校验不通过时调用）。"""
    try:
        data = load(host)
        entry = (data.get("pages") or {}).get(feature)
        if not entry:
            return
        entry["verified"] = False
        entry["stale"] = True
        entry["stale_at"] = _now()
        if reason:
            entry["stale_reason"] = reason
        save(host, data)
    except Exception:
        pass


def _title_norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def check_consistency(entry: dict, *, title=None, probe_verdict=None) -> str:
    """一致性校验：返回 'ok' | 'stale' | 'unknown'。

    ok      —— 归一化标题一致，或组件库判定一致且为已知库
    stale   —— 拿到了可比对的信息但都不一致
    unknown —— 无可比对信息（不应据此信任，但也不判失效）
    """
    if not entry:
        return "unknown"
    title_comparable = bool(title and entry.get("title"))
    if title_comparable and _title_norm(title) == _title_norm(entry["title"]):
        return "ok"
    now_v = str(probe_verdict or "")
    old_v = str(entry.get("probe_verdict") or "")
    if now_v and old_v:
        if now_v == old_v and now_v not in UNRELIABLE_VERDICTS \
                and old_v not in UNRELIABLE_VERDICTS:
            return "ok"          # 标题可能变（如加了后缀），组件库一致即可信
        if now_v != old_v and old_v not in UNRELIABLE_VERDICTS:
            return "stale"
    if title_comparable:
        return "stale"           # 标题可比但不等，且无可靠 verdict 兜底
    return "unknown"


def should_direct_goto(entry) -> bool:
    """是否允许「直接 goto」。只有 verified 且非 stale 的条目才允许。

    未通过这一关的条目只能当线索：仍走 ``goto_feature`` 搜索并校验落地页。
    """
    if not entry or not entry.get("url"):
        return False
    return bool(entry.get("verified")) and not entry.get("stale")


def check_landing(page, host: str, feature: str) -> dict:
    """在已 goto 的页面上做一致性校验（页面标题 + 组件库判定）。

    返回 ``{"status": "ok|stale|unknown", "title":..., "probe_verdict":...}``；
    判定为 stale 时自动降级注册表条目。
    """
    entry = get_page(host, feature) or {}
    title = ""
    verdict = ""
    try:
        title = page.title()
    except Exception:
        pass
    try:
        from .fingerprint import probe_components
        verdict = (probe_components(page) or {}).get("verdict", "")
    except Exception:
        verdict = ""
    status = check_consistency(entry, title=title, probe_verdict=verdict)
    if status == "stale":
        mark_stale(host, feature, reason="title/probe 不一致")
    return {"status": status, "title": title, "probe_verdict": verdict}


def pages_for(url: str, feature=None):
    """便捷入口：按 URL 取站点注册表（可选过滤某功能）。"""
    host = host_of(url)
    if not host:
        return None
    data = load(host)
    if feature:
        return {"host": host, "entry": (data.get("pages") or {}).get(feature)}
    return data


def render_for_prompt(host: str, feature=None) -> str:
    """渲染成 ≤10 行的紧凑摘要，直接喂模型（替代 dump 整个注册表）。"""
    if not host:
        return "（未识别站点）"
    data = load(host)
    pages = data.get("pages") or {}
    lines = ["站点 {}（{} 个已登记页面）".format(host, len(pages))]
    items = [(feature, pages.get(feature))] if feature else list(pages.items())
    for name, e in items[:10]:
        if not e:
            lines.append("- {}：未登记（需侦察）".format(name))
            continue
        flags = []
        flags.append("已验证" if e.get("verified") else "仅观测")
        if e.get("stale"):
            flags.append("已失效")
        lines.append("- {}：{}｜{}｜命中{}次".format(
            name, e.get("url", ""), "/".join(flags), e.get("hits", 0)))
        if e.get("waits"):
            w = e["waits"][0] if isinstance(e["waits"], list) and e["waits"] else e["waits"]
            lines.append("    等待: {}".format(json.dumps(w, ensure_ascii=False)))
        if e.get("selectors"):
            lines.append("    选择器: {}".format(json.dumps(e["selectors"], ensure_ascii=False)))
        if e.get("gotchas"):
            lines.append("    坑: {}".format("；".join(e["gotchas"][:3])))
    return "\n".join(lines)


def fingerprint_name(host: str, feature: str) -> str:
    """指纹命名规范：<host>#<功能名>（防跨站点撞名）。"""
    return "{}#{}".format(_safe_host(host), feature)


if __name__ == "__main__":
    import sys

    host = host_of(sys.argv[1]) if len(sys.argv) > 1 else ""
    feat = sys.argv[2] if len(sys.argv) > 2 else None
    print(render_for_prompt(host, feat))
