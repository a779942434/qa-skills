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
from . import coverage as coverage_mod
from . import metrics as metrics_mod
from . import oracle
from . import run_package
from .phase_runner import RunState

# stdout 硬上限（4 KiB）。依据：单次工具结果控制在 ~600–1000 tokens 量级，
# 与「压每轮新增 context」这条主线一致。实测余量：run 载荷 496 字符、
# exec 紧凑 40 步 2030 字符（均 <4096）；而带 detail 的 40 步是 55870 字符，
# 说明**上限不是问题、载荷结构才是**——detail 因此一律落盘、不进 stdout。
# 注意：4096 是设计取值，不是测量或宿主限制推导出来的。
MAX_STDOUT_CHARS = 4096

# 单步超时基线（与 SKILL「执行形态与等待基线」一致）
DEFAULT_ACTION_MS = 5000
DEFAULT_NAV_MS = 15000
DEFAULT_API_TIMEOUT = 45.0


# ---------------------------------------------------------------- 输出

def _emit(payload, *, kind, run_dir=None, label=None, max_chars=MAX_STDOUT_CHARS,
          full_path_hint=None):
    """输出到 stdout：单行 JSON、限长；完整版落盘 <run_dir>/cases/。

    ``full_path_hint``：调用方已自落全量现场时传入，交给 ``O.emit`` 复用，
    避免同一份现场落两份文件（G2）。
    """
    out_dir = (Path(run_dir) / "cases") if run_dir else None
    return O.emit(payload, kind=kind, max_chars=max_chars, out_dir=out_dir, name=label,
                  reuse_full=full_path_hint)


def _finish(payload, *, kind, run_dir=None, label=None, code=0, full_path_hint=None):
    print(_emit(payload, kind=kind, run_dir=run_dir, label=label,
                full_path_hint=full_path_hint))
    return code


def _err(msg, *, next_hint="", code=2, run_dir=None, label=None):
    return _finish({"status": "error", "error": str(msg)[:1000], "next_hint": next_hint},
                   kind="exec", run_dir=run_dir, label=label, code=code)


# ---------------------------------------------------------------- steps 引擎

def stdout_step(i, action, ok, ms, error=""):
    """构造 stdout 的 step 行：**只留判定所需字段**，detail 一律不进 stdout。

    两级输出是 4KB 上限能"结构性成立"的关键：带 detail 的 40 步是 55870 字符，
    紧凑行只有 2030 字符。error 是判定字段，必须留在 stdout。
    """
    row = {"i": i, "action": action, "ok": bool(ok), "ms": int(ms)}
    if error:
        row["error"] = error
    return row


def _net_of(watcher, limit=20):
    """把监听到的响应压成判定用的 http 列表（**判定字段，不截断**）。

    返回 ``(rows, error)``。error 非空表示这次没能取到信号——**必须上报**，
    不能静默返回空列表：HTTP 信号是红线 A#7「多信号交叉判定」的四源之一，
    静默变空会让「已发出请求」被误判成「无新响应」。
    """
    try:
        rows = watcher.recent(limit) if hasattr(watcher, "recent") else []
        return [{
            "url": r.get("url", ""),
            "method": r.get("method", ""),
            "status": r.get("status"),
            "ms": r.get("duration_ms") or r.get("ms"),
        } for r in (rows or [])], ""
    except Exception as exc:
        return [], "{}: {}".format(type(exc).__name__, exc)[:200]


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

