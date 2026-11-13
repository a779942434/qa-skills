# -*- coding: utf-8 -*-
"""ONES 两阶段提交 / 账本 / 描述图片渲染态校验离线单测。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ones_submission import (  # noqa: E402
    STATE_ATTACHED,
    STATE_CREATED,
    STATE_INLINE_PENDING,
    SubmissionLedger,
    image_figure,
    image_report,
    is_placeholder_src,
    merge_description_images,
    normalize_title,
    parse_html_images,
    submission_key,
)
from qa_skill_common import bug_report_schema as schema  # noqa: E402


class TestKeysAndLedger(unittest.TestCase):
    def test_normalize_and_stable_key(self):
        self.assertEqual(normalize_title("  A   B  "), "A B")
        self.assertEqual(
            submission_key("p", "BUG-ZZ-001", " 标题  A "),
            submission_key("p", "BUG-ZZ-001", "标题 A"),
        )
        self.assertNotEqual(
            submission_key("p", "BUG-ZZ-001", "标题"),
            submission_key("q", "BUG-ZZ-001", "标题"),
        )

    def test_ledger_roundtrip_and_idempotent_upsert(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            ledger = SubmissionLedger(path, "parent-1")
            ledger.upsert("BUG-ZZ-001", "标题", evidence_files=["/tmp/a.png"])
            ledger.mark("BUG-ZZ-001", STATE_CREATED, number="1", task_uuid="task-1")
            ledger.mark("BUG-ZZ-001", STATE_INLINE_PENDING, inline_message="later")
            self.assertTrue(path.exists())
            again = SubmissionLedger(path, "parent-1")
            rec = again.get("BUG-ZZ-001")
            self.assertEqual(rec["task_uuid"], "task-1")
            self.assertEqual(rec["state"], STATE_INLINE_PENDING)
            self.assertEqual([r["bug_key"] for r in again.pending_inline()], ["BUG-ZZ-001"])
            # upsert 不丢已有字段
            again.upsert("BUG-ZZ-001", "标题", attachment_files=["/tmp/a.png"])
            self.assertEqual(again.get("BUG-ZZ-001")["task_uuid"], "task-1")

    def test_ledger_rejects_other_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            SubmissionLedger(path, "parent-1").mark("BUG-ZZ-001", STATE_ATTACHED)
            with self.assertRaises(RuntimeError):
                SubmissionLedger(path, "parent-2")

    def test_find_by_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SubmissionLedger(Path(tmp) / "ledger.json", "p")
            ledger.mark("BUG-ZZ-001", STATE_ATTACHED)
            ledger.upsert("BUG-ZZ-001", "  同一   标题 ")
            self.assertEqual(ledger.find_by_title("同一 标题")["bug_key"], "BUG-ZZ-001")


class TestDescriptionImages(unittest.TestCase):
    def test_placeholder_detection(self):
        for src in ("", "data:image/gif;base64,xx", "blob:http://x/y"):
            self.assertTrue(is_placeholder_src(src), src)
        self.assertFalse(is_placeholder_src("https://x/a.png"))

    def test_parse_filename_data_uuid(self):
        html = (
            '<figure><img src="https://x/a.png" data-uuid="R1" '
            'data-filename="a.png"></figure>'
            '<img src="data:image/gif;base64,xx" data-uuid="R2" alt="b.png">'
        )
        images = parse_html_images(html)
        self.assertEqual([x["resource_uuid"] for x in images], ["R1", "R2"])
        self.assertEqual(images[0]["filename"], "a.png")
        self.assertEqual(images[1]["filename"], "b.png")
        self.assertTrue(images[1]["placeholder"])

    def test_merge_dedup_and_reject_placeholder(self):
        current = '<figure><img src="https://x/a.png" data-uuid="R1" data-filename="a.png"></figure>'
        merged = merge_description_images(
            current,
            [{"name": "a.png", "resource_uuid": "R1", "url": "https://x/a.png"},
             {"name": "b.png", "resource_uuid": "R2", "url": "https://x/b.png"}],
            ref_id="task-1",
        )
        self.assertEqual(merged.count("<img"), 2)
        self.assertIn("https://x/b.png", merged)
        self.assertIn('data-ref-id="task-1"', merged)
        with self.assertRaises(ValueError):
            merge_description_images(current, [{"name": "c.png", "url": "data:image/gif;base64,xx"}])

    def test_image_report_rendered_state(self):
        html = (
            '<img src="https://x/a.png" data-uuid="R1" data-filename="a.png">'
            '<img src="data:image/gif;base64,xx" data-uuid="R2">'
        )
        report = image_report(html, [{"src": "https://x/a.png", "ok": True, "naturalWidth": 10}])
        self.assertFalse(report["ok"])
        self.assertEqual(report["count"], 2)
        self.assertEqual(len(report["placeholder"]), 1)
        good = image_report('<img src="https://x/a.png" data-filename="a.png">',
                            [{"src": "https://x/a.png", "ok": True, "naturalWidth": 10}])
        self.assertTrue(good["ok"])
        broken = image_report('<img src="https://x/a.png">',
                              [{"src": "https://x/a.png", "ok": False, "naturalWidth": 0}])
        self.assertFalse(broken["ok"])
        self.assertEqual(len(broken["broken"]), 1)

    def test_figure_rejects_placeholder(self):
        with self.assertRaises(ValueError):
            image_figure("data:image/gif;base64,xx", "R1", "a.png")


class TestSchemaCompat(unittest.TestCase):
    def test_no_colon_heading_and_bold_fields(self):
        md = """# 缺陷清单

