# -*- coding: utf-8 -*-
"""单用例/批次执行闭环 CLI —— 现有 phase_runner 的**门面**，不新写执行内核。

为什么要它：实测大富会话 347 轮里，跑已有脚本 41.5% + 写跑内联脚本 23.6%
≈ **65% 的轮次花在脚本往返**上（写→跑→读错→改→重跑）。把这件事收敛成
「一次调用跑一批 + 单行 JSON 结果」，是唯一同时压成本与墙钟的手段。
（时间同样被轮次支配：2h20m / 347 轮 ≈ 24 秒/轮。）

**架构约束**：本模块不得直接读写检查点/台账状态文件，状态一律经
`RunState` / `PhaseRunner` 公共接口。由 `tests/test_case_cli_boundary.py`
静态断言守住（源码里连这两个文件名都不许出现）——防止门面演化成第二套状态管理。

输出契约：stdout **单行 JSON**、硬上限 `MAX_STDOUT_CHARS`，
形如::

    {"label":"C07","status":"pass","ms":1840,
     "signals":{"toasts":[],"form_errors":[],"http":[{"url":"...","status":200,"ms":88}],
                "data_diff":{}},
     "evidence":["/path/shot.png"],"detail_path":"...","next_hint":""}

完整现场落盘 `<run-dir>/cases/<label>.json`。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import output as O
from . import page_registry as REG
from .phase_runner import RunState

MAX_STDOUT_CHARS = 4096

# 单步超时基线（与 SKILL「执行形态与等待基线」一致）
DEFAULT_ACTION_MS = 5000
DEFAULT_NAV_MS = 15000
DEFAULT_API_TIMEOUT = 45.0


# ---------------------------------------------------------------- 输出

def _emit(payload, *, kind, run_dir=None, label=None, max_chars=MAX_STDOUT_CHARS):
    """输出到 stdout：单行 JSON、限长；完整版落盘 <run_dir>/cases/。"""
    out_dir = (Path(run_dir) / "cases") if run_dir else None
    return O.emit(payload, kind=kind, max_chars=max_chars, out_dir=out_dir, name=label)


def _finish(payload, *, kind, run_dir=None, label=None, code=0):
    print(_emit(payload, kind=kind, run_dir=run_dir, label=label))
    return code


def _err(msg, *, next_hint="", code=2, run_dir=None, label=None):
    return _finish({"status": "error", "error": str(msg)[:1000], "next_hint": next_hint},
                   kind="exec", run_dir=run_dir, label=label, code=code)


# ---------------------------------------------------------------- steps 引擎

def _net_of(watcher, limit=20):
    """把监听到的响应压成判定用的 http 列表（**判定字段，不截断**）。"""
    out = []
    try:
        for r in (watcher.snapshot() if hasattr(watcher, "snapshot") else [])[-limit:]:
            out.append({
                "url": r.get("url", ""),
                "method": r.get("method", ""),
                "status": r.get("status"),
                "ms": r.get("duration_ms") or r.get("ms"),
            })
    except Exception:
        pass
    return out


def _api_step(page, watcher, step):
    """wait_api：等待匹配的业务接口返回（动作已发生，只读观察）。"""
    kw = step.get("url_contains") or step.get("keyword")
    method = step.get("method")
    timeout = float(step.get("timeout") or DEFAULT_API_TIMEOUT)
    accept = step.get("accept_status")
    hits = watcher.wait_new(keyword=kw, timeout=timeout,
                            accept_status=set(accept) if accept else None)
    if method:
        hits = [h for h in hits if (h.get("method") or "").upper() == method.upper()]
    if not hits:
        raise TimeoutError("wait_api 未观测到匹配响应: {}".format(kw or "*"))
    return {"matched": len(hits), "url": hits[-1].get("url", ""),
            "status": hits[-1].get("status")}


def _run_step(page, watcher, step, i, out_dir, label, feature):
    """执行单步，返回 (ok, detail, evidence_path)。"""
    from . import bbt_helpers as H
    from .bbt_osd_common import goto as _goto

    act = (step.get("action") or "").strip()
    if not act:
        raise ValueError("第 {} 步缺少 action".format(i))
    scope = step.get("scope") or "body"

    if act == "goto":
        _goto(page, step["url"])
        return True, {"url": page.url}, ""
    if act == "click":
        r = H.click_visible_text(page, step["text"], timeout=int((step.get("timeout_ms") or DEFAULT_ACTION_MS)))
        ok = bool(r.get("clicked")) if isinstance(r, dict) else bool(r)
        return ok, {"text": step["text"], "via": (r or {}).get("via") if isinstance(r, dict) else ""}, ""
    if act == "fill":
        item = H.form_item(page, step["label"], scope=scope)
        item.locator("input, textarea").first.fill(str(step.get("value", "")))
        return True, {"label": step["label"]}, ""
    if act == "select":
        item = H.form_item(page, step["label"], scope=scope)
        H.open_select(page, item)
        H.select_option(page, item, step["option"])
        return True, {"label": step["label"], "option": step["option"]}, ""
    if act == "press":
        page.keyboard.press(step.get("key", "Enter"))
        return True, {"key": step.get("key", "Enter")}, ""
    if act == "sleep":
        ms = int(step.get("ms") or 300)
        if ms > 800:
            raise ValueError("sleep 上限 800ms（禁止长固定等待）：{}".format(ms))
        page.wait_for_timeout(ms)
        return True, {"ms": ms}, ""
    if act == "wait_api":
        return True, _api_step(page, watcher, step), ""
    if act == "assert_visible":
        to = float(step.get("timeout") or DEFAULT_NAV_MS / 1000)
        ok = H.wait_visible(page, "text={}".format(step["text"]), timeout=to)
        return bool(ok), {"text": step["text"]}, ""
    if act == "assert_text":
        to = float(step.get("timeout") or 3)
        hit = H.wait_text(page, step["text"], timeout=to)
        if not hit:
            raise AssertionError("未出现文本: {}".format(step["text"]))
        return True, {"text": step["text"]}, ""
    if act == "assert_value":
        item = H.form_item(page, step["label"], scope=scope)
        got = H.select_value(item) if step.get("kind") == "select" else (
            item.locator("input, textarea").first.input_value())
        exp = str(step.get("expect", ""))
        if str(got).strip() != exp.strip():
            raise AssertionError("{}: 期望 {!r} 实际 {!r}".format(step["label"], exp, got))
        return True, {"label": step["label"], "value": got}, ""
    if act == "read":
        sel = step.get("selector") or ".el-table__row"
        mx = int(step.get("max") or 20)
        loc = page.locator(sel)
        vals = []
        for j in range(min(loc.count(), mx)):
            try:
                vals.append((loc.nth(j).inner_text() or "").strip()[:200])
            except Exception:
                pass
        return True, {"selector": sel, "total": loc.count(), "head": vals}, ""
    if act == "snap":
        path = H.snap(page, step.get("name") or "step{}".format(i), out_dir, feature=feature)
        return True, {"screenshot": path}, path
    if act == "read_only_eval":
        val = page.evaluate(step.get("script", "() => null"))
        return True, {"value": O.summarize({"value": val})["value"]}, ""

    raise ValueError("未知 action: {}".format(act))


# ---------------------------------------------------------------- 子命令

def cmd_exec(args):
    from playwright.sync_api import sync_playwright

    from . import bbt_helpers as H
    from .api_wait import ApiWatcher
    from .bbt_osd_common import login_for_page

    spec_path = Path(args.steps).expanduser()
    if not spec_path.exists():
        return _err("steps 文件不存在: {}".format(spec_path), next_hint="给出 --steps <steps.json>")
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _err("steps 文件不是合法 JSON: {}".format(exc))
    if isinstance(spec, list):
        spec = {"steps": spec}
    steps = spec.get("steps") or []
    if not steps:
        return _err("steps 为空")

    url = args.url or spec.get("url") or ""
    feature = args.feature or spec.get("feature") or ""
    label = args.label or spec.get("label") or "exec"
    run_dir = Path(args.run_dir).expanduser() if args.run_dir else Path.cwd()
    out_dir = run_dir / "evidence"
    case_out = run_dir / "cases"
    case_out.mkdir(parents=True, exist_ok=True)

    started = time.time()
    results, evidence = [], []
    toasts, form_errors = [], []
    status = "pass"
    next_hint = ""
    steps_table = []

    steps_note = ""
    with sync_playwright() as pw:
        browser = H.launch_mes_browser(pw, headless=not args.visible)
        page = browser.new_context(viewport={"width": 1680, "height": 950},
                                   locale="zh-CN").new_page()
        try:
            H.configure_page_timeouts(page, action_ms=DEFAULT_ACTION_MS, navigation_ms=DEFAULT_NAV_MS)
            H.attach_error_watchers(page)
            watcher = ApiWatcher(page)
            if url:
                login_for_page(page, url)
                from .bbt_osd_common import goto as _goto
                landed, note = _land(page, url, feature, _goto)
                host = REG.host_of(page.url or url)
                if host and feature:
                    REG.upsert_page(host, feature, url=page.url, verified=True,
                                    title=_safe_title(page), fingerprint=REG.fingerprint_name(host, feature))
                if note:
                    steps_note = note
            for i, step in enumerate(steps):
                t0 = time.time()
                try:
                    ok, detail, ev = _run_step(page, watcher, step, i, out_dir, label, feature)
                except Exception as exc:
                    results.append({"i": i, "action": step.get("action"),
                                    "ok": False, "ms": int((time.time() - t0) * 1000),
                                    "error": "{}: {}".format(type(exc).__name__, exc)[:300]})
                    status = "fail"
                    try:
                        shot = H.snap(page, "{}_step{}_fail".format(label, i), out_dir, feature=feature)
                        evidence.append(shot)
                    except Exception:
                        pass
                    fb = _read_fb(page, H)
                    toasts = list(dict.fromkeys(toasts + (fb.get("toasts") or [])))
                    form_errors = list(dict.fromkeys(form_errors + (fb.get("form_errors") or [])))
                    next_hint = "第 {} 步失败；现场已落盘，先看 detail_path 再决定重试或记缺陷".format(i)
                    break
                if ev:
                    evidence.append(ev)
                results.append({"i": i, "action": step.get("action"), "ok": bool(ok),
                                "ms": int((time.time() - t0) * 1000), "detail": detail})
                steps_table.append({"i": i, "action": step.get("action"), "ok": bool(ok)})
            fb = _read_fb(page, H)
            toasts = list(dict.fromkeys(toasts + (fb.get("toasts") or [])))
            form_errors = list(dict.fromkeys(form_errors + (fb.get("form_errors") or [])))
            http = _net_of(watcher)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    elapsed = int((time.time() - started) * 1000)
    payload = {
        "label": label,
        "status": status,
        "ms": elapsed,
        "signals": {"toasts": toasts, "form_errors": form_errors,
                    "http": http, "data_diff": {}},
        "steps": results,
        "evidence": evidence,
        "next_hint": next_hint,
    }
    if steps_note:
        payload["registry"] = steps_note
    # 完整现场（含每步 detail）落盘，stdout 只回摘要
    try:
        detail_path = case_out / "{}.json".format(O._safe_name(label))
        detail_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["detail_path"] = str(detail_path)
    except Exception:
        pass
    return _finish(payload, kind="exec", run_dir=run_dir, label=label,
                   code=0 if status == "pass" else 1)


def _land(page, url, feature, goto_fn):
    """注册表感知的落地：命中 verified 才直接 goto，且必须过一致性校验。

    - 命中 verified=True → 直接 goto，再校验标题/组件库；不一致则标 stale、
      降级为仅观测，并回退走 goto_feature 重侦察。
    - 未命中 / 仅观测 → 直接走 goto_feature（按功能名搜索）。
    """
    host = REG.host_of(url)
    entry = REG.get_page(host, feature) if (host and feature) else None
    note = ""
    if REG.should_direct_goto(entry):
        try:
            goto_fn(page, entry["url"])
            check = REG.check_landing(page, host, feature)
            if check.get("status") == "ok":
                REG.record_hit(host, feature)
                return page.url, "直接 goto（注册表命中且校验通过）"
            note = "注册表条目已失效（{}），回退按功能名搜索".format(check.get("status"))
        except Exception as exc:
            note = "注册表 URL 不可达（{}），回退按功能名搜索".format(type(exc).__name__)
    try:
        from .bbt_osd_common import goto_feature
        landed = goto_feature(page, feature, base_url=host, use_cache=False) if feature else None
        if landed:
            return landed, note
    except Exception:
        pass
    goto_fn(page, url)
    return page.url, note


def cmd_pages(args):
    """查看站点注册表（≤10 行紧凑摘要，替代 dump 整表）。"""
    host = REG.host_of(args.url)
    if not host:
        return _err("无法从 URL 解析站点: {}".format(args.url))
    text = REG.render_for_prompt(host, args.feature)
    return _finish({"host": host, "registry": text, "status": "ok"},
                   kind="pages", run_dir=args.run_dir, label="pages", code=0)


def _safe_title(page):
    try:
        return page.title()
    except Exception:
        return ""


def _read_fb(page, H):
    try:
        return H.read_feedback(page) or {}
    except Exception:
        return {}


def cmd_status(args):
    run_dir = Path(args.run_dir).expanduser()
    state = RunState.load_or_create(run_dir, run_id=args.run_id or "")
    s = state.summary()
    payload = {
        "feature": s.get("feature", ""), "run_id": s.get("run_id", ""),
        "total": s.get("total", 0), "passed": s.get("passed", 0),
        "failed": s.get("failed", 0), "blocked": s.get("blocked", 0),
        "uncovered": s.get("uncovered", 0), "observations": s.get("observations", 0),
        "blocker_types": s.get("blocker_types", {}),
        "pending": [c for c, r in (state.cases or {}).items()
                    if (r or {}).get("status") not in ("通过", "pass")][:20],
    }
    return _finish(payload, kind="status", run_dir=run_dir, label="status", code=0)


def cmd_run(args):
    """跑 spec（run_all.py）：透传 --resume/--phase/--connect，然后回紧凑摘要。

    执行范围用 --phase 限定；--case 只影响输出摘要与 QA_ONLY_CASE 环境变量
    （spec 可以选择读取它来缩小范围）。
    """
    spec = Path(args.spec).expanduser()
    if not spec.exists():
        return _err("spec 不存在: {}".format(spec), next_hint="给出 --spec <run_all.py>")
    cmd = [sys.executable, str(spec)]
    if args.resume:
        cmd.append("--resume")
    if args.phase:
        cmd += ["--phase", args.phase]
    if args.connect:
        cmd.append("--connect")
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if args.case:
        env["QA_ONLY_CASE"] = args.case
    run_dir = Path(args.run_dir).expanduser() if args.run_dir else spec.parent
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(spec.parent), env=env,
                              capture_output=True, text=True, timeout=args.timeout)
        rc, tail = proc.returncode, (proc.stdout or "")[-400:]
    except subprocess.TimeoutExpired:
        rc, tail = 124, "spec 超时（{}s）".format(args.timeout)
    state = RunState.load_or_create(run_dir, run_id=args.run_id or "")
    s = state.summary()
    payload = {
        "spec": spec.name, "exit_code": rc, "ms": int((time.time() - t0) * 1000),
        "phase": args.phase or "", "resume": bool(args.resume),
        "summary": {k: s.get(k, 0) for k in
                    ("total", "passed", "failed", "blocked", "uncovered", "observations")},
        "tail": tail,
        "next_hint": "" if rc == 0 else "看 tail 与检查点摘要，优先 --resume 重跑失败项",
    }
    return _finish(payload, kind="run", run_dir=run_dir, label=args.phase or "run", code=0 if rc == 0 else 1)


def cmd_report(args):
    """由结构化状态重渲染报告（结论回流：改数据不改正文）。"""
    from .report_gen import gen_report

    run_dir = Path(args.run_dir).expanduser()
    state = RunState.load_or_create(run_dir, run_id=args.run_id or "")
    conclusions = _load_conclusions(run_dir)
    cases = state.results_for_report()
    if args.case:
        cases = [c for c in cases if c.get("id") == args.case]
    meta = dict(conclusions.get("meta") or {})
    meta.setdefault("功能", state.feature or "")
    text = gen_report(meta, cases,
                      conclusions.get("问题") or [],
                      conclusions.get("未覆盖") or [],
                      conclusions.get("证据") or [],
                      conclusions=conclusions.get("结论") or None)
    out = Path(args.out).expanduser() if args.out else (
        run_dir / "test-reports" / "{}_测试报告.md".format(state.feature or "测试"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    payload = {"report": str(out), "cases": len(cases),
               "conclusions": len(conclusions.get("结论") or []),
               "next_hint": ""}
    return _finish(payload, kind="report", run_dir=run_dir, label="report", code=0)


def _load_conclusions(run_dir: Path) -> dict:
    """读 <run-dir>/conclusions.json（结论回流的结构化唯一来源）。"""
    p = run_dir / "conclusions.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------- CLI

def build_parser():
    ap = argparse.ArgumentParser(
        prog="qa_case", description="单用例/批次执行闭环（phase_runner 的 CLI 门面）")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("exec", help="按 steps.json 跑一次 ad-hoc 动作序列")
    p.add_argument("--steps", required=True, help="steps JSON 路径")
    p.add_argument("--run-dir", default=None, help="产物目录（默认 cwd）")
    p.add_argument("--label", default=None, help="用例/批次标识")
    p.add_argument("--url", default=None, help="入口 URL（也可写在 steps.json 的 url 字段）")
    p.add_argument("--feature", default=None, help="功能名（用于注册表回写）")
    p.add_argument("--visible", action="store_true", help="可见窗口（默认无头）")
    p.set_defaults(func=cmd_exec)

    p = sub.add_parser("run", help="跑 run_all.py（透传 --resume/--phase）")
    p.add_argument("--spec", required=True, help="run_all.py 路径")
    p.add_argument("--phase", default=None)
    p.add_argument("--case", default=None, help="只影响摘要与环境变量 QA_ONLY_CASE")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--connect", action="store_true")
    p.add_argument("--run-dir", default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--timeout", type=int, default=3600)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="一行摘要")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--run-id", default=None)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("pages", help="查看站点/页面注册表（跨会话复用情报）")
    p.add_argument("--url", required=True)
    p.add_argument("--feature", default=None)
    p.add_argument("--run-dir", default=None)
    p.set_defaults(func=cmd_pages)

    p = sub.add_parser("report", help="由检查点状态 + conclusions.json 重渲染报告")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--run-id", default=None)
    p.add_argument("--case", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_report)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return _err("已中断", code=130)
    except Exception as exc:  # 任何异常都不许把 traceback 灌进 context
        return _err("{}: {}".format(type(exc).__name__, exc),
                    next_hint="把这一步拆成更小的 steps，或用 --visible 复现")


if __name__ == "__main__":
    raise SystemExit(main())
