# -*- coding: utf-8 -*-
"""一次会话常驻浏览器助手（web-blackbox-testing 配套）。

解决"每个脚本重新登录/导航"的重复开销：一次启动浏览器，一个长脚本跑完全部用例。
关键约定：
1. 一个会话只有一个持有者操作页面（启动后由同一脚本继续跑，或启动后立即让出、操作脚本只连接不并发）；
2. 优先复用已有页面（find_reuse_page），不重复多开标签页；
3. 会话结束显式 close（清理浏览器与标签页）。
"""
from __future__ import annotations

import time

from playwright.sync_api import sync_playwright


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


if __name__ == "__main__":
    print("session_helpers 可用：launch_session / connect_session / find_reuse_page / close_session / wait_until")