### BUG-ZZ-001 子表顺序为空排在最前
- **严重程度**：一般
- **操作步骤**：1. 新增
- **预期结果**：排最后
- **证据**：`74_child_copy_row.png`；接口快照。
"""
        result = schema.parse(md)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["bugs"]), 1)
        bug = result["bugs"][0]
        self.assertEqual(bug["key"], "BUG-ZZ-001")
        self.assertEqual(bug["severity"], "一般")
        self.assertIn("74_child_copy_row.png", bug["evidence"])


class PhaseATest(unittest.TestCase):
    def test_phase_a_attaches_evidence_before_return(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        import ones_submit_defects as cli
        with tempfile.TemporaryDirectory() as td:
            ledger = cli.SubmissionLedger(Path(td) / "ledger.json", "PARENT")
            bug = {"key": "BUG-ZZ-001", "title": "标题"}
            files = [Path(td) / "a.png"]
            bug["evidence"] = ["a.png"]

            def fake_create(page, team, parent, title, fvs, **kwargs):
                kwargs["on_created"]("214454", "TASK-UUID")
                return "214454", "TASK-UUID"

            with mock.patch.object(cli, "create_linked_defect", fake_create), \
                 mock.patch.object(cli, "attach_evidence", return_value=(True, "ok")) as attach:
                rec = cli._phase_a_one(
                    None, "TEAM", "PARENT", bug, [], files, {"uuid": "USER"},
                    "SCOPE", ledger,
                )
            self.assertEqual(rec["number"], "214454")
            self.assertEqual(ledger.get("BUG-ZZ-001")["state"], cli.STATE_ATTACHED)
            attach.assert_called_once()

    def test_phase_a_skips_attachment_when_already_attached(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        import ones_submit_defects as cli
        with tempfile.TemporaryDirectory() as td:
            ledger = cli.SubmissionLedger(Path(td) / "ledger.json", "PARENT")
            bug = {"key": "BUG-ZZ-001", "title": "标题"}
            ledger.mark("BUG-ZZ-001", cli.STATE_ATTACHED, number="214454",
                        task_uuid="TASK-UUID", attachment_files=["a.png"])
            with mock.patch.object(cli, "attach_evidence") as attach:
                rec = cli._phase_a_one(
                    None, "TEAM", "PARENT", bug, [], [Path("a.png")],
                    {"uuid": "USER"}, "SCOPE", ledger,
                )
            self.assertEqual(rec["uuid"], "TASK-UUID")
            attach.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
