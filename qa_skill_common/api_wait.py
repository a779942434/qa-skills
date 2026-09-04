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
_VALIDATION_HINTS = (
    "必须", "不能", "至少", "不大于", "请选择", "请填写", "不能为", "不允许",
    "超出", "超过", "最少", "最多", "请输入", "不能小于", "必填", "大于0",
)
_SUCCESS_HINTS = ("成功", "已保存", "已完成", "已生成", "提交成功")


def _is_validation(text):
    return any(k in (text or "") for k in _VALIDATION_HINTS)


def _is_success(text):
    return any(k in (text or "") for k in _SUCCESS_HINTS)



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
                   toast_selector=".el-message, .el-notification, .el-message-box",
                   form_error_selector=".el-form-item__error"):
    """统一操作判定：执行操作 → 等新业务接口返回 → 收集错误/页面提示/内联校验错误。

    解决"操作后盲目 sleep / 提前读 DOM"与"校验拦截被误判为失败"的问题（2026-09-03 修正）：
    - "校验被拦截且有提示（toast/内联错误）"是**已处理（业务拦截）**，不是"无响应失败"；
    - 仅当"既无新响应、又无任何提示、数据又未变"（processed=False）才需人工核，
      避免把"必填校验已生效"误当"静默无提示"（如生成方式必填拦截）。

    用法：
        w = ApiWatcher(page)
        result = confirm_action(page, lambda: click_action(...))
        if not result["ok"]:
            # errors / form_errors 可直接进缺陷清单；processed 区分"被拦截"与"无响应"
        # ok 后再读 DOM 断言

    返回 dict：
        ok            操作成功（有新接口且无 HTTP>=400 新响应，且无"校验拦截"类提示）
        processed     操作是否被处理（有新业务响应 或 有 toast/内联校验提示）
        reason        "success" | "changed" | "blocked" | "silent" | "http_error"
        new_responses 操作后新响应列表
        errors        操作期间错误（HTTP>=400 新响应）
        toasts        操作后页面可见提示文本
        form_errors   操作后页面表单内联校验错误文本
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

    form_errors = []
    try:
        for m in page.locator(form_error_selector).all():
            try:
                if m.is_visible():
                    t = (m.inner_text() or "").strip()
                    if t and t not in form_errors:
                        form_errors.append(t[:200])
            except Exception:
                pass
    except Exception:
        pass

    err_http_new = [(s, u) for s, u in err_http if u not in set(r["url"] for r in base)]
    has_new_resp = bool(new)
    has_feedback = bool(toasts or form_errors)          # toast + 内联错误任一存在即视为"有反馈"
    has_validation = any(_is_validation(t) for t in (toasts + form_errors))
    has_success = any(_is_success(t) for t in toasts)
    processed = has_new_resp or has_feedback            # 已处理 = 有新响应 或 有提示

    if err_http_new:
        ok, reason = False, "http_error"
    elif has_validation:
        ok, reason = False, "blocked"                   # 校验拦截：已处理，但未成功
    elif has_success:
        ok, reason = True, "success"
    elif has_new_resp:
        ok, reason = True, "success"
    elif has_feedback:
        ok, reason = False, "blocked"
    else:
        ok, reason = False, "silent"                    # 无任何信号，需人工核

    return {"ok": ok, "processed": processed, "reason": reason,
            "new_responses": new, "errors": err_http_new,
            "toasts": toasts, "form_errors": form_errors}


__all__ = ["ApiWatcher", "wait_any_api", "confirm_action"]
