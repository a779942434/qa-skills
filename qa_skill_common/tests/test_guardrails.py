# -*- coding: utf-8 -*-
"""L1 离线单测：防超时/作用域/失败现场 helper。"""
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import bbt_helpers as H  # noqa: E402


class FakeLocator:
    def __init__(self, exists=True, visible=True, text="", disabled=False, click_raises=None):
        self.exists = exists
        self.visible = visible
        self.text = text
        self.disabled = disabled
        self.click_raises = click_raises
        self.clicks = 0
        self.waits = []

    def count(self):
        return 1 if self.exists else 0

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def nth(self, i):
        return self

    def is_visible(self):
        return self.exists and self.visible

    def wait_for(self, state="visible", timeout=None):
        self.waits.append((state, timeout))
        if state == "visible" and not self.is_visible():
            raise RuntimeError("not visible")

    def is_disabled(self, timeout=None):
        return self.disabled

    def click(self, **kw):
        self.clicks += 1
        if self.click_raises:
            raise RuntimeError(self.click_raises)

    def inner_text(self, timeout=None):
        if not self.is_visible():
            raise RuntimeError("not visible")
        return self.text


class FakeCollection:
    def __init__(self, items):
        self.items = items

    def count(self):
        return len(self.items)

    def nth(self, i):
        return self.items[i]


class FakePage:
    def __init__(self, collections=None):
        self.collections = collections or {}
        self.default_timeout = None
        self.navigation_timeout = None

    def locator(self, selector):
        return self.collections.get(selector, FakeCollection([]))

    def set_default_timeout(self, ms):
        self.default_timeout = ms

    def set_default_navigation_timeout(self, ms):
        self.navigation_timeout = ms


