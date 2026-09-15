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
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    from .bbt_helpers import _chrome_candidates, configure_page_timeouts
except ImportError:  # 兼容直接执行单文件
    from bbt_helpers import _chrome_candidates, configure_page_timeouts


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
    configure_page_timeouts(page)
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
    configure_page_timeouts(page)
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
    print("持久会话：start_persistent_session / connect_persistent_session / ensure_mes_session / restart_persistent_session / stop_persistent_session")
    print("健康恢复：cdp_health / wait_cdp_healthy（/json/version + /json/list）")


# ---------------------------------------------------------------------------
# 持久化 MES 会话（2026-09-14）：固定用户数据目录 + 独立 CDP 端口，
# 以便长任务分阶段恢复时复用登录态，不与 ONES 的 9334 端口混用。
# ---------------------------------------------------------------------------

DEFAULT_MES_CDP_PORT = int(os.environ.get("MES_CDP_PORT", "9222"))

# 专用持久浏览器统一参数：隔离扩展/GPU/后台节流，并抑制崩溃恢复气泡。
# 这些参数用于降低长时间运行时的崩溃概率和误弹“浏览器意外退出/恢复页面”窗口。
PERSISTENT_BROWSER_ARGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-backgrounding-occluded-windows",
    "--disable-session-crashed-bubble",
    "--hide-crash-restore-bubble",
    "--disable-crash-reporter",
    "--disable-breakpad",
    "--noerrdialogs",
)


@dataclass
class CdpHealth:
    """CDP 健康检查结果；ok=False 时 error 给出可记录的失败原因。"""
    ok: bool
    cdp_url: str
    browser: str = ""
    websocket_url: str = ""
    target_count: int = 0
    error: str = ""
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "cdp_url": self.cdp_url,
            "browser": self.browser,
            "websocket_url": self.websocket_url,
            "target_count": self.target_count,
            "error": self.error,
            "checked_at": self.checked_at,
        }


@dataclass
class PersistentSession:
    """持久浏览器进程句柄；started=False 表示复用了已有 CDP 会话。"""
    cdp_url: str
    session_dir: Path
    process: object | None = None
    started: bool = False
    pid: int | None = None
    managed: bool = False
    restarts: int = 0
    recoveries_this_run: int = 0
    last_health_error: str = ""

    @property
    def alive(self) -> bool:
        return cdp_health(self.cdp_url, timeout=0.8).ok


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


def _write_session_meta(session_dir: str | Path, *, cdp_url: str, pid: int | None,
                        **extra) -> None:
    path = _session_meta_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "managed": True,
        "cdp_url": cdp_url,
        "pid": pid,
        "updated_at": time.time(),
    }
    payload.update(extra)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False


def cdp_health(cdp_url: str, timeout: float = 1.0) -> CdpHealth:
    """检查 CDP 是否可访问且能返回浏览器/页面列表。

    仅看端口是否打开会把“假死但仍占用端口”的浏览器判为可用；这里同时校验
    `/json/version` 和 `/json/list`，供启动恢复和长任务监控复用。
    """
    base = cdp_url.rstrip("/")
    checked_at = time.time()
    try:
        with urllib.request.urlopen(base + "/json/version", timeout=timeout) as resp:
            if not (200 <= int(resp.status) < 300):
                return CdpHealth(False, cdp_url, error=f"version HTTP {resp.status}", checked_at=checked_at)
            version = json.loads(resp.read().decode("utf-8") or "{}")
        with urllib.request.urlopen(base + "/json/list", timeout=timeout) as resp:
            if not (200 <= int(resp.status) < 300):
                return CdpHealth(False, cdp_url, error=f"list HTTP {resp.status}", checked_at=checked_at)
            targets = json.loads(resp.read().decode("utf-8") or "[]")
        browser = str(version.get("Browser") or "")
        ws_url = str(version.get("webSocketDebuggerUrl") or "")
        if not browser and not ws_url:
            return CdpHealth(False, cdp_url, error="CDP version 响应缺少浏览器标识", checked_at=checked_at)
        return CdpHealth(
            True, cdp_url, browser=browser, websocket_url=ws_url,
            target_count=len(targets) if isinstance(targets, list) else 0,
            checked_at=checked_at,
        )
    except Exception as exc:
        return CdpHealth(False, cdp_url, error=str(exc)[:300], checked_at=checked_at)


def _cdp_ready(cdp_url: str, timeout: float = 1.0) -> bool:
    """兼容旧调用：只返回健康布尔值。"""
    return cdp_health(cdp_url, timeout=timeout).ok


def wait_cdp_healthy(cdp_url: str, timeout: float = 20.0, interval: float = 0.25) -> CdpHealth:
    """等待 CDP 达到健康状态，超时返回最后一次健康详情。"""
    deadline = time.time() + max(float(timeout), 0.1)
    last = cdp_health(cdp_url, timeout=min(1.0, max(float(timeout), 0.1)))
    while not last.ok and time.time() < deadline:
        time.sleep(max(float(interval), 0.05))
        last = cdp_health(cdp_url, timeout=min(1.0, max(deadline - time.time(), 0.1)))
    return last


