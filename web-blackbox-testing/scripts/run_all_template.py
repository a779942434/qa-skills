# -*- coding: utf-8 -*-
"""总入口长脚本模板（B5/B6）——单登录、分阶段、可恢复。

一个任务 = 一个持久会话 + 一次登录 + 分阶段用例 + 检查点恢复。

用法：
    python run_all.py
    python run_all.py --resume
    python run_all.py --phase core-flow
    python run_all.py --connect

约定：
- 默认使用本机 Chrome/Edge 的持久会话（CDP 9222），先复用已有登录态；
- 每条用例执行后写 run_state.json，--resume 只重跑失败/阻塞/未执行项；
- 基础能力异常快停当前阶段并保存现场；业务失败记录后继续同阶段用例；
- 异常中断保留浏览器和检查点，正常完成才关闭本轮启动的持久浏览器。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path


def _find_scripts_dir() -> Path:
    """兼容“仓库内运行”和“复制到任务目录运行”两种形态。"""
    here = Path(__file__).resolve()
    if (here.parent / "qa_skill_common").exists():
        return here.parent
    for base in here.parents:
        cand = base / "web-blackbox-testing" / "scripts"
        if (cand / "qa_skill_common").exists():
            return cand
    return here.parent


SCRIPTS_DIR = _find_scripts_dir()
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from api_wait import ApiWatcher  # noqa: E402
from qa_skill_common import paths as qa_paths  # noqa: E402
from qa_skill_common.phase_runner import (  # noqa: E402
    BLOCK, FAIL, PASS, CaseGroupSpec, CaseSpec, PhaseRunner, PhaseSpec, RunContext, RunState,
)
from qa_skill_common.preflight import (  # noqa: E402
    active_pane_check, button_state_check, control_type_check, response_wait_check, url_check,
)
from bbt_helpers import (  # noqa: E402
    attach_error_watchers, capture_failure_context, configure_page_timeouts,
    error_report, reset_to, snap,
)
from report_gen import gen_report  # noqa: E402
from session_helpers import (  # noqa: E402
    cdp_health, connect_session, ensure_mes_session, stop_persistent_session,
)

# ============================ CONFIG（按任务改） ============================
_OUT_DIR = Path(os.environ.get("OUT_DIR", str(qa_paths.test_reports_dir())))

CONFIG = {
    "feature": "待填功能名",
    "run_id": os.environ.get("RUN_ID", ""),
    "base_url": os.environ.get("MES_URL", ""),
    "headless": True,
    "cdp_port": int(os.environ.get("MES_CDP_PORT", "9222")),
    "session_dir": os.environ.get("MES_SESSION_DIR", ""),
    "out_dir": _OUT_DIR,
    "state_dir": Path(os.environ.get("RUN_STATE_DIR", str(_OUT_DIR / "state"))),
}

# ============================ CASES（简单兼容模式） =========================
# 每条：{"id","模块","url"(目标页面，用于回到已知态),"tab"(可选页签),"keyword"(可选接口URL关键词)}
CASES = [
    {"id": "P0-01", "模块": "待填模块", "url": "", "tab": None, "keyword": None},
]

# ============================ PHASES（推荐模式） ============================
# 按任务填写阶段；为空时自动把 CASES 包装为 default 阶段。
# 示例：
# PHASES = [
#     PhaseSpec("bootstrap", cases=()),
#     PhaseSpec("data-setup", cases=(CaseSpec("SETUP-01", setup_case),)),
#     PhaseSpec("core-flow",
#         depends_on=("data-setup",),
#         provides_data=("split_no",),
#         preflight=(
#             url_check("/plan/work-plan/outsource-scheduling/index"),
#             # 页面动作触发接口时，以接口返回为完成信号，不用固定 5 秒猜完成
#             response_wait_check(
#                 lambda page: page.locator(".el-tabs__item", has_text="零件委外").click(),
#                 url_contains="outsource", timeout=60,
#             ),
#             active_pane_check("零件委外", timeout=0),
#             control_type_check(lambda page: active_pane(page).locator(".el-form-item", has_text="产品"), "select"),
#         ),
#         groups=(
#             CaseGroupSpec(
#                 "add-dialog-micro",
#                 setup=open_add_dialog,
#                 reset=reset_add_dialog,
#                 teardown=close_add_dialog,
#                 cases=(
#                     CaseSpec("FORM-001", validate_required, module="新增弹窗"),
#                     CaseSpec("FORM-002", validate_precision, module="新增弹窗"),
#                 ),
#             ),
#         ),
#         cases=(CaseSpec("CORE-01", core_case, module="核心流程"),),
#         requires_data=("base_product",),
#     ),
# ]
PHASES: list[PhaseSpec] = []

# 台账校验器：key 对应 RunContext.set_data 写入的数据；--resume 时用于判断数据是否仍有效。
# 示例：
# DATA_VALIDATORS = {
#     "split_no": lambda value: check_split_exists(page, value),
# }
DATA_VALIDATORS: dict = {}


def run_case(page, watcher, case):
    """简单 CASES 模式的单条用例适配器。

    按任务改写本函数即可。返回兼容格式：
    - CaseResult
    - (结果, 证据, 备注)
    - {"status": "...", "evidence": "...", "note": "..."}
    """
    if case.get("url"):
        reset_to(page, case["url"], case.get("tab"))

    def action():
        # 【按任务改】替换为真实标准操作（只做点击/键入/下拉，禁止 JS 注入改值）。
        # page.get_by_role("button", name="查询").click()
        pass

    # 动作与接口响应绑定：接口返回即继续，timeout 只作异常上限。
    new = watcher.wait_action(
        action,
        keyword=case.get("keyword"),
        url_contains=case.get("keyword"),
        timeout=60,
    )
    if not new:
        ev = snap(page, f"{case['id']}_no_response", CONFIG["out_dir"], feature=CONFIG["feature"])
        return "失败", ev, "匹配业务接口未返回或超时"

    page.wait_for_timeout(500)
    ok = True  # 【按任务改】替换为真实断言；优先数据变化，toast 仅辅助
    ev = snap(page, case["id"], CONFIG["out_dir"], feature=CONFIG["feature"])
    return ("通过" if ok else "失败"), ev, ""


def _first_url() -> str:
    if CONFIG.get("base_url"):
        return CONFIG["base_url"]
    for case in CASES:
        if case.get("url"):
            return case["url"]
    return ""


def _build_phases(watcher) -> list[PhaseSpec]:
    if PHASES:
        return PHASES
    cases = tuple(
        CaseSpec(
            id=case["id"],
            module=case.get("模块", ""),
            run=lambda ctx, page, c=case: run_case(page, watcher, c),
        )
        for case in CASES
    )
    return [PhaseSpec("default", cases=cases)]


def _capture_failure(**kwargs):
    """PhaseRunner 的基础异常现场捕获回调。"""
    page = kwargs.pop("page")
    name = kwargs.pop("name")
    return capture_failure_context(
        page, CONFIG["out_dir"], name,
        feature=CONFIG["feature"], extra=kwargs,
    )


def _keep_persistent_session(state: RunState) -> bool:
    """基础能力阻塞时保留会话，方便 --resume；业务失败仍算正常结束。"""
    for rec in state.phases.values():
        note = rec.get("note", "")
        if rec.get("status") == BLOCK and "基础能力异常" in note:
            return True
    return False


def _teardown(persistent, pw, browser, ctx, page, keep: bool):
    if persistent and persistent.started and not keep:
        stop_persistent_session(persistent)
    elif persistent and persistent.started:
        print(f"[run_all] 保留持久会话：{persistent.cdp_url}")
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="web-blackbox-testing 分阶段长测试模板")
    ap.add_argument("--resume", action="store_true", help="读取检查点，跳过已通过项")
    ap.add_argument("--phase", help="只运行指定阶段及其依赖阶段")
    ap.add_argument("--connect", action="store_true", help="连接已有持久浏览器，不新起会话")
    args = ap.parse_args()

    CONFIG["out_dir"].mkdir(parents=True, exist_ok=True)
    CONFIG["state_dir"].mkdir(parents=True, exist_ok=True)
    run_id = CONFIG["run_id"] or f"{CONFIG['feature']}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    state = RunState.load_or_create(CONFIG["state_dir"], run_id=run_id, feature=CONFIG["feature"])

    first_url = _first_url()
    persistent = None
    pw = browser = ctx = page = None
    summary = state.summary()
    keep_session = False
    try:
        if args.connect and cdp_health(
            f"http://127.0.0.1:{CONFIG['cdp_port']}", timeout=1.0,
        ).ok:
            pw, browser, ctx, page = connect_session(
                cdp_url=f"http://127.0.0.1:{CONFIG['cdp_port']}",
                url_contains=None,
            )
            # 已有会话仍需确保登录；ensure_login 已登录会直接跳过。
            from bbt_osd_common import ensure_login
            ensure_login(page, target_url=first_url, base_url=CONFIG["base_url"])
        else:
            persistent, pw, browser, ctx, page = ensure_mes_session(
                base_url=CONFIG["base_url"],
                target_url=first_url,
                headless=CONFIG["headless"],
                cdp_port=CONFIG["cdp_port"],
                session_dir=CONFIG["session_dir"] or None,
                login=True,
                auto_restart=True,
                restart_attempts=2,
            )
        if persistent and persistent.recoveries_this_run:
            state.meta["session_restarts"] = int(persistent.recoveries_this_run)
            state.meta["last_restart_error"] = persistent.last_health_error
            state.save()
            print(
                f"[run_all] 本轮持久浏览器已自动恢复 {persistent.recoveries_this_run} 次；"
                f"检查点继续使用 {state.state_path}"
            )
        configure_page_timeouts(page)

        watchers = attach_error_watchers(page)
        watcher = ApiWatcher(page)
        context = RunContext(state=state, page=page, extras={"watcher": watcher})
        runner = PhaseRunner(
            page=page,
            state=state,
            context=context,
            capture_failure=_capture_failure,
            validators=DATA_VALIDATORS,
        )
        summary = runner.run(
            _build_phases(watcher),
            resume=args.resume,
            selected_phase=args.phase,
        )

        errs = error_report(watchers)
        problems = []
        evidence = []
        for rec in state.cases.values():
            if rec.get("evidence"):
                evidence.append(str(rec["evidence"]))
        for item in state.results_for_report():
            if item["结果"] != PASS:
                problems.append({
                    "id": item["id"],
                    "标题": item.get("备注") or "待补充",
                    "级别": "待确认",
                    "备注": item.get("阻塞类型", ""),
                })
        if errs:
            problems.append({"id": "ERR", "标题": "错误监听命中", "级别": "待确认", "备注": str(errs)[:500]})

        meta = {"功能": CONFIG["feature"], "环境": CONFIG["base_url"] or first_url}
        report = gen_report(meta, state.results_for_report(), problems, uncovered=[], evidence=evidence)
        report_path = CONFIG["out_dir"] / "测试报告.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"[run_all] 检查点：{state.state_path}")
        print(f"[run_all] 数据台账：{state.ledger_path}")
        print(f"[run_all] 报告已生成：{report_path}")
    except KeyboardInterrupt:
        keep_session = True
        print("[run_all] 用户中断：保留持久会话和检查点，可用 --resume 继续")
        raise
    finally:
        keep_session = keep_session or _keep_persistent_session(state)
        _teardown(persistent, pw, browser, ctx, page, keep_session)


if __name__ == "__main__":
    main()
