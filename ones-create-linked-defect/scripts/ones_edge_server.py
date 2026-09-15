# -*- coding: utf-8 -*-
"""常驻 ONES Edge 监管器：CDP 健康检查、意外退出自动重启、单实例保护。

用法:
    python ones_edge_server.py [url] [--visible]
    python ones_edge_server.py [url] --max-restarts 5 --health-interval 5

职责:
    1. 检查与本机 Edge 登录态隔离的专用会话目录；
    2. 通过系统 Edge 启动独立 CDP 进程，不与其他 Edge profile 共用目录；
    3. 周期检查 `/json/version` + `/json/list`；发现假死或进程退出后自动重启；
    4. 重启复用同一 session_dir 和登录态，并恢复 ONES 页面；
    5. 通过 server.json 防止多个监管器同时重启同一实例。

其他脚本统一通过 ones_helpers.connect() 连接，不单独关闭或重启 Edge。
"""
import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from edge_session_setup import ensure_session
from ones_config import resolve_settings
from qa_skill_common.session_helpers import (
    cdp_health,
    connect_session,
    restart_persistent_session,
    start_persistent_session,
    stop_persistent_session,
    wait_cdp_healthy,
)

LOG = logging.getLogger("ones_edge_server")


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def cdp_ready(port, timeout=30):
    """兼容旧调用：等待 CDP 健康，不只看端口是否监听。"""
    return wait_cdp_healthy(f"http://127.0.0.1:{int(port)}", timeout=timeout).ok


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


def _server_meta_path(settings):
    return Path(settings["logs_dir"]) / "ones_edge_server.json"


