# -*- coding: utf-8 -*-
"""L1 离线单测：组件探针 / 结构指纹与对比 / 相似度自愈定位。

不依赖浏览器与网络：用假 page 拦截 evaluate / locator / get_by_role / get_by_text，
用临时目录隔离指纹落盘。真机行为由 L2（沙箱外）覆盖。

运行：python3 -m unittest discover -s qa_skill_common/tests -t . -v
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import fingerprint as F  # noqa: E402


class FakeLocator:
    def __init__(self, exists=True, visible=True, tag="BUTTON", cls="btn"):
        self.exists = exists
        self.visible = visible
        self.tag = tag
        self.cls = cls

    def count(self):
        return 1 if self.exists else 0

    @property
    def first(self):
        return self

    def nth(self, i):
        return self

    def is_visible(self):
        return self.visible and self.exists

    def click(self, **kw):
        self._clicked = True

    def evaluate(self, expr):
        if "click()" in expr:
            return "%s.%s" % (self.tag, self.cls)
        return "%s.%s" % (self.tag, self.cls)


MISSING = FakeLocator(exists=False)


class FakePage:
    """按 JS 特征分派 evaluate 返回值的假页面。"""

    def __init__(self, *, probe=None, elements=None, locators=None,
                 by_role=None, by_text=None, url="http://mes.example.com/x"):
        self._probe = probe
        self._elements = elements or []
        self._locators = locators or {}
        self._by_role = by_role or {}
        self._by_text = by_text or {}
        self.url = url
        self.evaluate_calls = []

    def evaluate(self, js, arg=None):
        self.evaluate_calls.append((js, arg))
        if "class_counts" in js:          # _PROBE_JS
            return self._probe or {}
        if "INTERACTIVE" in js:            # _CAPTURE_JS
            return self._elements
        return {}

    def locator(self, selector, **kw):
        return self._locators.get(selector, MISSING)

    def get_by_role(self, role, name=None, exact=False):
        return self._by_role.get(role, MISSING)

    def get_by_text(self, text, exact=False):
        return self._by_text.get(text, MISSING)


def elem(tag="button", classes=None, text="", role="", tier=0, path=None, ancestors=None):
    return {
        "tier": tier, "tag": tag, "classes": classes or [], "role": role, "text": text,
        "attrs": {}, "ancestor_path": ancestors or [], "sibling_texts": [],
        "child_tags": [], "path": path or ("body > %s:nth-child(1)" % tag),
    }


class TestClassPrefix(unittest.TestCase):
    def test_known_and_unknown_prefixes(self):
        cases = [("el-button", "el-"), ("el-button--primary", "el-"),
                 ("div-table-row", "div-table"), ("sy-toolbar", "sy-"),
                 ("vxe-table--body", "vxe-"), ("xc-panel", "xc-"),
                 ("btn", "btn"), ("", "")]
        for inp, want in cases:
            self.assertEqual(F.class_prefix(inp), want, "class_prefix(%r)" % inp)


class TestVerdict(unittest.TestCase):
    @staticmethod
    def lib(prefix, slug, share):
        return {"prefix": prefix, "slug": slug, "share": share}

    def test_dominant_library(self):
        self.assertEqual(F._decide_verdict([self.lib("el-", "element-plus", 0.7)], []), "element-plus")

    def test_mixed(self):
        libs = [self.lib("el-", "element-plus", 0.3), self.lib("sy-", "custom-sy", 0.25)]
        self.assertEqual(F._decide_verdict(libs, []), "mixed")

    def test_custom_when_only_unknown_dominates(self):
        self.assertEqual(F._decide_verdict([self.lib("el-", "element-plus", 0.1)],
                                           [{"prefix": "xc-", "share": 0.3}]), "custom")

    def test_unknown_when_nothing_dominates(self):
        self.assertEqual(F._decide_verdict([self.lib("el-", "element-plus", 0.1)], []), "unknown")

    def test_dominant_wins_over_mixed(self):
        """单库 >= 60% 时即使另一个库 >= 20% 也判该库，不判 mixed。"""
        libs = [self.lib("el-", "element-plus", 0.65), self.lib("sy-", "custom-sy", 0.25)]
        self.assertEqual(F._decide_verdict(libs, []), "element-plus")

    def test_primary_when_no_dominant_but_clear_leader(self):
        """最高库 >= 30% 且无第二库 >= 20% -> 判该库（primary 档）。"""
        libs = [self.lib("el-", "element-plus", 0.44), self.lib("sy-", "custom-sy", 0.15)]
        self.assertEqual(F._decide_verdict(libs, []), "element-plus")

    def test_primary_does_not_override_mixed(self):
        """两个库都 >= 20% 时仍判 mixed，primary 不抢戏。"""
        libs = [self.lib("el-", "element-plus", 0.44), self.lib("sy-", "custom-sy", 0.25)]
        self.assertEqual(F._decide_verdict(libs, []), "mixed")

    def test_primary_requires_30_percent(self):
        """最高库 < 30% 时不判 primary。"""
        self.assertEqual(F._decide_verdict([self.lib("el-", "element-plus", 0.25)], []), "unknown")


class TestProbe(unittest.TestCase):
    def test_counts_shares_and_unknown(self):
        page = FakePage(probe={
            "total_elements": 10, "iframes": 2,
            "class_counts": {"el-button": 6, "el-input": 2, "sy-panel": 1, "xc-x": 1},
        })
        r = F.probe_components(page)
        self.assertEqual(r["total_elements"], 10)
        self.assertEqual(r["iframes"], 2)
        self.assertEqual(r["total_class_instances"], 10)
        # el- 共 8/10 = 80% -> dominant
        self.assertEqual(r["verdict"], "element-plus")
        el = [x for x in r["libraries"] if x["prefix"] == "el-"][0]
        self.assertAlmostEqual(el["share"], 0.8, places=4)
        # xc- 1/10 = 10% >= 5% -> 进未知报告
        self.assertEqual([x["prefix"] for x in r["unknown_prefixes"]], ["xc-"])

    def test_unknown_below_threshold_is_dropped(self):
        page = FakePage(probe={"total_elements": 100, "iframes": 0,
                               "class_counts": {"el-a": 97, "xc-b": 1, "xc-c": 1, "xc-d": 1}})
        r = F.probe_components(page)
        self.assertEqual(r["unknown_prefixes"], [])   # 3/100 = 3% < 5%

    def test_empty_page(self):
        r = F.probe_components(FakePage(probe={"total_elements": 0, "iframes": 0,
                                               "class_counts": {}}))
        self.assertEqual(r["verdict"], "unknown")
        self.assertEqual(r["class_prefixes"], [])

    def test_status_prefixes_go_to_decorators(self):
        """is-* 是状态类：归 decorators，不进 unknown、不参与判定。"""
        page = FakePage(probe={"total_elements": 20, "iframes": 0,
                               "class_counts": {"el-button": 7, "is-active": 2, "is-disabled": 1}})
        r = F.probe_components(page)
        self.assertEqual([d["prefix"] for d in r["decorators"]], ["is-"])
        self.assertEqual(r["unknown_prefixes"], [])
        self.assertEqual(r["verdict"], "element-plus")

    def test_primary_verdict_from_probe(self):
        """真实站点形态：el- 40% + 工具类稀释 -> primary 判 element-plus。"""
        page = FakePage(probe={"total_elements": 100, "iframes": 0,
                               "class_counts": {"el-button": 20, "is-active": 5,
                                                "w-full": 20, "flex": 5}})
        r = F.probe_components(page)
        # 分母 50：el- 40% (>=30%, 无第二库) -> primary；is- 归 decorators；w- 10% 进 unknown
        self.assertEqual(r["verdict"], "element-plus")
        self.assertEqual([d["prefix"] for d in r["decorators"]], ["is-"])
        self.assertNotIn("is-", [u["prefix"] for u in r["unknown_prefixes"]])


class TestSanitizeName(unittest.TestCase):
    def test_keeps_safe_chars(self):
        self.assertEqual(F.sanitize_name("ipc-line_计划切换"), "ipc-line_计划切换")

    def test_replaces_bad_chars(self):
        self.assertEqual(F.sanitize_name("a/b c"), "a_b_c")

    def test_empty_falls_back(self):
        self.assertEqual(F.sanitize_name(""), "unnamed")
        self.assertEqual(F.sanitize_name(None), "unnamed")

    def test_length_capped(self):
        self.assertEqual(len(F.sanitize_name("x" * 200)), 80)


class TestSimilarity(unittest.TestCase):
    def test_text_sim_exact_contains_else(self):
        self.assertEqual(F.text_sim("新增", "新增"), 1.0)
        self.assertEqual(F.text_sim("新增", "新增按钮"), 0.6)
        self.assertEqual(F.text_sim("", "x"), 0.0)
        self.assertLess(F.text_sim("新增", "导出"), 0.01)

    def test_text_sim_partial_overlap_between_0_and_1(self):
        s = F.text_sim("客户名称", "客户编码")
        self.assertGreater(s, 0.0)
        self.assertLess(s, 1.0)

    def test_class_jaccard(self):
        self.assertEqual(F.class_jaccard(["a", "b"], ["b", "a"]), 1.0)
        self.assertAlmostEqual(F.class_jaccard(["a", "b"], ["b", "c"]), 1 / 3)
        self.assertEqual(F.class_jaccard(["a"], []), 0.0)
        self.assertEqual(F.class_jaccard([], []), 1.0)

    def test_identical_elements_score_one_when_all_axes_present(self):
        e = elem(classes=["el-button"], text="新增", role="button",
                 ancestors=["div.toolbar"])
        e["sibling_texts"] = ["导出"]
        self.assertAlmostEqual(F.similarity(e, dict(e)), 1.0, places=4)

    def test_empty_axes_do_not_inflate_score(self):
        """空维度不计分：只有 class/text/role/tag 有信号时满分是 0.80。"""
        e = elem(classes=["el-button"], text="新增", role="button")
        self.assertAlmostEqual(F.similarity(e, dict(e)), 0.80, places=4)

    def test_class_change_degrades_but_still_high(self):
        a = elem(classes=["action-button"], text="计划切换", role="button", ancestors=["div.toolbar"])
        b = elem(classes=["op-btn"], text="计划切换", role="button", ancestors=["div.toolbar"])
        s = F.similarity(a, b)
        self.assertGreaterEqual(s, F.DEFAULT_THRESHOLD)  # 文本/role/祖先一致，class 不同 -> 仍可自愈
        self.assertLess(s, 1.0)


class TestStoreAndDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch("qa_skill_common.paths.workspace_root", return_value=Path(self.tmp.name))
        self.addCleanup(p.stop)
        p.start()

    def _save(self, name, elements, url="http://mes.example.com/x"):
        page = FakePage(elements=elements, url=url,
                        probe={"total_elements": 1, "iframes": 0, "class_counts": {"el-a": 1}})
        return F.save_fingerprint(page, name), page

    def test_save_creates_file_under_fingerprints(self):
        path, _ = self._save("t1", [elem()])
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "fingerprints")
        self.assertTrue(path.name.endswith(".json"))

    def test_load_roundtrip(self):
        self._save("t2", [elem(text="新增")])
        fp = F.load_fingerprint("t2")
        self.assertEqual(fp["schema_version"], F.SCHEMA_VERSION)
        self.assertEqual(fp["elements"][0]["text"], "新增")

    def test_load_missing_returns_none(self):
        self.assertIsNone(F.load_fingerprint("nope"))

    def test_diff_detects_changed_classes(self):
        self._save("t3", [elem(classes=["action-button"], text="计划切换", role="button",
                               ancestors=["div.toolbar"])])
        page = FakePage(elements=[elem(classes=["op-btn"], text="计划切换", role="button",
                                        ancestors=["div.toolbar"])],
                        url="http://mes.example.com/x")
        d = F.diff_fingerprint(page, "t3")
        self.assertTrue(d["ok"])
        self.assertEqual(d["totals"]["changed"], 1)
        fields = d["changed"][0]["fields"]
        self.assertIn("classes", fields)
        self.assertEqual(fields["classes"]["before"], ["action-button"])
        self.assertEqual(fields["classes"]["after"], ["op-btn"])

    def test_diff_detects_disappeared_and_appeared(self):
        self._save("t4", [elem(classes=["old-btn"], text="旧按钮")])
        page = FakePage(elements=[elem(classes=["new-btn"], text="全新按钮")],
                        url="http://mes.example.com/x")
        d = F.diff_fingerprint(page, "t4")
        self.assertEqual(d["totals"]["disappeared"], 1)
        self.assertEqual(d["totals"]["appeared"], 1)

    def test_diff_rejects_origin_mismatch(self):
        self._save("t5", [elem()], url="http://a.example.com/x")
        page = FakePage(elements=[elem()], url="http://b.example.com/x")
        d = F.diff_fingerprint(page, "t5")
        self.assertFalse(d["ok"])
        self.assertEqual(d["reason"], "origin_mismatch")

    def test_diff_missing_fingerprint(self):
        d = F.diff_fingerprint(FakePage(), "not-exist")
        self.assertFalse(d["ok"])
        self.assertEqual(d["reason"], "fingerprint_not_found")

    def test_containers_are_excluded_from_diff(self):
        """tier=2 的容器噪声大，不参与对比。"""
        self._save("t6", [elem(classes=["wrap"], text="容器", tier=2)])
        page = FakePage(elements=[elem(classes=["gone"], text="容器", tier=2)],
                        url="http://mes.example.com/x")
        d = F.diff_fingerprint(page, "t6")
        self.assertEqual(d["counts"]["before"], 0)
        self.assertEqual(d["totals"]["disappeared"], 0)


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch("qa_skill_common.paths.workspace_root", return_value=Path(self.tmp.name))
        self.addCleanup(p.stop)
        p.start()

    def _save(self, name, elements, url="http://mes.example.com/x"):
        F.save_fingerprint(FakePage(elements=elements, url=url,
                                    probe={"total_elements": 1, "iframes": 0,
                                           "class_counts": {"el-a": 1}}), name)

    def test_exact_selector_wins(self):
        loc = FakeLocator(tag="DIV", cls="action-button")
        page = FakePage(locators={".action-button": loc})
        r = F.resolve(page, selector=".action-button")
        self.assertTrue(r["ok"])
        self.assertEqual(r["via"], "selector")
        self.assertIs(r["locator"], loc)

    def test_exact_text_wins(self):
        loc = FakeLocator()
        page = FakePage(by_text={"新增": loc})
        r = F.resolve(page, text="新增")
        self.assertTrue(r["ok"])
        self.assertEqual(r["via"], "exact")

    def test_fingerprint_heals_when_selector_gone(self):
        self._save("h1", [elem(classes=["action-button"], text="计划切换", role="button",
                               ancestors=["div.toolbar"])])
        page = FakePage(elements=[elem(classes=["op-btn"], text="计划切换", role="button",
                                       ancestors=["div.toolbar"],
                                       path="body > div:nth-child(1) > div:nth-child(1)")],
                        url="http://mes.example.com/x")
        r = F.resolve(page, selector=".action-button", fingerprint="h1")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["via"], "fingerprint")
        self.assertEqual(r["healed_from"], ".action-button")
        self.assertGreaterEqual(r["score"], F.DEFAULT_THRESHOLD)

    def test_ambiguous_returns_candidates_without_picking(self):
        self._save("h2", [elem(classes=["a", "b"], text="重复按钮", role="button")])
        twin = elem(classes=["a", "b"], text="重复按钮", role="button")
        page = FakePage(elements=[dict(twin), dict(twin)], url="http://mes.example.com/x")
        r = F.resolve(page, text="重复按钮", fingerprint="h2")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "ambiguous")
        self.assertGreaterEqual(len(r["candidates"]), 2)

    def test_low_confidence_when_nothing_similar(self):
        self._save("h3", [elem(classes=["alpha"], text="目标按钮", role="button")])
        page = FakePage(elements=[elem(classes=["zzz"], text="完全无关", role="link")],
                        url="http://mes.example.com/x")
        r = F.resolve(page, selector=".alpha", fingerprint="h3")
        self.assertFalse(r["ok"])
        self.assertIn(r["reason"], ("low_confidence", "ambiguous"))

    def test_fingerprint_origin_mismatch_rejected(self):
        self._save("h4", [elem(classes=["a"], text="x")], url="http://a.example.com/x")
        page = FakePage(elements=[elem(classes=["a"], text="x")], url="http://b.example.com/x")
        r = F.resolve(page, selector=".a", fingerprint="h4")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "origin_mismatch")

    def test_no_fingerprint_and_no_exact_is_not_found(self):
        r = F.resolve(FakePage(), text="x")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "not_found")


class TestClickVisibleTextHeal(unittest.TestCase):
    """click_visible_text 第 4 级：heal=<指纹名>。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch("qa_skill_common.paths.workspace_root", return_value=Path(self.tmp.name))
        self.addCleanup(p.stop)
        p.start()
        from qa_skill_common import bbt_helpers as H
        self.H = H

    def test_heal_disabled_keeps_old_failure_shape(self):
        page = FakePage()
        page.evaluate = lambda js, arg=None: {"ok": False, "why": "none-visible"}
        r = self.H.click_visible_text(page, "不存在")
        self.assertFalse(r["ok"])
        self.assertEqual(r["via"], "js-text")
        self.assertNotIn("candidates", r)

    def test_heal_used_only_after_all_levels_fail(self):
        F.save_fingerprint(FakePage(elements=[elem(classes=["action-button"], text="计划切换",
                                                       role="button",
                                                       ancestors=["div.toolbar"])]), "hc1")
        page = FakePage(elements=[elem(classes=["op-btn"], text="计划切换", role="button",
                                       ancestors=["div.toolbar"],
                                       path="body > div:nth-child(1)")],
                        url="http://mes.example.com/x")
        # 让三级降级都失败：无 role/text 命中，JS 兜底返回 none-visible
        page.evaluate = lambda js, arg=None: (page._elements if "INTERACTIVE" in js
                                              else {"ok": False, "why": "none-visible"})
        page.locator = lambda sel, **kw: FakeLocator(tag="DIV", cls="op-btn")
        r = self.H.click_visible_text(page, "计划切换", heal="hc1")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["via"], "heal:hc1")
        self.assertIn("score", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
