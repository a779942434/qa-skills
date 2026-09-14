# -*- coding: utf-8 -*-
"""一次会话常驻浏览器助手（web-blackbox-testing 配套）。

解决"每个脚本重新登录/导航"的重复开销：一次启动浏览器，一个长脚本跑完全部用例。
关键约定：
1. 一个会话只有一个持有者操作页面（启动后由同一脚本继续跑，或启动后立即让出、操作脚本只连接不并发）；
2. 优先复用已有页面（find_reuse_page），不重复多开标签页；
3. 会话结束显式 close（清理浏览器与标签页）。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    from .bbt_helpers import _chrome_candidates
except ImportError:  # 兼容直接执行单文件
    from bbt_helpers import _chrome_candidates


def launch_session(headless: bool = True, cdp_port: int | None = None,
                   viewport: tuple = (1680, 950), locale: str = "zh-CN",
                   storage_state: str | None = None):
    """启动新 Chromium 会话（可选暴露 CDP 端口供后续连接）。

    返回 (pw, browser, ctx, page)；调用方负责在 finally 里 close。
    """
    args = ["--no-sandbox"]
    if cdp_port:
        args.append(f"--remote-debugging-port={cdp_port}")
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless, args=args)
    ctx = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        locale=locale,
        storage_state=storage_state,
    )
    page = ctx.new_page()
    return pw, browser, ctx, page


def connect_session(cdp_url: str = "http://127.0.0.1:9222",
                    url_contains: str | None = None):
    """连接常驻浏览器（CDP），优先复用匹配 url_contains 的已有页面。

    返回 (pw, browser, ctx, page)。
    """
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp_url, timeout=20000)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = find_reuse_page(ctx, url_contains=url_contains)
    if page is None:
        page = ctx.new_page()
    return pw, browser, ctx, page


def find_reuse_page(ctx, url_contains: str | None = None, title_contains: str | None = None):
    """在常驻浏览器上下文里查找已存在的页面，命中则复用。"""
    for p in ctx.pages:
        try:
            if url_contains and url_contains not in (p.url or ""):
                continue
            if title_contains and title_contains not in (p.title() or ""):
                continue
            return p
        except Exception:
            continue
    return None


def close_session(pw, browser=None, ctx=None, page=None):
    """收尾：关闭多余标签页并停掉 playwright（幂等，不抛异常）。"""
    try:
        if ctx is not None:
            for p in list(ctx.pages):
                try:
                    if page is not None and p is not page:
                        p.close()
                except Exception:
                    pass
        if browser is not None:
            browser.close()
    except Exception:
        pass
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass


def wait_until(obj, fn, timeout=30, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


@contextmanager
def session(base_url=None, target_url=None, headless=True, cdp_port=None,
            reuse_cdp=False, login=True):
    """一次会话上下文管理器：起/连浏览器 → 确保登录 → yield page → 收尾。

    用法：
        from session_helpers import session
        with session(base_url="http://<host>") as page:
            goto(page, url)

    - `reuse_cdp=True` 时连接常驻浏览器（收尾只断开客户端，不关浏览器）；
    - `login=True` 时自动 ensure_login（已登录会跳过，不重复登录）。
    """
    launched = True
    pw = browser = ctx = page = None
    try:
        if reuse_cdp:
            launched = False
            pw, browser, ctx, page = connect_session(cdp_url=f"http://127.0.0.1:{cdp_port or 9222}")
        else:
            pw, browser, ctx, page = launch_session(headless=headless, cdp_port=cdp_port)
        if login:
            from .bbt_osd_common import ensure_login
            ensure_login(page, target_url=target_url, base_url=base_url)
        yield page
    finally:
        if launched:
            close_session(pw, browser, ctx, page)
        else:
            try:
                if pw is not None:
                    pw.stop()
            except Exception:
                pass


if __name__ == "__main__":
    print("session_helpers 可用：launch_session / connect_session / find_reuse_page / close_session / wait_until")
    print("持久会话(2026-09-14)：start_persistent_session / connect_persistent_session / ensure_mes_session / stop_persistent_session")


# ---------------------------------------------------------------------------
# 持久化 MES 会话（2026-09-14）：固定用户数据目录 + 独立 CDP 端口，
# 以便长任务分阶段恢复时复用登录态，不与 ONES 的 9334 端口混用。
# ---------------------------------------------------------------------------

DEFAULT_MES_CDP_PORT = int(os.environ.get("MES_CDP_PORT", "9222"))


@dataclass
class PersistentSession:
    """持久浏览器进程句柄；started=False 表示复用了已有 CDP 会话。"""
    cdp_url: str
    session_dir: Path
    process: object | None = None
    started: bool = False
    pid: int | None = None
    managed: bool = False

    @property
    def alive(self) -> bool:
        return _cdp_ready(self.cdp_url, timeout=0.8)


def default_persistent_session_dir() -> Path:
    env = os.environ.get("MES_SESSION_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".codex" / "tmp" / "mes-web-session"


def _session_meta_path(session_dir: str | Path) -> Path:
    return Path(session_dir).expanduser() / "session.json"


def _read_session_meta(session_dir: str | Path) -> dict:
    path = _session_meta_path(session_dir)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_session_meta(session_dir: str | Path, *, cdp_url: str, pid: int | None) -> None:
    path = _session_meta_path(session_dir)
    path.write_text(json.dumps({
        "managed": True,
        "cdp_url": cdp_url,
        "pid": pid,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_session_meta(session_dir: str | Path) -> None:
    try:
        _session_meta_path(session_dir).unlink()
    except Exception:
        pass


def _terminate_pid(pid: int, timeout: float = 5.0) -> bool:
    """按 PID 终止本工具启动的持久浏览器（跨平台）。"""
    if not pid:
        return False
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           timeout=timeout, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def _cdp_ready(cdp_url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(cdp_url.rstrip("/") + "/json/version", timeout=timeout) as resp:
            return 200 <= int(resp.status) < 300
    except Exception:
        return False


def _browser_executable() -> str:
    env = os.environ.get("MES_BROWSER_PATH", "").strip()
    if env and Path(env).exists():
        return env
    candidates = _chrome_candidates()
    if not candidates:
        raise RuntimeError("未找到本机 Chrome/Edge；请设置 MES_BROWSER_PATH，且不要下载 Playwright 浏览器")
    return candidates[0]


def start_persistent_session(headless: bool = True, cdp_port: int | None = None,
                             session_dir: str | Path | None = None,
                             startup_timeout: float = 20.0) -> PersistentSession:
    """启动仓库外用户数据目录的持久 Chrome/Edge，并等待 CDP 就绪。

    若同端口已有会话则直接复用，不重复启动、不重复登录。
    """
    port = int(cdp_port or DEFAULT_MES_CDP_PORT)
    cdp_url = f"http://127.0.0.1:{port}"
    sess_dir = Path(session_dir).expanduser() if session_dir else default_persistent_session_dir()
    sess_dir.mkdir(parents=True, exist_ok=True)
    if _cdp_ready(cdp_url):
        meta = _read_session_meta(sess_dir)
        return PersistentSession(
            cdp_url=cdp_url, session_dir=sess_dir, started=False,
            pid=meta.get("pid"), managed=bool(meta.get("managed")),
        )

    exe = _browser_executable()
    args = [
        exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={sess_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
    ]
    if headless:
        args.append("--headless=new")
    log_path = sess_dir / "browser.log"
    log = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - 由子进程持有
    try:
        proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    except Exception:
        log.close()
        raise
    deadline = time.time() + max(float(startup_timeout), 1.0)
    while time.time() < deadline:
        if _cdp_ready(cdp_url):
            pid = getattr(proc, "pid", None)
            _write_session_meta(sess_dir, cdp_url=cdp_url, pid=pid)
            return PersistentSession(cdp_url=cdp_url, session_dir=sess_dir, process=proc,
                                     started=True, pid=pid, managed=True)
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    try:
        proc.terminate()
    except Exception:
        pass
    raise RuntimeError(f"持久浏览器启动失败，CDP 未就绪: {cdp_url}; 日志: {log_path}")


def connect_persistent_session(cdp_url: str = "http://127.0.0.1:9222",
                               url_contains: str | None = None):
    """连接持久浏览器；返回与 connect_session 相同的 (pw,browser,ctx,page)。"""
    return connect_session(cdp_url=cdp_url, url_contains=url_contains)


def ensure_mes_session(base_url: str | None = None, target_url: str | None = None,
                       headless: bool = True, cdp_port: int | None = None,
                       session_dir: str | Path | None = None,
                       login: bool = True):
    """确保 MES 持久会话可用并登录一次。

    返回 `(persistent, pw, browser, ctx, page)`。
    - 若 CDP 9222 已存活：复用现有会话，不重复启动；
    - 若不存在：启动持久浏览器；
    - login=True 时调用 ensure_login，已登录会直接跳过。
    """
    port = int(cdp_port or DEFAULT_MES_CDP_PORT)
    cdp_url = f"http://127.0.0.1:{port}"
    persistent = start_persistent_session(
        headless=headless, cdp_port=port, session_dir=session_dir,
    )
    pw, browser, ctx, page = connect_persistent_session(cdp_url, url_contains=None)
    if login:
        from .bbt_osd_common import ensure_login
        ensure_login(page, target_url=target_url, base_url=base_url)
    return persistent, pw, browser, ctx, page


def stop_persistent_session(persistent: PersistentSession | None, timeout: float = 5.0) -> bool:
    """关闭本工具管理的持久浏览器；外部/非受管浏览器不会被误杀。"""
    if not persistent or not persistent.managed:
        return False
    proc = persistent.process
    stopped = False
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
            stopped = True
        except Exception:
            try:
                proc.kill()
                stopped = True
            except Exception:
                pass
    elif persistent.pid:
        stopped = _terminate_pid(persistent.pid, timeout=timeout)
    if stopped:
        _remove_session_meta(persistent.session_dir)
    return stopped