class TestGuardrails(unittest.TestCase):
    def test_configure_page_timeouts(self):
        p = FakePage()
        result = H.configure_page_timeouts(p, action_ms=4000, navigation_ms=12000)
        self.assertEqual(p.default_timeout, 4000)
        self.assertEqual(p.navigation_timeout, 12000)
        self.assertEqual(result["action_ms"], 4000)

    def test_active_pane_uses_last_visible_pane(self):
        first = FakeLocator()
        last = FakeLocator()
        p = FakePage({".el-tab-pane:visible": FakeCollection([first, last])})
        self.assertIs(H.active_pane(p), last)

    def test_dialog_by_title_returns_matching_overlay(self):
        dlg = FakeLocator(text="新增")
        p = FakePage({'.el-overlay-dialog:visible[aria-label="新增"]': FakeCollection([dlg])})
        self.assertIs(H.dialog_by_title(p, "新增"), dlg)

    def test_safe_click_reports_disabled_without_click(self):
        loc = FakeLocator(disabled=True)
        result = H.safe_click(loc, timeout=1, description="确定")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "disabled")
        self.assertEqual(loc.clicks, 0)

    def test_safe_click_not_visible(self):
        loc = FakeLocator(visible=False)
        result = H.safe_click(loc, timeout=0.1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_visible")

    def test_wait_result_or_closed_reads_result(self):
        dlg = FakeLocator(text="导入完成（成功0条，失败1条）第2行 必填字段不能为空")
        result = H.wait_result_or_closed(FakePage(), dlg, ["导入完成", "失败"], timeout=0.5)
        self.assertEqual(result["status"], "result")
        self.assertEqual(result["matched"], "导入完成")

    def test_wait_result_or_closed_handles_closed_dialog(self):
        dlg = FakeLocator(exists=False)
        result = H.wait_result_or_closed(FakePage(), dlg, ["导入完成"], timeout=0.5)
        self.assertEqual(result["status"], "closed")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestResetToNoFixedSleep(unittest.TestCase):
    """修正：reset_to 默认条件等待，不再固定 sleep。

    实测依据：原实现 wait_ms=6000，3 条用例的截图间隔精确 6.0s，白等 18s
    （占 run 总时长 75%），换成条件等待后同类任务 23.9s → 11.0s。
    """

    class P:
        def __init__(self):
            self.gotoed = None
            self.waits = []

        def goto(self, url, **kwargs):
            self.gotoed = url

        def wait_for_timeout(self, ms):
            self.waits.append(ms)

    def test_default_uses_conditional_wait(self):
        p = self.P()
        with mock.patch.object(H, "wait_app_ready", lambda *a, **k: True):
            H.reset_to(p, "http://x.example/y")
        self.assertEqual(p.gotoed, "http://x.example/y")
        self.assertEqual(p.waits, [])          # 默认不再固定等待

    def test_explicit_wait_ms_is_capped(self):
        p = self.P()
        with mock.patch.object(H, "wait_app_ready", lambda *a, **k: True):
            H.reset_to(p, "http://x.example/y", wait_ms=6000)
        self.assertEqual(p.waits, [800])       # 显式传入也封顶 800ms（同 sleep 动作）


class FakeElement:
    def __init__(self, tag="DIV", desc=None, attrs=None):
        self.tag = tag
        self.desc = desc or {}
        self.attrs = attrs or {}
        self.count_value = 1
        self.clicks = 0
        self.children = dict(desc or {})

    def evaluate(self, expr):
        return self.tag

    def get_attribute(self, name):
        return self.attrs.get(name)

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def count(self):
        return self.count_value

    def locator(self, selector, **kw):
        item = self.children.get(selector)
        if item is None:
            item = FakeElement(desc={}, attrs={})
            item.count_value = 0
        return item

    def wait_for(self, state="visible", timeout=None):
        if self.count_value == 0:
            raise RuntimeError("not visible")

    def click(self, **kw):
        self.clicks += 1


class TestControlAndCascader(unittest.TestCase):
    def test_control_type_detects_select_and_reports_mismatch(self):
        select = FakeElement(tag="DIV", desc={".el-select": FakeElement()})
        result = H.assert_control_type(select, "手动输入", timeout=0.1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["actual"], "select")

    def test_control_type_accepts_text_input(self):
        inp = FakeElement(tag="INPUT", attrs={"type": "text", "readonly": None})
        result = H.assert_control_type(inp, "input", timeout=0.1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["actual"], "input")

    def test_wait_dropdown_closed_uses_visible_count(self):
        class P:
            def __init__(self):
                self.counts = iter([1, 0])

            def locator(self, selector):
                class L:
                    def __init__(self, n): self.n = n
                    def count(self): return self.n
                return L(next(self.counts))
        self.assertTrue(H.wait_dropdown_closed(P(), timeout=1))

    def test_select_cascader_values_confirms_and_reads_tags(self):
        tags = []
        checkbox = FakeElement(tag="LABEL")
        checkbox.click = lambda **kw: tags.append("地点A")
        node = FakeElement(tag="LI")
        node.children[".el-checkbox"] = checkbox
        node.click = lambda **kw: tags.append("地点A")

        root = FakeElement(tag="DIV")
        root.children[".el-tag"] = FakeElement(tag="SPAN")
        root.children[".el-tag"].inner_text = lambda timeout=None: ""
        root.children[".el-tag"].all_inner_texts = lambda: list(tags)
        root.children["input"] = FakeElement(tag="INPUT", attrs={"type": "text", "readonly": None})
        root.children["input"].input_value = lambda: ""

        trigger = FakeElement(tag="DIV")
        trigger.children[".el-cascader"] = root

        class P:
            def locator(self, selector, **kw):
                if "el-cascader-node" in selector:
                    return node
                if "el-cascader-dropdown" in selector or "el-popper" in selector:
                    popper = FakeElement(tag="DIV")
                    btn = FakeElement(tag="BUTTON")
                    popper.children["button"] = btn
                    return popper
                return FakeElement()
            def wait_for_timeout(self, ms):
                pass

        with mock.patch.object(H, "wait_dropdown_closed", return_value=True):
            result = H.select_cascader_values(P(), trigger, ["地点A"], timeout=1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["selected"], ["地点A"])
