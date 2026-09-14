# -*- coding: utf-8 -*-
"""通用预检：在创建/修改业务数据前验证页面、控件和主数据可用性。

预检失败属于基础能力问题，应停止当前阶段并保留现场，不写入业务缺陷。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .bbt_helpers import active_pane, assert_control_type
from .api_wait import wait_for_response_after_action


@dataclass
class PreflightCheck:
    id: str
    run: Callable[[Any], Any]
    critical: bool = True
    description: str = ""


@dataclass
class PreflightReport:
    ok: bool
    checks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checks": self.checks}

    def summary(self) -> str:
        failed = [c for c in self.checks if c.get("status") == "failed"]
        blocked = [c for c in self.checks if c.get("status") == "blocked"]
        if failed:
            return "预检失败: " + "; ".join(f"{c['id']}:{c.get('reason','')}" for c in failed[:5])
        if blocked:
            return "预检未完成: " + "; ".join(f"{c['id']}:{c.get('reason','')}" for c in blocked[:5])
        return "预检通过"


def _normalize_result(raw: Any) -> tuple[bool, str, dict]:
    if isinstance(raw, dict):
        ok = bool(raw.get("ok"))
        reason = str(raw.get("reason") or raw.get("why") or ("通过" if ok else "失败"))
        return ok, reason, raw
    if isinstance(raw, (tuple, list)):
        if not raw:
            return False, "空结果", {"value": raw}
        first = raw[0]
        if isinstance(first, str) and first in ("通过", "失败", "阻塞"):
            ok = first == "通过"
            reason = str(raw[-1]) if len(raw) > 1 else first
            return ok, reason, {"value": list(raw)}
        return bool(first), str(raw[-1] if len(raw) > 1 else first), {"value": list(raw)}
    if isinstance(raw, str):
        ok = raw == "通过"
        return ok, raw, {"value": raw}
    ok = bool(raw)
    return ok, "通过" if ok else "失败", {"value": raw}


class PreflightRunner:
    """顺序执行预检；关键检查失败后，后续检查标记 blocked。"""

    def run(self, page: Any, checks: list[PreflightCheck] | tuple[PreflightCheck, ...]) -> PreflightReport:
        records = []
        critical_failed = False
        for check in checks:
            if critical_failed:
                records.append({
                    "id": check.id,
                    "description": check.description,
                    "critical": check.critical,
                    "status": "blocked",
                    "reason": "前序关键预检失败",
                })
                continue
            try:
                ok, reason, detail = _normalize_result(check.run(page))
                status = "passed" if ok else "failed"
                if not ok and check.critical:
                    critical_failed = True
                records.append({
                    "id": check.id,
                    "description": check.description,
                    "critical": check.critical,
                    "status": status,
                    "reason": reason,
                    "detail": detail,
                })
            except Exception as exc:
                if check.critical:
                    critical_failed = True
                records.append({
                    "id": check.id,
                    "description": check.description,
                    "critical": check.critical,
                    "status": "failed",
                    "reason": f"{type(exc).__name__}: {exc}",
                })
        return PreflightReport(ok=not any(c.get("status") != "passed" for c in records), checks=records)


def url_check(contains: str, exact: bool = False) -> PreflightCheck:
    def _run(page):
        url = getattr(page, "url", "") or ""
        ok = url == contains if exact else contains in url
        return {"ok": ok, "reason": "URL 匹配" if ok else f"URL 不匹配: {url}", "url": url}
    return PreflightCheck(f"url:{contains}", _run, description="直达 URL")


def title_check(contains: str) -> PreflightCheck:
    def _run(page):
        title = page.title() or ""
        ok = contains in title
        return {"ok": ok, "reason": "标题匹配" if ok else f"标题不匹配: {title}", "title": title}
    return PreflightCheck(f"title:{contains}", _run, description="页面标题")


def active_pane_check(text: str | None = None, timeout: float = 0.0) -> PreflightCheck:
    def _run(page):
        deadline = time.time() + max(float(timeout), 0)
        pane_ok = False
        tab_ok = not text
        while True:
            pane = active_pane(page)
            pane_ok = pane.count() > 0
            if text:
                try:
                    tabs = page.locator(".el-tabs__item", has_text=str(text))
                    tab_ok = any(tabs.nth(i).is_visible() for i in range(tabs.count()))
                except Exception:
                    tab_ok = False
            else:
                tab_ok = True
            if pane_ok and tab_ok:
                return {"ok": True, "reason": "活动页签命中", "pane_ok": True, "tab_ok": True}
            if time.time() >= deadline:
                break
            time.sleep(0.25)
        return {
            "ok": False,
            "reason": f"活动页签不匹配: {text or '*'}",
            "pane_ok": pane_ok,
            "tab_ok": tab_ok,
        }
    return PreflightCheck(f"active_pane:{text or '*'}", _run, description="活动页签")


def control_type_check(locator_factory: Callable[[Any], Any], expected: str,
                       timeout: float = 3.0, name: str | None = None) -> PreflightCheck:
    cid = name or f"control:{expected}"

    def _run(page):
        locator = locator_factory(page)
        return assert_control_type(locator, expected, timeout=timeout)
    return PreflightCheck(cid, _run, description=f"控件类型={expected}")


def response_wait_check(action, url_contains=None, predicate=None, timeout: float = 60.0,
                        follow_up=None, name: str | None = None) -> PreflightCheck:
    """执行动作并等待匹配接口返回；接口返回后立即继续，不用固定 5 秒猜测完成。"""
    cid = name or f"response:{url_contains or '*'}"

    def _run(page):
        result = wait_for_response_after_action(
            page, action=lambda: action(page),
            url_contains=url_contains, predicate=predicate, timeout=timeout,
        )
        if not result.get("ok"):
            return result
        if follow_up is not None:
            detail = follow_up(page, result)
            if isinstance(detail, dict):
                detail.setdefault("response", {"status": result["status"], "url": result["url"]})
                return detail
            return {"ok": bool(detail), "reason": "follow_up_checked"}
        return {"ok": True, "reason": "接口已返回", "status": result["status"], "url": result["url"]}
    return PreflightCheck(cid, _run, description="页面接口返回等待")


def button_state_check(text: str, enabled: bool = True,
                       scope_factory: Callable[[Any], Any] | None = None) -> PreflightCheck:
    cid = f"button:{text}:{'enabled' if enabled else 'disabled'}"

    def _run(page):
        scope = scope_factory(page) if scope_factory else active_pane(page)
        loc = scope.get_by_role("button", name=text, exact=True).last
        if loc.count() == 0:
            return {"ok": False, "reason": "按钮不存在"}
        actual = loc.is_enabled()
        return {"ok": actual == enabled, "reason": f"按钮 enabled={actual}", "enabled": actual}
    return PreflightCheck(cid, _run, description=f"按钮 {text}")


__all__ = [
    "PreflightCheck", "PreflightReport", "PreflightRunner",
    "url_check", "title_check", "active_pane_check", "response_wait_check",
    "control_type_check", "button_state_check",
]