def cmd_init(args):
    """初始化标准运行包；不联网，不覆盖已有文件（除非 --force）。"""
    run_dir = Path(args.run_dir).expanduser()
    base_url = args.base_url or os.environ.get("MES_URL", "")
    environment = run_package.environment_snapshot(
        base_url,
        tenant_alias=args.tenant or "",
        role=args.role or "",
        location_org=args.location or "",
        config_fingerprint=args.config_fingerprint or "",
        browser_profile=args.browser_profile or "",
        app_version=args.app_version or "",
    )
    try:
        paths = run_package.init_run_package(
            run_dir, args.feature, mode=args.mode,
            requirements=args.requirement or [], force=args.force,
            run_id=args.run_id or "", environment=environment,
        )
        state = RunState.load_or_create(run_dir, run_id=args.run_id or "", feature=args.feature)
        state.save()
    except FileExistsError as exc:
        return _err(str(exc), next_hint="确认要覆盖时加 --force", code=1)
    payload = {
        "status": "initialized",
        "run_dir": str(run_dir),
        "mode": args.mode,
        "requirements": list(args.requirement or []),
        "files": paths,
    }
    return _finish(payload, kind="init", run_dir=run_dir, label="init", code=0)


def cmd_audit(args):
    """审计标准运行包；strict 时质量缺口返回 1。"""
    run_dir = Path(args.run_dir).expanduser()
    audit = run_package.audit_run_package(run_dir, strict=args.strict)
    payload = {
        "ok": audit["ok"],
        "structure_ok": audit.get("structure_ok", True),
        "strict": audit["strict"],
        "errors": audit["errors"],
        "warnings": audit["warnings"],
        "summary": audit["summary"],
    }
    code = 0 if audit["ok"] else (2 if not audit.get("structure_ok", True) else 1)
    return _finish(payload, kind="audit", run_dir=run_dir, label="audit", code=code)


def cmd_metrics(args):
    """聚合运行包指标，默认输出紧凑 JSON。"""
    root = Path(args.root).expanduser()
    result = metrics_mod.collect_metrics(root, since=args.since)
    payload = {
        "schema_version": result["schema_version"],
        "root": result["root"],
        "since": result["since"],
        "summary": result["summary"],
        "runs": result["runs"],
    }
    return _finish(payload, kind="metrics", run_dir=root, label="metrics", code=0)


