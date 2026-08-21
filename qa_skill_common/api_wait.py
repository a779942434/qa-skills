# -*- coding: utf-8 -*-
"""接口观测等待工具（web-blackbox-testing 配套）。

核心思想：页面数据是接口返回后渲染的。不要在操作后直接固定 sleep 或立即读 DOM，
而是观测页面实际发出的接口，等到"操作触发的业务接口返回"后再断言页面数据。

用法（每个业务不同，无需预知接口路径）：

    from api_wait import ApiWatcher
    watcher = ApiWatcher(page)          # 挂 response 监听（覆盖所有 frame）
    base = watcher.snapshot()           # 操作前记录响应基线

    click_action(...)                   # 触发操作（切页签/提交/刷卡）

    new = watcher.wait_new(base, timeout=15)   # 等出现基线后的新响应
    # new 非空 = 业务接口已返回；此时再读页面 DOM，通常已渲染
    page.wait_for_timeout(500)          # 留少量渲染余量（可选）

可选：wait_new(keyword="plan") 按 URL 关键词过滤（适用于能判断业务前缀的场景，
如列表接口含 /plan/、提交接口含 /switch/ 等；不确定时不传，等任意新响应）。
"""
import time
__all__ = ["ApiWatcher", "wait_any_api"]



class ApiWatcher:
    """监听页面所有 response（含 iframe），记录响应供基线对比与等待。"""

    def __init__(self, page, url_filter=None):
        self.page = page
        # url_filter: 可选 callable(url)->bool，只记录关心的接口；默认记录全部
        self.url_filter = url_filter or (lambda u: True)
        self._responses = []  # [{"status": int, "url": str, "t": float}]
        page.on("response", self._on_response)

    def _on_response(self, resp):
        try:
            url = resp.url
            if self.url_filter(url):
                self._responses.append({"status": resp.status, "url": url, "t": time.time()})
        except Exception:
            pass

    def snapshot(self):
        """操作前调用：返回当前已记录响应的 URL 集合（基线）。"""
        return set(r["url"] for r in self._responses)

    def wait_new(self, baseline=None, keyword=None, timeout=15.0, interval=0.3,
                 accept_status=None):
        """等待出现基线之后的新响应，返回新响应列表（空=超时）。

        参数：
          baseline    snapshot() 的返回值；缺省用当前全部 URL 作为基线（即只等未来新请求）
          keyword     URL 包含该字符串才视为目标响应；None=等任意新响应
          timeout     最大等待秒数
          interval    轮询间隔
          accept_status  仅接受这些状态码的响应（默认接受 <400）
        """
        base = baseline if baseline is not None else set(r["url"] for r in self._responses)
        deadline = time.time() + timeout
        while time.time() < deadline:
            new = []
            for r in self._responses:
                if r["url"] in base:
                    continue
                if keyword is not None and keyword not in r["url"]:
                    continue
                if accept_status is not None:
                    if r["status"] not in accept_status:
                        continue
                elif r["status"] >= 400:
                    continue
                new.append(r)
            if new:
                return new
            time.sleep(interval)
        return []

    def recent(self, n=10):
        """最近 n 条响应（调试用）。"""
        return self._responses[-n:]


def wait_any_api(page, keyword=None, timeout=15.0, interval=0.3):
    """快捷用法：操作前先调用得到基线，再操作，再调用本函数。

    base = set()  # 或先收集当前 URL
    更推荐用 ApiWatcher 实例管理基线。
    """
    w = ApiWatcher(page)
    return w.wait_new(keyword=keyword, timeout=timeout, interval=interval)


if __name__ == "__main__":
    print("api_wait 可用：ApiWatcher(page) -> snapshot() -> 操作 -> wait_new(base)")


def confirm_action(page, action, watcher=None, keyword=None, timeout=15.0,
                   toast_selector=".el-message, .el-notification, .el-message-box"):
    """统一操作判定：执行操作 → 等新业务接口返回 → 收集错误与页面提示。

    解决"操作后盲目 sleep / 提前读 DOM"的问题：
    - 无新响应 = 操作未生效（按钮没点中/请求被拦截），按失败处理，不硬读页面；
    - 有 HTTP>=400 新响应 = 接口失败，结果带原因。

    用法：
        w = ApiWatcher(page)
        base = w.snapshot()                       # 操作前基线（可省略，函数内会自动取）
        result = confirm_action(page, lambda: click_action(...))
        if not result["ok"]:
            # result["errors"] 可直接进缺陷清单；不继续断言页面
        # ok 后再读 DOM 断言

    返回 dict：
        ok            操作是否生效（等到新接口且无 HTTP>=400 新响应）
        new_responses 操作后新响应列表
        errors        操作期间错误（HTTP>=400 响应 + 页面提示 toast）
        toasts        操作后页面可见提示文本
    """
    if watcher is None:
        watcher = ApiWatcher(page)
    base = watcher.snapshot()
    err_http = []

    def on_resp(resp):
        try:
            if resp.status >= 400:
                err_http.append((resp.status, resp.url[:200]))
        except Exception:
            pass

    page.on("response", on_resp)
    try:
        action()
        new = watcher.wait_new(base, keyword=keyword, timeout=timeout)
    finally:
        try:
            page.remove_listener("response", on_resp)
        except Exception:
            pass

    toasts = []
    try:
        for m in page.locator(toast_selector).all():
            try:
                if m.is_visible():
                    t = (m.inner_text() or "").strip()
                    if t and t not in toasts:
                        toasts.append(t[:200])
            except Exception:
                pass
    except Exception:
        pass

    err_http_new = [(s, u) for s, u in err_http if u not in set(r["url"] for r in base)]
    ok = bool(new) and not err_http_new
    return {"ok": ok, "new_responses": new, "errors": err_http_new, "toasts": toasts}


__all__ = ["ApiWatcher", "wait_any_api", "confirm_action"]
