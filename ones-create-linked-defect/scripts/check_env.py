# -*- coding: utf-8 -*-
"""使用前自检：一键检查 skill 运行环境是否就绪。

用法: python scripts/check_env.py

检查项:
    1. Python / Playwright / PyYAML
    2. Edge 可执行文件
    3. 本机 Edge 登录态源目录
    4. 会话目录状态（已就绪 / 需运行 edge_session_setup.py）
    5. CDP 端口可用性（常驻浏览器是否已启动）
    6. 配置文件可解析
    7. bug-reports 缺陷清单目录（警告级别）

退出码：存在 FAIL 返回 1，否则返回 0。
"""
import socket
import sys
from pathlib import Path

from ones_config import CONFIG_DIR, load_field_mapping, resolve_settings

RESULTS = []


def check(name, ok, detail="", warn=False):
    RESULTS.append((name, ok, detail, warn))
    tag = "WARN" if (not ok and warn) else ("PASS" if ok else "FAIL")
    suffix = f"  [{detail}]" if detail else ""
    print(f"  [{tag}] {name}{suffix}")


def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main():
    print("== ONES skill 环境自检 ==")

    # 1. 依赖
    deps_ok = True
    for mod in ("playwright", "yaml"):
        try:
            __import__(mod)
            check(f"依赖 {mod}", True)
        except ImportError:
            deps_ok = False
            check(f"依赖 {mod}", False, "pip install " + ("playwright" if mod == "playwright" else "pyyaml"))

    # 2. 配置
    try:
        settings = resolve_settings()
        field_map = load_field_mapping()
        check("配置文件可解析", True)
    except Exception as exc:
        settings = None
        field_map = {}
        check("配置文件可解析", False, str(exc))

    # 3. Edge / 登录态源
    if settings:
        edge_exe = settings["edge"]["executable"]
        check("Edge 可执行文件", bool(edge_exe) and Path(edge_exe).exists(), edge_exe or "未探测到")

        src = settings["edge"]["user_data_source"]
        src_ok = bool(src) and Path(src).exists() and any(
            p.exists()
            for p in (
                Path(src) / "Default" / "Network" / "Cookies",
                Path(src) / "Default" / "Cookies",
            )
        )
        check("本机 Edge 登录态源", src_ok, src or "未探测到", warn=True)

        session_dir = Path(settings["edge"]["session_dir"])
        session_ok = any(
            p.exists()
            for p in (
                session_dir / "Default" / "Network" / "Cookies",
                session_dir / "Default" / "Cookies",
            )
        )
        check("会话目录已就绪", session_ok, str(session_dir), warn=True)

        # 4. CDP 端口
        port = settings["cdp_port"]
        if port_open(port):
            check(f"CDP {port} 已就绪", True, "常驻浏览器运行中")
        else:
            check(f"CDP {port} 已就绪", False, "未启动；运行 python scripts/ones_edge_server.py", warn=True)

        # 5. 缺陷清单目录
        bug_dir = Path(settings["bug_reports_dir"])
        check("缺陷清单目录存在", bug_dir.exists(), str(bug_dir), warn=True)

    # 6. 字段映射关键项
    if field_map:
        missing = [k for k in ("priority",) if not field_map.get(k)]
        check("字段映射关键项", not missing, "缺: " + ", ".join(missing) if missing else "P2 已配置；处理人/负责人动态取自主工单与登录账号")

    print("==")
    fails = [r for r in RESULTS if not r[1] and not r[3]]
    warns = [r for r in RESULTS if not r[1] and r[3]]
    print(f"结果: {len(RESULTS) - len(fails) - len(warns)} PASS, {len(warns)} WARN, {len(fails)} FAIL")
    if fails:
        print("请先解决 FAIL 项再执行任务。")
        return 1
    if warns:
        print("WARN 项不阻塞，但注意按提示处理。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
