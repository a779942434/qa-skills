# -*- coding: utf-8 -*-
"""常驻 ONES 浏览器：准备登录态并启动 Edge（CDP 端口可配置，默认 9334）。

用法: python ones_edge_server.py [url] [--visible]

后台启动（Windows: Start-Process；macOS: nohup ... &），浏览器窗口保持可见；
其他脚本通过 ones_helpers.connect() 复用。

启动前自动：
    1. 检查 CDP 端口是否已被占用（已占用则提示复用现有实例）；
    2. 调用 edge_session_setup.ensure_session() 准备登录态；
    3. 启动后轮询 CDP 就绪，输出 READY / TITLE。

日志写入 <logs_dir>/ones_edge_server.log（同时输出到控制台）。
"""
import argparse
import logging
import socket
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

from edge_session_setup import ensure_session
from ones_config import resolve_settings

LOG = logging.getLogger("ones_edge_server")


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def cdp_ready(port, timeout=30):
    """轮询 CDP /json/version 直到可访问，返回 TITLE 所在页面 URL（或 None）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def setup_logging(logs_dir):
    Path(logs_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(Path(logs_dir) / "ones_edge_server.log", encoding="utf-8"),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="启动常驻 ONES 浏览器（CDP 9334）")
    parser.add_argument("url", nargs="?", default=None, help="启动后打开的 URL（默认 ONES 首页）")
    parser.add_argument("--visible", action="store_true", help="以可见窗口启动（首次登录/飞书授权时用；默认后台静默）")
    args = parser.parse_args()

    settings = resolve_settings()
    port = settings["cdp_port"]
    url = args.url or settings["ones_url"]

    setup_logging(settings["logs_dir"])
    LOG.info("配置: port=%s url=%s", port, url)
    LOG.info("Edge: %s", settings["edge"]["executable"])
    LOG.info("会话目录: %s", settings["edge"]["session_dir"])

    if port_in_use(port):
        LOG.error("端口 %s 已被占用，可能已有常驻浏览器实例；直接复用（ones_helpers.connect()）或先关闭旧实例。", port)
        raise SystemExit(1)

    ensure_session()

    edge_exe = settings["edge"]["executable"]
    if not edge_exe or not Path(edge_exe).exists():
        LOG.error("未找到 Edge 可执行文件：%s", edge_exe)
        raise SystemExit(1)

    headless = settings["edge"].get("headless", True)
    if args.visible:
        headless = False
    LOG.info("启动 Edge（headless=%s，慢速操作）...", headless)
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=settings["edge"]["session_dir"],
        executable_path=edge_exe,
        headless=headless,
        slow_mo=80,
        viewport={"width": 1680, "height": 950},
        args=[
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )

    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(15000)

    if not cdp_ready(port):
        LOG.warning("CDP 端口探测超时，请确认浏览器已启动")

    LOG.info("READY %s", page.url)
    LOG.info("TITLE %s", page.title())

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        pw.stop()


if __name__ == "__main__":
    main()
