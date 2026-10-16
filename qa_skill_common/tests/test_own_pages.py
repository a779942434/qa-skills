# -*- coding: utf-8 -*-
"""L1 离线单测：会话隔离（自有页面登记 / 禁止误关他人页面）。

对抗性用例：
  - 默认调用 close_other_pages 必须**拒绝**（否则等于没防）
  - force=True 也不得关闭「自有页面」与 keep 页面
  - _warn_foreign_pages 只告警、**绝不**关闭任何页面
"""
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import bbt_helpers as H  # noqa: E402


class FakePage:
    def __init__(self, url="about:blank"):
        self.url = url
        self.closed = False

    def close(self):
        self.closed = True


class FakeCtx:
    def __init__(self, pages):
        self.pages = list(pages)


class OwnPagesTest(unittest.TestCase):
    def setUp(self):
        self._bak = set(H._OWN_PAGE_IDS)
        H._OWN_PAGE_IDS.clear()

    def tearDown(self):
        H._OWN_PAGE_IDS.clear()
        H._OWN_PAGE_IDS.update(self._bak)

    # ---- 对抗性 1：默认必须拒绝 ----
    def test_close_other_pages_refuses_by_default(self):
        mine, foreign = FakePage("mine"), FakePage("foreign")
        H._register_own_page(mine)
        ctx = FakeCtx([mine, foreign])
        with self.assertRaises(RuntimeError):
            H.close_other_pages(ctx)
        self.assertFalse(foreign.closed, "默认拒绝时不得关闭任何页面")
        self.assertFalse(mine.closed)

    # ---- 对抗性 2：force 也只关外来页面 ----
    def test_force_closes_only_foreign(self):
        mine, keep, foreign = FakePage("mine"), FakePage("keep"), FakePage("foreign")
        H._register_own_page(mine)
        ctx = FakeCtx([mine, keep, foreign])
        closed = H.close_other_pages(ctx, keep=keep, force=True)
        self.assertEqual(closed, ["foreign"])
        self.assertTrue(foreign.closed)
        self.assertFalse(mine.closed, "自有页面不得被关闭")
        self.assertFalse(keep.closed, "keep 页面不得被关闭")

    # ---- 对抗性 3：告警函数不产生副作用 ----
    def test_warn_foreign_pages_is_readonly(self):
        mine, foreign = FakePage("mine"), FakePage("foreign")
        H._register_own_page(mine)
        buf = io.StringIO()
        with redirect_stderr(buf):
            H._warn_foreign_pages(FakeCtx([mine, foreign]), keep=mine)
        self.assertIn("非本会话页面", buf.getvalue())
        self.assertFalse(foreign.closed, "告警不得关闭任何页面")
        self.assertFalse(mine.closed)

    def test_warn_silent_when_no_foreign(self):
        mine = FakePage("mine")
        H._register_own_page(mine)
        buf = io.StringIO()
        with redirect_stderr(buf):
            H._warn_foreign_pages(FakeCtx([mine]), keep=mine)
        self.assertEqual(buf.getvalue().strip(), "")

    def test_own_pages_registry(self):
        a, b = FakePage(), FakePage()
        H._register_own_page(a)
        H._register_own_page(b)
        self.assertEqual(len(H.own_pages()), 2)


if __name__ == "__main__":
    unittest.main()
