# -*- coding: utf-8 -*-
"""接口观测等待工具（web-blackbox-testing 配套）。

核心思想：页面数据是接口返回后渲染的。不要在操作后直接固定 sleep 或立即读 DOM，
而是观测页面实际发出的接口，等到"操作触发的业务接口返回"后再断言页面数据。

推荐模式（动作与接口响应绑定）：

    from api_wait import ApiWatcher
    watcher = ApiWatcher(page)          # 挂 request/response 监听（覆盖所有 frame）

    new = watcher.wait_action(
        lambda: page.get_by_role("button", name="查询").click(),
        url_contains="/plan/",
        timeout=60,
    )
    # 接口返回即继续；timeout 只是异常上限，不表示要等满 60 秒。

也可直接调用：
    from api_wait import wait_for_response_after_action
    result = wait_for_response_after_action(page, action, url_contains="/plan/", timeout=60)

`snapshot()` + `wait_new()` 仅保留给“响应已经发生、只读观察”的兼容场景；
业务动作完成判定统一优先使用 `wait_action()`。
"""
import threading
import time
__all__ = ["ApiWatcher", "wait_any_api", "wait_for_response_after_action"]
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
        self._responses = []  # DevTools Network 风格响应记录
        self._request_started = {}
        self._event = threading.Event()
        page.on("request", self._on_request)
        page.on("response", self._on_response)

    @staticmethod
    def _request_key(request):
        return (
            getattr(request, "method", ""),
            getattr(request, "url", ""),
            getattr(request, "resource_type", ""),
        )

    def _on_request(self, request):
        try:
            key = self._request_key(request)
            self._request_started.setdefault(key, []).append(time.time())
        except Exception:
            pass

    def _on_response(self, resp):
        try:
            url = resp.url
            if self.url_filter(url):
                request = resp.request
                key = self._request_key(request)
                starts = self._request_started.get(key, [])
                started = starts.pop(0) if starts else None
                if not starts:
                    self._request_started.pop(key, None)
                now = time.time()
                self._responses.append({
                    "seq": len(self._responses) + 1,
                    "method": getattr(request, "method", ""),
                    "resource_type": getattr(request, "resource_type", ""),
                    "status": resp.status,
                    "status_text": getattr(resp, "status_text", ""),
                    "url": url,
                    "ok": int(resp.status) < 400,
                    "t": now,
                    "duration_ms": int((now - started) * 1000) if started else None,
                })
                self._event.set()
        except Exception:
            pass

    def close(self):
        """移除页面监听，避免长流程反复挂 watcher 造成监听器堆积。"""
        for event, handler in (("request", self._on_request), ("response", self._on_response)):
            try:
                self.page.remove_listener(event, handler)
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def snapshot(self):
        """操作前调用：返回响应序号和 URL 基线。

        序号用于识别“同一个 URL 的第二次调用”，避免旧实现按 URL 集合并集后漏掉重复接口。
        """
        return {
            "seq": len(self._responses),
            "urls": set(r["url"] for r in self._responses),
        }

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
        if baseline is None:
            start_seq = len(self._responses)
            base_urls = set(r["url"] for r in self._responses)
        elif isinstance(baseline, dict):
            start_seq = int(baseline.get("seq", 0))
            base_urls = set(baseline.get("urls", set()))
        elif isinstance(baseline, int):
            start_seq = int(baseline)
            base_urls = set()
        else:  # 兼容旧 URL 集合基线
            start_seq = 0
            base_urls = set(baseline)
        deadline = time.time() + timeout

        def _collect():
            new = []
            for r in self._responses:
                if "seq" in r:
                    if r["seq"] <= start_seq:
                        continue
                elif r["url"] in base_urls:
                    continue
                if keyword is not None and keyword not in r["url"]:
                    continue
                if accept_status is not None:
                    if r["status"] not in accept_status:
                        continue
                elif r["status"] >= 400:
                    continue
                new.append(r)
            return new

        while True:
            new = _collect()
            if new:
                return new
            remaining = deadline - time.time()
            if remaining <= 0:
                return []
            self._event.wait(min(remaining, max(float(interval), 0.05)))
            self._event.clear()

    def wait_action(self, action, keyword=None, url_contains=None, method=None, predicate=None,
                    request_predicate=None, request_json=None, body_contains=None,
                    timeout=60.0, accept_status=None, resource_types=("xhr", "fetch")):
        """执行 action 并等待匹配接口返回，返回 Network 风格响应记录列表。

        这是推荐入口：响应回来即结束；timeout 仅为异常上限。旧 `wait_new` 仅用于
        “已经发生完、只读观察”的场景，不应再用于动作完成判定。
        """
        result = wait_for_response_after_action(
            self.page, action,
            url_contains=url_contains or keyword,
            method=method,
            predicate=predicate,
            request_predicate=request_predicate,
            request_json=request_json,
            body_contains=body_contains,
            timeout=timeout,
            accept_status=accept_status,
            resource_types=resource_types,
        )
        response = result.get("response")
        if response is None:
            return []
        request = getattr(response, "request", None)
        return [{
            "seq": None,
            "method": getattr(request, "method", ""),
            "resource_type": getattr(request, "resource_type", ""),
            "status": result.get("status", getattr(response, "status", None)),
            "status_text": result.get("status_text", ""),
            "url": result.get("url", getattr(response, "url", "")),
            "ok": int(result.get("status", 500)) < 400,
            "t": time.time(),
            "duration_ms": int(float(result.get("elapsed", 0)) * 1000),
        }]

    def recent(self, n=10):
        """最近 n 条响应（调试用）。"""
        return self._responses[-n:]


