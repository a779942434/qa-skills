# -*- coding: utf-8 -*-
"""L1 离线单测：DevTools 风格响应基线与重复接口识别。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import api_wait as A  # noqa: E402


class FakeRequest:
    def __init__(self, method="POST", post_data=""):
        self.method = method
        self.resource_type = "xhr"
        self.post_data = post_data


class FakeResponse:
    def __init__(self, url, status=200, request=None):
        self.url = url
        self.status = status
        self.status_text = "OK" if status < 400 else "ERROR"
        self.request = request or FakeRequest()


class FakePage:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    def emit_request(self):
        self.handlers["request"](FakeRequest())

    def emit_response(self, url, status=200):
        self.handlers["response"](FakeResponse(url, status))


class FakeExpectation:
    def __init__(self, response):
        self.response = response
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.value = self.response
        return False


class FakeResponsePage:
    def __init__(self, response):
        self.response = response
        self.matcher = None
        self.timeout = None
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    def expect_response(self, matcher, timeout=None):
        self.matcher = matcher
        self.timeout = timeout
        return FakeExpectation(self.response)


class TestApiWatcher(unittest.TestCase):
    def test_same_url_second_response_is_detected_by_sequence(self):
        page = FakePage()
        watcher = A.ApiWatcher(page)
        page.emit_request(); page.emit_response("http://x/api/list", 200)
        baseline = watcher.snapshot()
        page.emit_request(); page.emit_response("http://x/api/list", 200)
        new = watcher.wait_new(baseline, timeout=0.5)
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["seq"], 2)
        self.assertEqual(new[0]["status"], 200)
        self.assertEqual(new[0]["method"], "POST")
        self.assertLess(new[0]["duration_ms"], 10_000)

    def test_http_error_is_returned_for_network_judgement(self):
        page = FakePage()
        watcher = A.ApiWatcher(page)
        base = watcher.snapshot()
        page.emit_request(); page.emit_response("http://x/api/save", 500)
        new = watcher.wait_new(base, timeout=0.5, accept_status={500})
        self.assertEqual(new[0]["status"], 500)
        self.assertFalse(new[0]["ok"])



class TestRequestMatching(unittest.TestCase):
    def test_method_and_json_body_are_enforced(self):
        request = FakeRequest("POST", '{"queryType":1,"statusList":[0],"page":1}')
        response = FakeResponse("http://x/api/list?t=1", 200, request)

        class Page:
            def expect_response(self, matcher, timeout=None):
                class Ctx:
                    value = response
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        return False
                self.matcher = matcher
                return Ctx()

        result = A.wait_for_response_after_action(
            Page(), lambda: None, url_contains="/api/list", method="POST",
            request_json={"queryType": 1, "statusList": [0]}, timeout=5,
        )
        self.assertTrue(result["ok"])

    def test_wrong_method_does_not_match(self):
        request = FakeRequest("GET", '{"queryType":1}')
        response = FakeResponse("http://x/api/list", 200, request)

        class Page:
            def expect_response(self, matcher, timeout=None):
                class Ctx:
                    value = response
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        return False
                self.matcher = matcher
                return Ctx()

        page = Page()
        self.assertFalse(A._request_matches(response.request, method="POST"))
        result = A.wait_for_response_after_action(
            page, lambda: None, url_contains="/api/list", method="POST", timeout=5,
        )
        self.assertFalse(page.matcher(response))
        self.assertTrue(result["ok"])  # FakePage 不执行 Playwright 的真实等待过滤



class TestActionBoundResponse(unittest.TestCase):
    def test_wait_for_response_after_action_returns_status(self):
        request = FakeRequest()
        response = FakeResponse("http://x/api/save", 200, request)
        page = FakeResponsePage(response)
        called = []
        result = A.wait_for_response_after_action(
            page, lambda: called.append("action"),
            url_contains="/api/", timeout=10,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], 200)
        self.assertEqual(called, ["action"])
        self.assertTrue(page.matcher(response))

    def test_wait_for_response_after_action_marks_http_error(self):
        response = FakeResponse("http://x/api/save", 500)
        page = FakeResponsePage(response)
        result = A.wait_for_response_after_action(page, lambda: None, url_contains="/api/", timeout=10)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "http_error")


class TestWatcherAction(unittest.TestCase):
    def test_watcher_wait_action_uses_response_status(self):
        response = FakeResponse("http://x/api/query", 200)
        page = FakeResponsePage(response)
        watcher = A.ApiWatcher(page)
        records = watcher.wait_action(lambda: None, url_contains="/api/", timeout=5)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], 200)
        self.assertEqual(records[0]["url"], "http://x/api/query")


if __name__ == "__main__":
    unittest.main(verbosity=2)
