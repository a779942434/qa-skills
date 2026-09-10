# -*- coding: utf-8 -*-
"""总入口长脚本模板（B5/B6）—— web-blackbox-testing 技能配套。

一个任务 = 一个后台会话 + 一次登录 + 一个总入口脚本串行跑完全部用例。
复制本文件为任务目录下的 run_all.py，按任务改 CONFIG 与 CASES 即可：

    cp scripts/run_all_template.py <任务目录>/run_all.py
    MES_URL=http://<host> MES_ACCOUNT=<账号> MES_PASSWORD=<密码> python3 <任务目录>/run_all.py

可选：复用已启动的常驻浏览器（不重新起会话）时加 `--connect`。

约定（对应 SKILL.md「必守清单」与「Playwright 使用策略」）：
- B5 一次会话跑完：不要每个用例新起浏览器 + 重新登录；总入口一次提权批准即可。
- B6 等待顺序：接口观测等待（ApiWatcher）> 条件等待 > 固定 sleep（仅 <=500ms 渲染余量）。
- 失败分级：环境失败（5xx/超时/网络）跳过不重试；业务失败重试 <=1 次后截图进缺陷清单。
- 用例间独立：每条 try/except + reset_to 回到已知态，单条失败不中断整段、不脏状态传染。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from api_wait import ApiWatcher  # noqa: E402
from qa_skill_common import paths as qa_paths  # noqa: E402
from bbt_osd_common import login_for_page  # noqa: E402
from bbt_helpers import (  # noqa: E402
    attach_error_watchers, error_report, reset_to, snap,
)
from report_gen import gen_report  # noqa: E402
from session_helpers import (  # noqa: E402
    close_session, connect_session, launch_session,
)

# ============================ CONFIG（按任务改） ============================
CONFIG = {
    "feature": "待填功能名",
    # 站点：优先 MES_URL；留空则取首个用例 url 的根地址
    "base_url": os.environ.get("MES_URL", ""),
    "headless": True,
    "cdp_port": 9222,           # 只想复用常驻浏览器时用（--connect）
    # 默认落到统一产物根 <workspace>/knowledge-base/test-reports（可用 OUT_DIR 覆盖）
    "out_dir": Path(os.environ.get("OUT_DIR", str(qa_paths.test_reports_dir()))),
}

# ============================ CASES（按任务改） =============================
# 每条：{"id","模块","url"(目标页面，用于回到已知态),"tab"(可选页签),"keyword"(可选接口URL关键词)}
CASES = [
    {"id": "P0-01", "模块": "待填模块", "url": "", "tab": None, "keyword": None},
]


def run_case(page, watcher, case):
    """执行单条用例：回到已知态 -> 操作 -> 等业务接口 -> 读 DOM 断言。

    按任务改写本函数体内的操作与断言。返回 (结果, 证据文件, 备注)；
    结果 ∈ 通过 / 失败 / 阻塞。
    """
    # 1) 回到已知态（清勾选/关弹窗，防脏状态传染）
    if case.get("url"):
        reset_to(page, case["url"], case.get("tab"))

    # 2) B6：操作前取响应基线
    base = watcher.snapshot()

    # 【按任务改】替换为真实标准操作（只做点击/键入/下拉，禁止 JS 注入改值）
    # page.get_by_role("button", name="查询").click()

    # 3) 等业务接口返回；无新响应 = 操作未生效，按失败处理
    new = watcher.wait_new(base, keyword=case.get("keyword"), timeout=15)
    if not new:
        ev = snap(page, f"{case['id']}_no_response", CONFIG["out_dir"], feature=CONFIG["feature"])
        return "失败", ev, "无新接口响应，操作未生效"

    # 4) 少量渲染余量后再读 DOM 断言
    page.wait_for_timeout(500)
    ok = True  # 【按任务改】替换为真实断言（以数据状态变化为准，toast 仅辅助）
    ev = snap(page, case["id"], CONFIG["out_dir"], feature=CONFIG["feature"])
    return ("通过" if ok else "失败"), ev, ""


def _teardown(launched, pw, browser, ctx, page):
    """收尾：自己起的会话就整体关闭；连接来的常驻浏览器只断开客户端。"""
    if launched:
        close_session(pw, browser, ctx, page)
        return
    try:
        if ctx is not None and page is not None:
            for p in list(ctx.pages):
                if p is not page:
                    p.close()
    except Exception:
        pass
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="web-blackbox-testing 总入口长脚本模板")
    ap.add_argument("--connect", action="store_true",
                    help="复用已启动的常驻浏览器（CDP），不新起会话")
    args = ap.parse_args()

    CONFIG["out_dir"].mkdir(parents=True, exist_ok=True)

    launched = not args.connect
    if args.connect:
        pw, browser, ctx, page = connect_session(cdp_url=f"http://127.0.0.1:{CONFIG['cdp_port']}")
    else:
        pw, browser, ctx, page = launch_session(headless=CONFIG["headless"], cdp_port=CONFIG["cdp_port"])

    results, problems, evidence = [], [], []
    try:
        # 一次登录：站点取 MES_URL，缺省取首个用例 url 的根地址
        first_url = next((c.get("url") for c in CASES if c.get("url")), "")
        login_for_page(page, CONFIG["base_url"] or first_url)

        watchers = attach_error_watchers(page)
        watcher = ApiWatcher(page)

        for case in CASES:
            try:
                result, ev, note = run_case(page, watcher, case)
            except Exception as exc:  # 用例间独立，单条失败不中断整段
                result, ev, note = "阻塞", "", f"异常：{exc}"
            results.append({"id": case["id"], "模块": case.get("模块", ""),
                            "结果": result, "证据": Path(ev).name if ev else ""})
            if ev:
                evidence.append(str(ev))
            if result != "通过":
                problems.append({"id": case["id"], "标题": note or "待补充", "级别": "待确认", "备注": ""})
            print(f"[{case['id']}] {result} {note}")

        # 三路错误监听（console / HTTP>=400 / 页面提示）汇总进报告
        errs = error_report(watchers)
        if errs:
            problems.append({"id": "ERR", "标题": "错误监听命中", "级别": "待确认", "备注": str(errs)[:500]})

        meta = {"功能": CONFIG["feature"], "环境": CONFIG["base_url"] or first_url}
        report = gen_report(meta, results, problems, uncovered=[], evidence=evidence)
        report_path = CONFIG["out_dir"] / "测试报告.md"
        report_path.write_text(report, encoding="utf-8")
        print(f"[run_all] 报告已生成：{report_path}")
    finally:
        _teardown(launched, pw, browser, ctx, page)


if __name__ == "__main__":
    main()
