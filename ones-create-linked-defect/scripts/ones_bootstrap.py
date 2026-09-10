# -*- coding: utf-8 -*-
"""ONES 首次使用一键引导：自检 → 提示/启动常驻浏览器（复制登录态 + CDP）。

默认 **dry-run**（只自检 + 打印将要执行的步骤，不改动本机状态）。

用法:
    python scripts/ones_bootstrap.py                     # 自检 + 打印步骤（不改动）
    python scripts/ones_bootstrap.py --apply             # 真正执行：后台启动常驻 Edge（headless）
    python scripts/ones_bootstrap.py --apply --visible   # 首次登录 / 飞书授权：可见窗口完成 SSO
    python scripts/ones_bootstrap.py --apply --url <ONES工单URL>

完成后：常驻浏览器在后台运行（CDP 端口见 config/settings.yaml），后续 ones_helpers.connect() 直接复用。
环境与全部变量的总表见 scripts/qa_skill_common/references/environment.md。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _port_in_use(port):
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _cdp_ready(port, timeout=60):
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(1.5)
    return False


def run_selfcheck():
    """跑一次 check_env，返回退出码。"""
    import check_env

    return check_env.main()


def main():
    ap = argparse.ArgumentParser(description="ONES 首次使用一键引导（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="真正执行：后台启动常驻 Edge")
    ap.add_argument("--visible", action="store_true", help="可见窗口启动（首次登录 / 飞书授权用）")
    ap.add_argument("--url", default=None, help="启动后打开的 ONES 地址（默认 ONES 首页）")
    args = ap.parse_args()

    from ones_config import resolve_settings

    settings = resolve_settings()
    port = settings["cdp_port"]
    server = SCRIPTS_DIR / "ones_edge_server.py"

    print("== 第 1 步：环境自检 ==")
    rc = run_selfcheck()
    if rc != 0 and not args.apply:
        print("\n存在 FAIL：请先按上面「修复指引」补齐，再执行引导。")
        return rc

    print("\n== 第 2 步：常驻浏览器 ==")
    if _port_in_use(port):
        print(f"  [SKIP] CDP {port} 已在运行，可直接复用（ones_helpers.connect()）。")
        print("\n完成。后续提缺陷命令示例：")
        print("  python scripts/ones_submit_defects.py --bug-report <清单.md> --work-order <工单URL> --profile <项目名>")
        return 0

    cmd = [sys.executable, str(server)]
    if args.visible:
        cmd.append("--visible")
    if args.url:
        cmd.append(args.url)

    if not args.apply:
        print("  当前为 dry-run（未改动本机）。将要执行：")
        print("   ", " ".join(cmd))
        print("  该命令会：复制本机 Edge 登录态 → 后台启动常驻 Edge → 等待 CDP 就绪。")
        print("\n确认后执行：")
        print("  python scripts/ones_bootstrap.py --apply            # 后台静默启动")
        print("  python scripts/ones_bootstrap.py --apply --visible  # 首次登录 / 飞书授权")
        return 0

    log_dir = Path(settings["logs_dir"])
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "bootstrap_edge.log"
    print(f"  启动中（日志：{log_path}）...")
    with open(log_path, "a", encoding="utf-8") as fh:
        subprocess.Popen(
            cmd, cwd=str(SCRIPTS_DIR), stdout=fh, stderr=fh,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )

    if _cdp_ready(port, timeout=60):
        print(f"  [OK] CDP {port} 已就绪。")
        print("\n完成。后续提缺陷命令示例：")
        print("  python scripts/ones_submit_defects.py --bug-report <清单.md> --work-order <工单URL> --profile <项目名>")
        if args.visible:
            print("\n提示：可见窗口下请完成飞书/ONES 登录授权；之后可改回默认（不带 --visible）静默运行。")
        return 0

    print(f"  [FAIL] CDP {port} 未就绪，请查看日志：{log_path}")
    print("  常见原因：Edge 登录态未就绪（首次加 --visible 完成 SSO）、端口被占用、Edge 路径未探测到。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