_STATIC_SUFFIXES = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".map",
)


def _is_static_url(url: str) -> bool:
    path = str(url or "").split("?", 1)[0].lower()
    return path.endswith(_STATIC_SUFFIXES)



def _normalize_methods(method):
    if method is None:
        return set()
    values = [method] if isinstance(method, str) else list(method)
    return {str(x).strip().upper() for x in values if str(x).strip()}


def _json_contains(actual, expected):
    """递归判断 actual 是否包含 expected 的键值；列表按“存在任一匹配项”处理。"""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and _json_contains(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(any(_json_contains(item, exp) for item in actual) for exp in expected)
    return actual == expected


def _request_matches(request, method=None, request_predicate=None,
                     request_json=None, body_contains=None):
    methods = _normalize_methods(method)
    req_method = str(getattr(request, "method", "") or "").upper()
    if methods and req_method not in methods:
        return False
    if request_predicate is not None:
        try:
            if not request_predicate(request):
                return False
        except Exception:
            return False
    body = ""
    try:
        body = getattr(request, "post_data", "") or ""
    except Exception:
        body = ""
    if body_contains is not None:
        needles = [body_contains] if isinstance(body_contains, str) else list(body_contains)
        if not all(str(x) in body for x in needles):
            return False
    if request_json is not None:
        try:
            actual = json.loads(body) if body else None
        except Exception:
            return False
        if not _json_contains(actual, request_json):
            return False
    return True


def wait_for_response_after_action(page, action, url_contains=None, method=None, predicate=None,
                                   request_predicate=None, request_json=None, body_contains=None,
                                   timeout=60.0, accept_status=None,
                                   exclude_static=True, raise_on_timeout=False,
                                   resource_types=("xhr", "fetch")):
    """在执行 action 前绑定响应等待，等匹配的业务接口返回后立即继续。

    - 不使用固定 5 秒作为完成信号；只要接口返回就结束，接口慢可继续等；
    - timeout 仅是保护性上限，不是等待时长；
    - url_contains 支持字符串或字符串列表；
    - 返回 {ok,status,url,elapsed,response} 或 {ok:False,reason,elapsed,error}。
    """
    started = time.time()
    contains = [url_contains] if isinstance(url_contains, str) else list(url_contains or [])

    def _matcher(response):
        url = response.url or ""
        status = int(response.status)
        if exclude_static and _is_static_url(url):
            return False
        if resource_types is not None:
            try:
                rtype = response.request.resource_type
            except Exception:
                rtype = ""
            if rtype and rtype not in resource_types:
                return False
        if contains and not any(x in url for x in contains):
            return False
        if accept_status is not None and status not in accept_status:
            return False
        if not _request_matches(response.request, method=method,
                                request_predicate=request_predicate,
                                request_json=request_json,
                                body_contains=body_contains):
            return False
        if predicate is not None and not predicate(response):
            return False
        return True

    try:
        with page.expect_response(_matcher, timeout=int(float(timeout) * 1000)) as info:
            if action is not None:
                action()
        response = info.value
        return {
            "ok": int(response.status) < 400,
            "reason": "response_received" if int(response.status) < 400 else "http_error",
            "status": response.status,
            "status_text": getattr(response, "status_text", ""),
            "url": response.url,
            "elapsed": time.time() - started,
            "response": response,
        }
    except Exception as exc:
        result = {
            "ok": False,
            "reason": "timeout" if "Timeout" in type(exc).__name__ else "response_error",
            "elapsed": time.time() - started,
            "error": str(exc)[:300],
        }
        if raise_on_timeout:
            raise
        return result


def wait_any_api(page, action=None, keyword=None, timeout=60.0, interval=0.3,
                 url_contains=None, method=None, predicate=None,
                 request_predicate=None, request_json=None, body_contains=None, accept_status=None,
                 resource_types=("xhr", "fetch")):
    """等待 action 触发的新业务接口返回。action 为必填。"""
    if action is None:
        raise ValueError("wait_any_api 必须传入 action；只读观察请直接使用 ApiWatcher.wait_new")
    w = ApiWatcher(page)
    return w.wait_action(
        action, keyword=keyword, url_contains=url_contains, method=method, predicate=predicate,
        request_predicate=request_predicate, request_json=request_json, body_contains=body_contains,
        timeout=timeout, accept_status=accept_status, resource_types=resource_types,
    )


if __name__ == "__main__":
    print("api_wait 推荐：ApiWatcher.wait_action(action) / wait_for_response_after_action")


def confirm_action(page, action, watcher=None, keyword=None, timeout=60.0,
                   response_required=True, method=None, request_predicate=None,
                   request_json=None, body_contains=None,
                   toast_selector=".el-message, .el-notification, .el-message-box",
                   form_error_selector=".el-form-item__error"):
    """执行 action 并等待业务接口返回，再综合判定结果。

    默认 action 与接口响应绑定：接口返回即继续，timeout 只是异常上限。
    对“纯前端必填校验”这类不发接口的动作，显式传 response_required=False。
    """
    w = watcher or ApiWatcher(page)
    if response_required:
        responses = w.wait_action(
            action, keyword=keyword, method=method, timeout=timeout,
            request_predicate=request_predicate, request_json=request_json,
            body_contains=body_contains,
        )
    else:
        action()
        responses = []

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

    errors = [(r.get("status"), r.get("url")) for r in responses if r.get("status", 0) >= 400]
    has_new_resp = bool(responses)
    has_feedback = bool(toasts or form_errors)
    has_validation = any(_is_validation(t) for t in (toasts + form_errors))
    has_success = any(_is_success(t) for t in toasts)
    processed = has_new_resp or has_feedback

    if errors:
        ok, reason = False, "http_error"
    elif has_validation:
        ok, reason = False, "blocked"
    elif has_success or (has_new_resp and not has_validation):
        ok, reason = True, "success"
    elif has_feedback:
        ok, reason = False, "blocked"
    else:
        ok, reason = False, "silent"

    return {
        "ok": ok,
        "processed": processed,
        "reason": reason,
        "new_responses": responses,
        "errors": errors,
        "toasts": toasts,
        "form_errors": form_errors,
    }


__all__ = ["ApiWatcher", "wait_any_api", "wait_for_response_after_action", "confirm_action"]