def _browser_executable(browser_path: str | None = None) -> str:
    if browser_path and Path(browser_path).exists():
        return str(Path(browser_path).expanduser())
    env = os.environ.get("MES_BROWSER_PATH", "").strip()
    if env and Path(env).exists():
        return env
    candidates = _chrome_candidates()
    if not candidates:
        raise RuntimeError("未找到本机 Chrome/Edge；请设置 MES_BROWSER_PATH，且不要下载 Playwright 浏览器")
    return candidates[0]


def persistent_browser_args(port: int, session_dir: str | Path, headless: bool = True,
                            extra_args: tuple[str, ...] | list[str] | None = None) -> list[str]:
    """生成专用持久浏览器启动参数；ONES/MES 共用同一套抗崩溃与防恢复气泡配置。"""
    args = [
        f"--remote-debugging-port={int(port)}",
        f"--user-data-dir={Path(session_dir).expanduser()}",
        *PERSISTENT_BROWSER_ARGS,
    ]
    if headless:
        args.append("--headless=new")
    args.extend(str(arg) for arg in (extra_args or ()) if str(arg))
    return args


def _stop_recorded_unhealthy_session(session_dir: str | Path, cdp_url: str,
                                     timeout: float = 5.0) -> bool:
    """回收上次由本工具启动、但当前 CDP 已不健康的浏览器进程。

    只终止 session.json 中标记 managed 的 PID；没有受管元数据时绝不猜测或误杀外部浏览器。
    """
    meta = _read_session_meta(session_dir)
    if not meta.get("managed") or not meta.get("pid"):
        return False
    stopped = _terminate_pid(int(meta["pid"]), timeout=timeout)
    deadline = time.time() + max(float(timeout), 0.5)
    while cdp_health(cdp_url, timeout=0.4).ok and time.time() < deadline:
        time.sleep(0.2)
    return stopped


def start_persistent_session(headless: bool = True, cdp_port: int | None = None,
                             session_dir: str | Path | None = None,
                             startup_timeout: float = 20.0,
                             browser_path: str | None = None,
                             extra_args: tuple[str, ...] | list[str] | None = None,
                             recover_stale: bool = True) -> PersistentSession:
    """启动仓库外用户数据目录的持久 Chrome/Edge，并等待 CDP 就绪。

    若同端口已有会话则直接复用，不重复启动、不重复登录。
    """
    port = int(cdp_port or DEFAULT_MES_CDP_PORT)
    cdp_url = f"http://127.0.0.1:{port}"
    sess_dir = Path(session_dir).expanduser() if session_dir else default_persistent_session_dir()
    sess_dir.mkdir(parents=True, exist_ok=True)
    health = cdp_health(cdp_url, timeout=1.0)
    if health.ok:
        meta = _read_session_meta(sess_dir)
        return PersistentSession(
            cdp_url=cdp_url, session_dir=sess_dir, started=False,
            pid=meta.get("pid"), managed=bool(meta.get("managed")),
            restarts=int(meta.get("restarts") or 0),
        )
    if _port_open(port):
        if not recover_stale:
            raise RuntimeError(f"CDP 端口 {port} 已占用但健康检查失败: {health.error}")
        if _stop_recorded_unhealthy_session(sess_dir, cdp_url, timeout=5.0):
            deadline = time.time() + 5.0
            while _port_open(port) and time.time() < deadline:
                time.sleep(0.2)
        if _port_open(port):
            raise RuntimeError(
                f"CDP 端口 {port} 已占用且不是本工具可回收的受管实例；"
                f"健康检查失败: {health.error}"
            )

    exe = _browser_executable(browser_path)
    args = [
        exe,
        *persistent_browser_args(port, sess_dir, headless=headless, extra_args=extra_args),
    ]
    log_path = sess_dir / "browser.log"
    log = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - 由子进程持有
    try:
        proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    except Exception:
        log.close()
        raise
    log.close()
    deadline = time.time() + max(float(startup_timeout), 1.0)
    while time.time() < deadline:
        health = cdp_health(cdp_url, timeout=0.8)
        if health.ok:
            pid = getattr(proc, "pid", None)
            old_meta = _read_session_meta(sess_dir)
            _write_session_meta(
                sess_dir, cdp_url=cdp_url, pid=pid,
                started_at=time.time(), restarts=int(old_meta.get("restarts") or 0),
                browser=health.browser, user_data_dir=str(sess_dir),
            )
            return PersistentSession(cdp_url=cdp_url, session_dir=sess_dir, process=proc,
                                     started=True, pid=pid, managed=True,
                                     restarts=int(old_meta.get("restarts") or 0))
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    try:
        proc.terminate()
    except Exception:
        pass
    raise RuntimeError(
        f"持久浏览器启动失败，CDP 未就绪: {cdp_url}; "
        f"最后健康状态: {health.error or 'unknown'}; 日志: {log_path}"
    )


