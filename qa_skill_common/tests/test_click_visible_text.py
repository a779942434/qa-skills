# -*- coding: utf-8 -*-
"""L1 离线单测：click_visible_text 的三级降级链。

降级链（locator fallback ladder）：
  1) role     Playwright 语义定位 get_by_role
  2) text     Playwright 精确文本 get_by_text
  3) js-text  JS 兜底（原实现：可见叶子 + 向上找可点容器）

点击方式（性能关键）：
  默认   浏览器内 e.click()  —— 实测约 3ms（role 已精确定位，无需遍历 DOM）
  native=True  Playwright click() —— 实测约 39ms，带滚动/稳定性/可接收事件检查

用假 Locator 模拟 Playwright API，不依赖浏览器与网络。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import bbt_helpers as H  # noqa: E402


class FakeLocator:
    """模拟 Playwright Locator（只实现被测代码用到的部分）。"""

    def __init__(self, exists=True, visible=True, tag="BUTTON", cls="btn",
                 click_raises=None, evaluate_raises=None):
        self.exists = exists
        self.visible = visible
        self.tag = tag
        self.cls = cls
        self.click_raises = click_raises
        self.evaluate_raises = evaluate_raises
        self.native_clicks = 0     # Playwright click() 次数
        self.js_clicks = 0         # 浏览器内 e.click() 次数
        self.describes = 0

    def count(self):
        return 1 if self.exists else 0

    @property
    def first(self):
        return self

    def nth(self, i):
        return self

    def is_visible(self):
        # 不存在 = 不可见（真实 Playwright 行为，也是被测代码依赖的语义）
        return self.visible and self.exists

    def click(self, **kw):
        self.native_clicks += 1
        if self.click_raises:
            raise RuntimeError(self.click_raises)

    def evaluate(self, expr):
        """含 click() 的表达式视作「JS 点击」，否则视作「取描述」。"""
        if "click()" in expr:
            self.js_clicks += 1
            if self.evaluate_raises:
                raise RuntimeError(self.evaluate_raises)
        else:
            self.describes += 1
        return "%s.%s" % (self.tag, self.cls)


EMPTY = FakeLocator(exists=False)


class FakePage:
    def __init__(self, roles=None, text=None, js=None, js_raises=None):
        self.roles = roles or {}
        self._text = text
        self._js = js
        self.js_raises = js_raises
        self.role_queries = []
        self.text_queries = []
        self.js_calls = []

    def get_by_role(self, role, name=None, exact=False):
        self.role_queries.append(role)
        return self.roles.get(role, EMPTY)

    def get_by_text(self, text, exact=False):
        self.text_queries.append(text)
        return self._text if self._text is not None else EMPTY

    def evaluate(self, js, arg=None):
        self.js_calls.append(arg)
        if self.js_raises:
            raise RuntimeError(self.js_raises)
        return self._js


class TestFallbackLadder(unittest.TestCase):

    def test_role_hit_short_circuits(self):
        """第一级命中后，不应再试后面两级。"""
        loc = FakeLocator()
        p = FakePage(roles={"button": loc})
        r = H.click_visible_text(p, "新增")
        self.assertTrue(r["ok"])
        self.assertEqual(r["via"], "role:button")
        self.assertEqual(loc.js_clicks, 1)
        self.assertEqual(p.text_queries, [])
        self.assertEqual(p.js_calls, [])

    def test_skips_invisible_then_next_role(self):
        p = FakePage(roles={"button": FakeLocator(visible=False),
                            "link": FakeLocator(tag="A", cls="lk")})
        r = H.click_visible_text(p, "详情")
        self.assertEqual(r["via"], "role:link")
        self.assertEqual(r["on"], "A.lk")

    def test_role_order_is_respected(self):
        """button 必须优先于 link。"""
        p = FakePage(roles={"button": FakeLocator(tag="BUTTON"),
                            "link": FakeLocator(tag="A")})
        r = H.click_visible_text(p, "X")
        self.assertEqual(r["via"], "role:button")
        self.assertEqual(p.role_queries[0], "button")

    def test_falls_back_to_text(self):
        p = FakePage(text=FakeLocator(tag="DIV", cls="btn-like"))
        r = H.click_visible_text(p, "导出")
        self.assertEqual(r["via"], "text")
        self.assertEqual(r["on"], "DIV.btn-like")
        self.assertTrue(p.role_queries)     # 第一级确实试过
        self.assertEqual(p.js_calls, [])    # 第二级命中，不该落到 JS

    def test_falls_back_to_js(self):
        p = FakePage(js={"ok": True, "on": "BUTTON.js"})
        r = H.click_visible_text(p, "查询")
        self.assertEqual(r["via"], "js-text")
        self.assertTrue(r["ok"])
        self.assertEqual(p.js_calls, ["查询"])

    def test_all_levels_fail(self):
        p = FakePage(js={"ok": False, "why": "none-visible"})
        r = H.click_visible_text(p, "不存在")
        self.assertFalse(r["ok"])
        self.assertEqual(r["via"], "js-text")
        self.assertEqual(r["why"], "none-visible")

    def test_js_exception_is_reported(self):
        p = FakePage(js_raises="boom")
        r = H.click_visible_text(p, "X")
        self.assertFalse(r["ok"])
        self.assertIn("boom", r["why"])

    def test_role_click_failure_degrades_to_text(self):
        """role 找到可见目标但点不动时，应直接降级，而不是继续试其它 role。"""
        p = FakePage(roles={"button": FakeLocator(evaluate_raises="detached")},
                     text=FakeLocator(tag="DIV", cls="fallback"))
        r = H.click_visible_text(p, "X")
        self.assertEqual(r["via"], "text")
        self.assertEqual(r["on"], "DIV.fallback")
        self.assertEqual(p.role_queries, ["button"])   # 只试了 button

    def test_custom_roles(self):
        p = FakePage(roles={"menuitem": FakeLocator(tag="LI", cls="mi")})
        r = H.click_visible_text(p, "编辑", roles=["menuitem"])
        self.assertEqual(r["via"], "role:menuitem")
        self.assertEqual(p.role_queries, ["menuitem"])


class TestClickMode(unittest.TestCase):
    """默认走 JS 点击（快）；native=True 走 Playwright click（慢但带可操作性检查）。"""

    def test_default_uses_js_click(self):
        loc = FakeLocator()
        p = FakePage(roles={"button": loc})
        H.click_visible_text(p, "新增")
        self.assertEqual(loc.js_clicks, 1)
        self.assertEqual(loc.native_clicks, 0)

    def test_native_uses_playwright_click(self):
        loc = FakeLocator()
        p = FakePage(roles={"button": loc})
        r = H.click_visible_text(p, "新增", native=True)
        self.assertEqual(loc.native_clicks, 1)
        self.assertEqual(loc.js_clicks, 0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["via"], "role:button")

    def test_default_message_contains_click_in_one_roundtrip(self):
        """默认路径应是「一次 evaluate 内既点击又取描述」。"""
        loc = FakeLocator(tag="BUTTON", cls="primary")
        p = FakePage(roles={"button": loc})
        r = H.click_visible_text(p, "新增")
        self.assertEqual(loc.js_clicks, 1)
        self.assertEqual(r["on"], "BUTTON.primary")


class TestBackwardCompat(unittest.TestCase):
    """老调用方依赖 {ok, on} / {ok, why}，改造后必须保留。"""

    def test_success_has_ok_and_on(self):
        p = FakePage(roles={"button": FakeLocator()})
        r = H.click_visible_text(p, "新增")
        self.assertIn("ok", r)
        self.assertIn("on", r)

    def test_js_failure_has_ok_and_why(self):
        p = FakePage(js={"ok": False, "why": "none-visible"})
        r = H.click_visible_text(p, "X")
        self.assertIn("ok", r)
        self.assertIn("why", r)

    def test_via_is_additive_only_on_success(self):
        p = FakePage(roles={"button": FakeLocator()})
        r = H.click_visible_text(p, "新增")
        self.assertEqual(set(r), {"ok", "on", "via"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