def _replay_path(run_dir: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    return p if p.is_absolute() else run_dir / p


def cmd_replay(args):
    """执行缺陷记录中的最小回放脚本，写入证据并更新复现台账。"""
    run_dir = Path(args.run_dir).expanduser()
    try:
        defect = run_package.find_defect(run_dir, args.defect)
    except KeyError as exc:
        return _err(str(exc), next_hint="检查 defects.json 中的缺陷编号", code=1)
    replay = defect.get("replay") or {}
    script = replay.get("script")
    if not script:
        return _err("该缺陷没有 replay.script，不能自动回放", next_hint="先补最小复现脚本", code=1)
    script_path = _replay_path(run_dir, script)
    if not script_path.exists():
        return _err(f"回放脚本不存在: {script_path}", code=1)
    cmd = [sys.executable, str(script_path)] + [str(x) for x in (replay.get("args") or [])]
    timeout = int(replay.get("timeout") or 300)
    expected = int(replay.get("expect_exit_code") or 0)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(run_dir), capture_output=True, text=True, timeout=timeout)
        rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        rc, out, err = 124, "", "回放超时"
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ev_path = evidence_dir / f"replay_{defect.get('id', 'defect')}_{int(time.time())}.json"
    ev_path.write_text(json.dumps({
        "defect_id": defect.get("id"),
        "command": cmd,
        "exit_code": rc,
        "expected_exit_code": expected,
        "stdout": out[-4000:],
        "stderr": err[-4000:],
        "ms": int((time.time() - t0) * 1000),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    ev = run_package.add_evidence(
        run_dir, ev_path, defect_id=defect.get("id", ""), source="replay",
        reproduction={"attempts": 1, "successes": 1 if rc == expected else 0,
                      "deterministic_api": bool(replay.get("deterministic_api"))},
    )
    repro = dict(defect.get("reproducibility") or {})
    attempts = int(repro.get("attempts") or 0) + 1
    successes = int(repro.get("successes") or 0) + (1 if rc == expected else 0)
    repro.update({"attempts": attempts, "successes": successes,
                  "deterministic_api": bool(repro.get("deterministic_api") or replay.get("deterministic_api"))})
    run_package.update_defect(run_dir, defect.get("id", ""), {
        "reproducibility": repro,
        "evidence_ids": list(dict.fromkeys((defect.get("evidence_ids") or []) + [ev["id"]])),
    })
    payload = {
        "status": "pass" if rc == expected else "fail",
        "defect": defect.get("id"),
        "exit_code": rc,
        "expected_exit_code": expected,
        "evidence_id": ev["id"],
        "evidence": str(ev_path),
        "reproducibility": repro,
    }
    return _finish(payload, kind="replay", run_dir=run_dir, label="replay",
                   code=0 if rc == expected else 1)


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
    os.environ.setdefault("QA_JUDGE_LOG", str(run_dir / "judgements.jsonl"))

    started = time.time()
    results, stdout_steps, evidence = [], [], []
    toasts, form_errors = [], []
    status = "pass"
    next_hint = ""
    net_error = ""

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
                landed, note, verified_ok = _land(page, url, feature, _goto)
                host = REG.host_of(page.url or url)
                if host and feature:
                    # 只有真实验证成功才登记 verified=True；否则按「仅观测」登记，
                    # 下次仍走 goto_feature 重侦察——避免把落错的页面永久缓存。
                    REG.upsert_page(host, feature, url=page.url, verified=verified_ok,
                                    title=_safe_title(page),
                                    fingerprint=REG.fingerprint_name(host, feature))
                if note or not verified_ok:
                    steps_note = note or "落地页未验证通过（已按仅观测登记），下次仍走按功能名搜索"
            for i, step in enumerate(steps):
                t0 = time.time()
                try:
                    ok, detail, ev = _run_step(page, watcher, step, i, out_dir, label, feature)
                except Exception as exc:
                    err = "{}: {}".format(type(exc).__name__, exc)[:300]
                    ms = int((time.time() - t0) * 1000)
                    # error 是判定字段：detail 落盘，error 必须留在 stdout
                    results.append({"i": i, "action": step.get("action"),
                                    "ok": False, "ms": ms, "error": err})
                    stdout_steps.append(stdout_step(i, step.get("action"), False, ms, err))
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
                ms = int((time.time() - t0) * 1000)
                # 两级输出：detail 只进 cases/<label>.json；stdout 只留判定所需字段
                results.append({"i": i, "action": step.get("action"), "ok": bool(ok),
                                "ms": ms, "detail": detail})
                stdout_steps.append(stdout_step(i, step.get("action"), ok, ms))
            fb = _read_fb(page, H)
            toasts = list(dict.fromkeys(toasts + (fb.get("toasts") or [])))
            form_errors = list(dict.fromkeys(form_errors + (fb.get("form_errors") or [])))
            http, net_error = _net_of(watcher)
        finally:
            try:
                browser.close()
            except Exception:
                pass

    for evidence_path in evidence:
        try:
            run_package.add_evidence(run_dir, evidence_path, case_id=label, source="ui")
        except Exception:
            pass
    elapsed = int((time.time() - started) * 1000)
    signals = {"toasts": toasts, "form_errors": form_errors,
               "http": http, "data_diff": {}}
    if net_error:
        # 取信号失败必须显式可见，不能静默成空列表（红线 A#7 四源之一）
        signals["_net_error"] = net_error
    full_payload = {
        "label": label,
        "status": status,
        "ms": elapsed,
        "signals": signals,
        "steps": results,              # 含 detail
        "evidence": evidence,
        "next_hint": next_hint,
    }
    if steps_note:
        full_payload["registry"] = steps_note
    # 完整现场（含每步 detail）落盘；stdout 只回紧凑摘要
    try:
        detail_path = case_out / "{}.json".format(O.safe_name(label))
        detail_path.write_text(json.dumps(full_payload, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        detail_path_str = str(detail_path)
    except Exception:
        detail_path_str = ""
    stdout_payload = dict(full_payload)
    stdout_payload["steps"] = stdout_steps
    if detail_path_str:
        stdout_payload["detail_path"] = detail_path_str
    # G2：全量现场已写 detail_path，stdout 截断时复用它，不再另落 <label>.exec.json
    return _finish(stdout_payload, kind="exec", run_dir=run_dir, label=label,
                   code=0 if status == "pass" else 1, full_path_hint=detail_path_str)


def _land(page, url, feature, goto_fn):
    """注册表感知的落地：命中 verified 才直接 goto，且必须过一致性校验。

    - 命中 verified=True → 直接 goto，再校验标题/组件库；不一致则标 stale、
      降级为仅观测，并回退走 goto_feature 重侦察。
    - 未命中 / 仅观测 → 直接走 goto_feature（按功能名搜索）。
    - 返回 ``(landed_url, note, verified_ok)``；**只有前两条路径算验证成功**，
      最后的兜底 goto 不算——调用方必须据此决定注册表写 verified 还是仅观测。
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
                return page.url, "直接 goto（注册表命中且校验通过）", True
            note = "注册表条目已失效（{}），回退按功能名搜索".format(check.get("status"))
        except Exception as exc:
            note = "注册表 URL 不可达（{}），回退按功能名搜索".format(type(exc).__name__)
    try:
        from .bbt_osd_common import goto_feature
        landed = goto_feature(page, feature, base_url=host, use_cache=False) if feature else None
        if landed:
            return landed, note, True
    except Exception as exc:
        note = note or "按功能名搜索失败（{}）".format(type(exc).__name__)
    goto_fn(page, url)
    return page.url, note or "按功能名搜索未命中，已回退到给定 URL（未验证）", False


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


def _resolve_state_dir(spec_path: Path, explicit=None) -> Path:
    """定位检查点目录（P1-1：必须与 spec 实际写入同源）。

    优先级：``--run-dir`` > spec 同目录（已有检查点）> ``RUN_STATE_DIR``
    > ``<产物根>/knowledge-base/test-reports/state``（run_all_template 的默认值）。
    都不存在时回退 spec 同目录，并由调用方向子进程导出 RUN_STATE_DIR 保证一致。
    """
    if explicit:
        return Path(explicit).expanduser()
    candidates = [spec_path.parent]
    env_dir = os.environ.get("RUN_STATE_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    try:
        from . import paths
        candidates.append(paths.test_reports_dir() / "state")
    except Exception:
        pass
    found = RunState.find_existing(candidates)   # 文件名由 RunState 独占维护
    return found if found else candidates[0]


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
    run_dir = _resolve_state_dir(spec, args.run_dir)
    # 让子进程写进我们将要读的目录（不覆盖用户显式设置的 RUN_STATE_DIR）
    if not env.get("RUN_STATE_DIR"):
        env["RUN_STATE_DIR"] = str(run_dir)
    # 判定埋点：跨进程可观测，供 run/report 统计「是否走了 qa_action 统一入口」
    if not env.get("QA_JUDGE_LOG"):
        env["QA_JUDGE_LOG"] = str(run_dir / "judgements.jsonl")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(spec.parent), env=env,
                              capture_output=True, text=True, timeout=args.timeout)
        rc, tail = proc.returncode, (proc.stdout or "")[-400:]
    except subprocess.TimeoutExpired:
        rc, tail = 124, "spec 超时（{}s）".format(args.timeout)
    state = RunState.load_or_create(run_dir, run_id=args.run_id or "")
    try:
        if not (run_dir / run_package.MANIFEST).exists():
            run_package.init_run_package(
                run_dir, state.feature or spec.stem, mode="standard",
                run_id=state.run_id or "",
                environment=run_package.environment_snapshot(os.environ.get("MES_URL", "")),
            )
        run_package.update_manifest(
            run_dir, tooling={"qa_case": True, "phase_runner": True},
        )
    except Exception:
        pass
    s = state.summary()
    payload = {
        "spec": spec.name, "exit_code": rc, "ms": int((time.time() - t0) * 1000),
        "phase": args.phase or "", "resume": bool(args.resume),
        "summary": {k: s.get(k, 0) for k in
                    ("total", "passed", "failed", "blocked", "uncovered", "observations")},
        "tail": tail,
        "next_hint": "" if rc == 0 else "看 tail 与检查点摘要，优先 --resume 重跑失败项",
    }
    try:
        audit = run_package.audit_run_package(run_dir, strict=False)
        payload["audit"] = {
            "ok": audit["ok"],
            "errors": audit["errors"][:5],
            "warnings": audit["warnings"][:5],
        }
    except Exception:
        pass
    try:
        from .qa_action import summarize as _summ
        jg = _summ(env.get("QA_JUDGE_LOG") or (run_dir / "judgements.jsonl"))
        payload["judgements"] = {"total": jg["total"], "verdict": jg["verdict"],
                                 "control": jg["control"], "failed": jg["failed"]}
        if not jg["total"]:
            payload["next_hint"] = ("未检测到判定动作（judgements.total=0）——是否绕过了 "
                                    "qa_action 统一入口？判定类动作应走 qa_action.verdict/control")
    except Exception:
        pass
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
    pkg = run_package.load_package(run_dir)
    cov = coverage_mod.audit_coverage(pkg["contract"], pkg["coverage"], state, strict=False)
    evidence_items = (pkg.get("evidence") or {}).get("items") or []
    for case in cases:
        if not case.get("证据"):
            linked = [str(e.get("path") or "") for e in evidence_items
                      if str(e.get("case_id") or "") == str(case.get("id") or "")]
            if linked:
                case["证据"] = " ".join(dict.fromkeys(p for p in linked if p))
    ui_executed = any(
        str(c.get("oracle_mode") or "ui").lower() == "ui"
        and str(c.get("status") or "") in coverage_mod.EXECUTED_STATUSES
        for c in cov.get("cases", {}).values()
    )
    try:
        if ui_executed:
            from .qa_action import summarize as _summ
            meta["判定动作"] = _summ(run_dir / "judgements.jsonl")
    except Exception:
        pass
    text = gen_report(meta, cases,
                      conclusions.get("问题") or [],
                      conclusions.get("未覆盖") or [],
                      conclusions.get("证据") or [],
                      conclusions=conclusions.get("结论") or None,
                      coverage=cov.get("summary") or None,
                      evidence_index=(pkg.get("evidence") or {}).get("items") or None,
                      defects=(pkg.get("defects") or {}).get("defects") or None)
    out = Path(args.out).expanduser() if args.out else (
        run_dir / "test-reports" / "{}_测试报告.md".format(state.feature or "测试"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    jg = meta.get("判定动作") or {}
    payload = {"report": str(out), "cases": len(cases),
               "conclusions": len(conclusions.get("结论") or []),
               "judgements": {"total": jg.get("total", 0), "verdict": jg.get("verdict", 0),
                              "control": jg.get("control", 0)},
               "next_hint": ("" if (not ui_executed or jg.get("total"))
                             else "judgements.total=0：本次存在 UI 判定用例，未走 qa_action 统一判定入口")}
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

    p = sub.add_parser("init", help="初始化标准运行包（不联网）")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--feature", required=True)
    p.add_argument("--mode", choices=("quick", "standard", "deep"), default="standard")
    p.add_argument("--requirement", action="append", default=[], help="需求编号/URL，可重复")
    p.add_argument("--run-id", default=None)
    p.add_argument("--base-url", default=None)
    p.add_argument("--tenant", default=None)
    p.add_argument("--role", default=None)
    p.add_argument("--location", default=None)
    p.add_argument("--config-fingerprint", default=None)
    p.add_argument("--browser-profile", default=None)
    p.add_argument("--app-version", default=None)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("audit", help="审计运行包覆盖、证据、复现和清理")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--strict", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("metrics", help="聚合运行包质量与效率指标")
    p.add_argument("--root", default="runs")
    p.add_argument("--since", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("replay", help="执行缺陷最小回放脚本")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--defect", required=True)
    p.set_defaults(func=cmd_replay)

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