def _read_server_meta(settings):
    try:
        return json.loads(_server_meta_path(settings).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_server_meta(settings, *, pid=None, state="running", error=""):
    path = _server_meta_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": int(pid if pid is not None else os.getpid()),
        "state": state,
        "cdp_port": int(settings["cdp_port"]),
        "updated_at": time.time(),
        "error": str(error or "")[:300],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _open_ones_page(url, timeout=45000):
    """通过 CDP 打开/恢复 ONES 页面，随后只断开 Playwright 客户端。"""
    settings = resolve_settings()
    cdp_url = f"http://127.0.0.1:{settings['cdp_port']}"
    pw, _browser, _ctx, page = connect_session(cdp_url, url_contains=None)
    try:
        target = url or settings["ones_url"]
        if target:
            page.goto(target, wait_until="domcontentloaded", timeout=timeout)
        return page.url
    finally:
        try:
            pw.stop()
        except Exception:
            pass


def ensure_server_process(url=None, visible=False, startup_timeout=60, recovery_timeout=45):
    """确保后台监管器存在并返回 (started, healthy, meta)。

    已有健康 CDP 时直接复用；监管器存活但 Edge 正在自恢复时只等待，不重复拉起实例。
    """
    settings = resolve_settings()
    port = int(settings["cdp_port"])
    health = cdp_health(f"http://127.0.0.1:{port}", timeout=1.0)
    meta = _read_server_meta(settings)
    other_pid = int(meta.get("pid") or 0)
    if other_pid and other_pid != os.getpid() and _pid_alive(other_pid):
        if health.ok:
            return False, True, meta
        recovered = wait_cdp_healthy(f"http://127.0.0.1:{port}", timeout=recovery_timeout)
        return False, recovered.ok, _read_server_meta(settings)

    cmd = [sys.executable, str(Path(__file__).resolve())]
    if url:
        cmd.append(url)
    if visible:
        cmd.append("--visible")
    log_path = Path(settings["logs_dir"]) / "bootstrap_edge.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).resolve().parent),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    _write_server_meta(settings, pid=proc.pid, state="starting")
    recovered = wait_cdp_healthy(
        f"http://127.0.0.1:{port}", timeout=max(float(startup_timeout), 1.0),
    )
    return True, recovered.ok, _read_server_meta(settings)


def _launch_managed_edge(url, visible=False, startup_timeout=60):
    settings = resolve_settings()
    ensure_session()
    edge_exe = settings["edge"]["executable"]
    if not edge_exe or not Path(edge_exe).exists():
        raise RuntimeError(f"未找到 Edge 可执行文件：{edge_exe}")
    headless = bool(settings["edge"].get("headless", True)) and not visible
    persistent = start_persistent_session(
        headless=headless,
        cdp_port=settings["cdp_port"],
        session_dir=settings["edge"]["session_dir"],
        startup_timeout=startup_timeout,
        browser_path=edge_exe,
        extra_args=("--remote-allow-origins=*",),
    )
    if persistent.started:
        _open_ones_page(url or settings["ones_url"])
    return persistent


def serve(url=None, visible=False, health_interval=5.0,
          max_restarts=3, startup_timeout=60):
    """启动并监管 Edge；返回 0 表示已有其他监管器接管或达到正常退出。"""
    settings = resolve_settings()
    port = int(settings["cdp_port"])
    cdp_url = f"http://127.0.0.1:{port}"
    persistent = _launch_managed_edge(url, visible=visible, startup_timeout=startup_timeout)
    if not persistent.started:
        server_meta = _read_server_meta(settings)
        other_pid = int(server_meta.get("pid") or 0)
        if other_pid and other_pid != os.getpid() and _pid_alive(other_pid):
            LOG.info("已有监管器 PID %s 在运行，当前进程退出以避免重复监管", other_pid)
            return 0
        if not persistent.managed:
            LOG.info("监听已有非受管 CDP 实例；不主动终止它，若其意外退出则拉起受管实例")
        else:
            LOG.info("接管已有受管 CDP 实例，开始健康检查与自动重启")

    _write_server_meta(settings, pid=os.getpid(), state="running")
    LOG.info("READY %s", cdp_url)
    LOG.info("TITLE %s", url or settings["ones_url"])
    recoveries = int(persistent.recoveries_this_run or 0)
    try:
        while True:
            time.sleep(max(float(health_interval), 1.0))
            health = cdp_health(cdp_url, timeout=1.5)
            if health.ok:
                continue
            LOG.error("CDP 健康检查失败: %s", health.error or "unknown")
            if max_restarts > 0 and recoveries >= max_restarts:
                LOG.error("已达到最大重启次数 %s，停止监管", max_restarts)
                return 1
            recoveries += 1
            LOG.warning("重启 Edge 实例（第 %s 次）...", recoveries)
            try:
                persistent = restart_persistent_session(
                    persistent,
                    headless=bool(settings["edge"].get("headless", True)) and not visible,
                    cdp_port=port,
                    session_dir=settings["edge"]["session_dir"],
                    startup_timeout=startup_timeout,
                    browser_path=settings["edge"]["executable"],
                    extra_args=("--remote-allow-origins=*",),
                    reason=health.error,
                )
            except Exception as exc:  # noqa: BLE001
                LOG.exception("Edge 自动重启失败: %s", exc)
                _write_server_meta(settings, pid=os.getpid(), state="recovering", error=str(exc))
                time.sleep(min(max(float(health_interval) * 2, 2.0), 30.0))
                continue
            persistent.recoveries_this_run = recoveries
            _open_ones_page(url or settings["ones_url"])
            _write_server_meta(settings, pid=os.getpid(), state="running")
            LOG.info("RECOVERED %s (%s)", cdp_url, recoveries)
    except KeyboardInterrupt:
        LOG.info("收到中断，关闭本次受管 Edge")
        return 0
    finally:
        stop_persistent_session(persistent)
        meta = _read_server_meta(settings)
        if int(meta.get("pid") or 0) == os.getpid():
            try:
                _server_meta_path(settings).unlink()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="启动并监管常驻 ONES Edge（CDP）")
    parser.add_argument("url", nargs="?", default=None, help="启动后打开的 URL（默认 ONES 首页）")
    parser.add_argument("--visible", action="store_true", help="以可见窗口启动（首次登录/飞书授权时用）")
    parser.add_argument("--health-interval", type=float, default=5.0, help="健康检查间隔秒数")
    parser.add_argument("--max-restarts", type=int, default=3, help="最大自动重启次数；0 表示无限")
    parser.add_argument("--startup-timeout", type=float, default=60.0, help="单次启动等待秒数")
    args = parser.parse_args()

    settings = resolve_settings()
    setup_logging(settings["logs_dir"])
    LOG.info("配置: port=%s url=%s", settings["cdp_port"], args.url or settings["ones_url"])
    LOG.info("Edge: %s", settings["edge"]["executable"])
    LOG.info("会话目录: %s", settings["edge"]["session_dir"])
    try:
        return serve(
            url=args.url,
            visible=args.visible,
            health_interval=args.health_interval,
            max_restarts=args.max_restarts,
            startup_timeout=args.startup_timeout,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.exception("ONES Edge 监管器启动失败: %s", exc)
        _write_server_meta(settings, state="failed", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