def connect_persistent_session(cdp_url: str = "http://127.0.0.1:9222",
                               url_contains: str | None = None):
    """连接持久浏览器；返回与 connect_session 相同的 (pw,browser,ctx,page)。"""
    return connect_session(cdp_url=cdp_url, url_contains=url_contains)


def restart_persistent_session(persistent: PersistentSession | None = None, *,
                               headless: bool = True,
                               cdp_port: int | None = None,
                               session_dir: str | Path | None = None,
                               startup_timeout: float = 20.0,
                               browser_path: str | None = None,
                               extra_args: tuple[str, ...] | list[str] | None = None,
                               reason: str = "") -> PersistentSession:
    """关闭受管持久浏览器并启动新实例；保留同一 session_dir 以复用登录态。"""
    port = int(cdp_port or DEFAULT_MES_CDP_PORT)
    sess_dir = (
        Path(session_dir).expanduser() if session_dir
        else persistent.session_dir if persistent
        else default_persistent_session_dir()
    )
    cdp_url = f"http://127.0.0.1:{port}"
    previous_restarts = int(persistent.restarts if persistent else 0)
    stop_persistent_session(persistent, timeout=5.0)
    deadline = time.time() + 5.0
    while _port_open(port) and time.time() < deadline:
        time.sleep(0.2)
    if _port_open(port):
        raise RuntimeError(f"无法重启持久浏览器：CDP 端口 {port} 仍被占用")

    restarted = start_persistent_session(
        headless=headless,
        cdp_port=port,
        session_dir=sess_dir,
        startup_timeout=startup_timeout,
        browser_path=browser_path,
        extra_args=extra_args,
        recover_stale=True,
    )
    restarted.restarts = previous_restarts + 1
    restarted.recoveries_this_run = int(
        (persistent.recoveries_this_run if persistent else 0)
    ) + 1
    restarted.last_health_error = str(reason or "")[:300]
    _write_session_meta(
        sess_dir,
        cdp_url=cdp_url,
        pid=restarted.pid,
        started_at=time.time(),
        restarts=restarted.restarts,
        last_restart_reason=restarted.last_health_error,
        browser=cdp_health(cdp_url, timeout=1.0).browser,
        user_data_dir=str(sess_dir),
    )
    return restarted


def _is_browser_connection_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "connect_over_cdp", "cdp", "websocket", "connection closed", "connection reset",
        "target page, context or browser has been closed", "browser has been closed",
        "econnrefused", "connection refused", "socket hang up",
    )
    return any(marker in text for marker in markers)


def ensure_mes_session(base_url: str | None = None, target_url: str | None = None,
                       headless: bool = True, cdp_port: int | None = None,
                       session_dir: str | Path | None = None,
                       login: bool = True, auto_restart: bool = True,
                       restart_attempts: int = 2):
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
    attempts = max(int(restart_attempts), 0) + 1 if auto_restart else 1
    last_error: BaseException | None = None
    for attempt in range(attempts):
        pw = browser = ctx = page = None
        try:
            pw, browser, ctx, page = connect_persistent_session(cdp_url, url_contains=None)
            if login:
                from .bbt_osd_common import ensure_login
                ensure_login(page, target_url=target_url, base_url=base_url)
            return persistent, pw, browser, ctx, page
        except Exception as exc:
            last_error = exc
            try:
                if pw is not None:
                    pw.stop()
            except Exception:
                pass
            if attempt >= attempts - 1 or not _is_browser_connection_error(exc):
                raise
            health = cdp_health(cdp_url, timeout=1.0)
            persistent = restart_persistent_session(
                persistent,
                headless=headless,
                cdp_port=port,
                session_dir=session_dir,
                reason=f"连接恢复失败: {health.error or exc}",
            )
    raise RuntimeError(f"MES 持久会话恢复失败: {last_error}")


def stop_persistent_session(persistent: PersistentSession | None, timeout: float = 5.0) -> bool:
    """关闭本工具管理的持久浏览器；外部/非受管浏览器不会被误杀。"""
    if not persistent or not persistent.managed:
        return False
    proc = persistent.process
    stopped = False
    if proc is not None:
        try:
            if proc.poll() is not None:
                stopped = True
            else:
                proc.terminate()
                proc.wait(timeout=timeout)
                stopped = True
        except Exception:
            try:
                if proc.poll() is None:
                    proc.kill()
                stopped = True
            except Exception:
                if proc.poll() is not None:
                    stopped = True
    elif persistent.pid:
        stopped = _terminate_pid(persistent.pid, timeout=timeout)
    if stopped or not persistent.alive:
        _remove_session_meta(persistent.session_dir)
    return stopped
