# -*- coding: utf-8 -*-
"""L1 离线单测：站点/页面注册表（两级可信度 + 一致性校验 + 容错）。

运行：python3 -m unittest discover -s qa_skill_common/tests -t . -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import page_registry as R  # noqa: E402

HOST = "http://t-dafu.ob.shuyilink.com"
FEAT = "月度工序计划"


class TestHostAndPaths(unittest.TestCase):
    def test_host_of(self):
        self.assertEqual(R.host_of("http://t-dafu.ob.shuyilink.com/plan/x"), HOST)
        self.assertEqual(R.host_of("https://a.b/c"), "https://a.b")
        self.assertEqual(R.host_of("not a url"), "")

    def test_safe_host_for_fingerprint_name(self):
        self.assertEqual(R.fingerprint_name(HOST, FEAT),
                         "http_t-dafu.ob.shuyilink.com#月度工序计划")


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = mock.patch("qa_skill_common.paths.workspace_root", return_value=self.root)
        self.addCleanup(p.stop)
        p.start()

    def test_upsert_creates_file_under_sites(self):
        path = R.upsert_page(HOST, FEAT, url=HOST + "/plan/monthly/index", verified=True,
                             title="月度工序计划", probe_verdict="element-plus")
        self.assertTrue(path.exists())
        self.assertEqual(path.parent.name, "sites")
        entry = R.get_page(HOST, FEAT)
        self.assertTrue(entry["verified"])
        self.assertEqual(entry["title"], "月度工序计划")
        self.assertEqual(entry["hits"], 1)

    def test_repeat_upsert_no_duplicate_and_hits_increment(self):
        R.upsert_page(HOST, FEAT, url=HOST + "/a", verified=True)
        R.upsert_page(HOST, FEAT, url=HOST + "/a", verified=True)
        data = R.load(HOST)
        self.assertEqual(len(data["pages"]), 1)
        self.assertEqual(R.get_page(HOST, FEAT)["hits"], 2)

    def test_upsert_preserves_existing_intel(self):
        R.upsert_page(HOST, FEAT, url=HOST + "/a", verified=True,
                      title="月度工序计划", gotchas=["分单号要手动输入"],
                      selectors={"新增按钮": "button:has-text('新增')"})
        R.upsert_page(HOST, FEAT, url=HOST + "/a", verified=True)
        e = R.get_page(HOST, FEAT)
        self.assertEqual(e["title"], "月度工序计划")
        self.assertEqual(e["gotchas"], ["分单号要手动输入"])
        self.assertIn("新增按钮", e["selectors"])

    def test_upsert_syncs_features_cache(self):
        R.upsert_page(HOST, FEAT, url=HOST + "/a", verified=True)
        cache = json.loads((self.root / ".cache" / "features.json").read_text(encoding="utf-8"))
        self.assertEqual(cache["{}|{}".format(HOST, FEAT)], HOST + "/a")

    def test_corrupt_json_self_heals(self):
        p = R.registry_path(HOST)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ this is not json", encoding="utf-8")
        data = R.load(HOST)                      # 不得抛错
        self.assertEqual(data["pages"], {})
        R.upsert_page(HOST, FEAT, url=HOST + "/a", verified=True)
        self.assertTrue(R.get_page(HOST, FEAT))


class TestTwoLevelTrust(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch("qa_skill_common.paths.workspace_root",
                       return_value=Path(self.tmp.name))
        self.addCleanup(p.stop)
        p.start()

    def test_observed_only_entry_not_directly_trusted(self):
        R.upsert_page(HOST, FEAT, url=HOST + "/maybe", verified=False)
        entry = R.get_page(HOST, FEAT)
        self.assertFalse(entry["verified"])
        self.assertFalse(R.should_direct_goto(entry))

    def test_verified_entry_allows_direct_goto(self):
        R.upsert_page(HOST, FEAT, url=HOST + "/ok", verified=True)
        self.assertTrue(R.should_direct_goto(R.get_page(HOST, FEAT)))

    def test_mark_stale_downgrades_verified(self):
        R.upsert_page(HOST, FEAT, url=HOST + "/ok", verified=True)
        R.mark_stale(HOST, FEAT, reason="标题不一致")
        entry = R.get_page(HOST, FEAT)
        self.assertFalse(entry["verified"])
        self.assertTrue(entry["stale"])
        self.assertFalse(R.should_direct_goto(entry))

    def test_upsert_clears_stale_flag(self):
        R.upsert_page(HOST, FEAT, url=HOST + "/ok", verified=True)
        R.mark_stale(HOST, FEAT)
        R.upsert_page(HOST, FEAT, url=HOST + "/ok", verified=True)
        self.assertNotIn("stale", R.get_page(HOST, FEAT))


class TestConsistency(unittest.TestCase):
    def test_title_match_is_ok(self):
        e = {"title": "月度 工序计划", "probe_verdict": "element-plus"}
        self.assertEqual(R.check_consistency(e, title="月度工序计划"), "ok")

    def test_known_verdict_match_is_ok(self):
        e = {"probe_verdict": "element-plus"}
        self.assertEqual(R.check_consistency(e, probe_verdict="element-plus"), "ok")

    def test_verdict_mismatch_is_stale(self):
        e = {"probe_verdict": "element-plus"}
        self.assertEqual(R.check_consistency(e, probe_verdict="vxe-table"), "stale")

    def test_unreliable_verdict_never_counts_as_ok(self):
        e = {"probe_verdict": "unknown"}
        self.assertEqual(R.check_consistency(e, probe_verdict="unknown"), "unknown")

    def test_no_comparable_info_is_unknown(self):
        self.assertEqual(R.check_consistency({}, title="x"), "unknown")

    def test_title_mismatch_without_verdict_is_stale(self):
        """标题可比但不等、又没有 verdict 兜底 -> 判失效（保守方向：宁可重侦察）。"""
        e = {"title": "月度工序计划"}
        self.assertEqual(R.check_consistency(e, title="完全不同的页面"), "stale")

    def test_verdict_match_rescues_title_change(self):
        """标题可能带动态后缀；组件库判定一致即可信任。"""
        e = {"title": "月度工序计划", "probe_verdict": "element-plus"}
        self.assertEqual(R.check_consistency(e, title="月度工序计划 - 编辑",
                                             probe_verdict="element-plus"), "ok")


class TestRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch("qa_skill_common.paths.workspace_root",
                       return_value=Path(self.tmp.name))
        self.addCleanup(p.stop)
        p.start()

    def test_render_is_short_and_marks_state(self):
        R.upsert_page(HOST, FEAT, url=HOST + "/a", verified=True,
                      gotchas=["分单号手动输入"])
        R.upsert_page(HOST, "另一个功能", url=HOST + "/b", verified=False)
        text = R.render_for_prompt(HOST)
        self.assertLessEqual(len(text.splitlines()), 10)
        self.assertIn("已验证", text)
        self.assertIn("仅观测", text)

    def test_render_missing_feature_says_need_recon(self):
        self.assertIn("未登记", R.render_for_prompt(HOST, "没测过的功能"))

    def test_pages_for_unknown_host(self):
        self.assertIsNone(R.pages_for("not a url"))


if __name__ == "__main__":
    unittest.main()
