# -*- coding: utf-8 -*-
"""使用前自检：一键检查 ONES 技能运行环境是否就绪。

用法: python scripts/check_env.py

公共检查项（依赖等）复用 qa_skill_common.env_check；以下是 ONES 专属项。

检查项:
    1. Python / Playwright / PyYAML（公共）
    2. Edge 可执行文件
    3. 本机 Edge 登录态源
    4. 会话目录状态（已就绪 / 需运行 ones_bootstrap.py）
    5. CDP 端口可用性（常驻浏览器是否已启动）
    6. 配置文件可解析
    7. bug-reports 缺陷清单目录（警告级别）

退出码：存在 FAIL 返回 1，否则返回 0。
环境与全部变量的总表见 scripts/qa_skill_common/references/environment.md。
"""
import socket
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qa_skill_common import env_check as ec  # noqa: E402
from ones_config import load_field_mapping, resolve_settings  # noqa: E402


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    results = []

    # 1. 依赖（公共）
    results += ec.check_deps()

    # 2. 配置
    try:
        settings = resolve_settings()
        field_map = load_field_mapping()
        results.append(ec.ok("配置文件可解析"))
    except Exception as exc:  # noqa: BLE001
        settings = None
        field_map = {}
        results.append(ec.fail("配置文件可解析", str(exc)[:120]))

    if settings:
        # 3. Edge / 登录态源
        edge_exe = settings["edge"]["executable"]
        results.append(
            ec.ok("Edge 可执行文件", str(edge_exe))
            if edge_exe and Path(edge_exe).exists()
            else ec.fail("Edge 可执行文件", str(edge_exe or "未探测到"), "安装 Edge 或设置 ONES_EDGE_EXE")
        )

        src = settings["edge"]["user_data_source"]
        src_ok = bool(src) and Path(src).exists() and any(
            p.exists()
            for p in (Path(src) / "Default" / "Network" / "Cookies", Path(src) / "Default" / "Cookies")
        )
        results.append(
            ec.ok("本机 Edge 登录态源", str(src))
            if src_ok
            else ec.warn("本机 Edge 登录态源", str(src or "未探测到"), "确认本机 Edge 已登录过 ONES / 飞书")
        )

        session_dir = Path(settings["edge"]["session_dir"])
        session_ok = any(
            p.exists()
            for p in (session_dir / "Default" / "Network" / "Cookies", session_dir / "Default" / "Cookies")
        )
        results.append(
            ec.ok("会话目录已就绪", str(session_dir))
            if session_ok
            else ec.warn("会话目录已就绪", str(session_dir), "运行 python scripts/ones_bootstrap.py --apply")
        )

        # 4. CDP 端口
        port = settings["cdp_port"]
        results.append(
            ec.ok(f"CDP {port} 已就绪", "常驻浏览器运行中")
            if port_open(port)
            else ec.warn(f"CDP {port} 已就绪", "未启动", "运行 python scripts/ones_bootstrap.py --apply")
        )

        # 5. 缺陷清单目录
        bug_dir = Path(settings["bug_reports_dir"])
        results.append(
            ec.ok("缺陷清单目录存在", str(bug_dir))
            if bug_dir.exists()
            else ec.warn("缺陷清单目录存在", str(bug_dir), "可由 web-blackbox-testing 产出，或设 ONES_BUG_REPORTS_DIR")
        )

    # 6. 字段映射关键项
    if field_map:
        missing = [k for k in ("priority",) if not field_map.get(k)]
        results.append(
            ec.ok("字段映射关键项", "P2 已配置；处理人/负责人动态取自主工单与登录账号")
            if not missing
            else ec.fail("字段映射关键项", "缺: " + ", ".join(missing))
        )

    return ec.report("ONES skill 环境自检", results)


if __name__ == "__main__":
    sys.exit(main())
