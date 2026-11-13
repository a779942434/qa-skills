# -*- coding: utf-8 -*-
"""qa_case 新增动作的离线单测：不启动浏览器，用小型 fake 验证调用契约。"""
import sys
import tempfile
import unittest
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import case_cli as C  # noqa: E402


class FakeLocator:
    def __init__(self, *, count=1, rows=None):
        self._count = count
        self._rows = rows or []
        self.clicked = 0
        self.hovered = 0
        self.files = []

    def count(self):
        return self._count

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def set_input_files(self, files):
        self.files.append(files)

    def click(self, **kwargs):
        self.clicked += 1

    def hover(self, **kwargs):
        self.hovered += 1

    def filter(self, **kwargs):
        return self

    def locator(self, selector):
        return self


class FakePage:
    def __init__(self, file_input=None, rows=None):
        self.file_input = file_input or FakeLocator()
        self.rows = rows or {}

    def locator(self, selector):
        if selector == "input[type=file]":
            return self.file_input
        return self.rows.get(selector, FakeLocator())


class FakeDownload:
    suggested_filename = "导出结果.xlsx"

    def __init__(self):
        self.saved = []

    def save_as(self, path):
        Path(path).write_text("fake", encoding="utf-8")
        self.saved.append(path)


class FakeDownloadInfo:
    def __init__(self, download):
        self.value = download


class FakeDownloadContext:
    def __init__(self, download):
        self.download = download

    def __enter__(self):
        return FakeDownloadInfo(self.download)

    def __exit__(self, *args):
        return False


class TestNewActions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "evidence"
        self.out.mkdir()

    def run_step(self, page, step, state=None):
        return C._run_step(page, object(), step, 0, self.out, "C01", "示例",
                           state if state is not None else {})

    def test_upload_sets_file_input(self):
        source = Path(self.tmp.name) / "导入.xlsx"
        source.write_text("x", encoding="utf-8")
        page = FakePage()
        ok, detail, ev = self.run_step(page, {"action": "upload", "file": str(source)})
        self.assertTrue(ok)
        self.assertEqual(page.file_input.files, [str(source)])
        self.assertEqual(detail["file"], str(source))
        self.assertEqual(ev, "")

    def test_dialog_sets_scope_and_body_resets(self):
        state = {}
        with mock.patch("qa_skill_common.bbt_helpers.dialog_by_title", return_value=object()):
            ok, detail, _ = self.run_step(page=FakePage(), step={"action": "dialog", "text": "新增"}, state=state)
        self.assertTrue(ok)
        self.assertIn(".el-dialog:visible", state["scope"])
        self.run_step(page=FakePage(), step={"action": "body"}, state=state)
        self.assertEqual(state["scope"], "body")

    def test_hover_click_and_upload_scope_paths(self):
        page = FakePage()
        target = FakeLocator()
        with mock.patch.object(C, "_visible_text_locator", return_value=target):
            ok, _, _ = self.run_step(page, {"action": "hover", "text": "详情"})
        self.assertTrue(ok)
        self.assertEqual(target.hovered, 1)

    def test_row_select_prefers_checkbox(self):
        checkbox = FakeLocator()
        row = FakeLocator()
        row.locator = lambda selector: checkbox
        page = FakePage(rows={".el-table__row": row})
        # filter() 由 FakeLocator 返回自身，row 仍可提供 checkbox locator
        ok, detail, _ = self.run_step(page, {"action": "row_select", "text": "订单A"})
        self.assertTrue(ok)
        self.assertEqual(checkbox.clicked, 1)
        self.assertEqual(detail["via"], "checkbox")

    def test_wait_toast(self):
        with mock.patch("qa_skill_common.bbt_helpers.wait_toast", return_value=True):
            ok, detail, _ = self.run_step(FakePage(), {"action": "wait_toast", "text": "保存成功"})
        self.assertTrue(ok)
        self.assertEqual(detail["text"], "保存成功")

    def test_expect_download_saves_to_evidence(self):
        page = FakePage()
        download = FakeDownload()
        page.expect_download = lambda timeout: FakeDownloadContext(download)
        with mock.patch.object(C, "_visible_text_locator", return_value=FakeLocator()):
            ok, detail, evidence = self.run_step(page, {"action": "expect_download", "text": "导出"})
        self.assertTrue(ok)
        self.assertTrue(Path(evidence).exists())
        self.assertEqual(Path(evidence).read_text(encoding="utf-8"), "fake")
        self.assertEqual(detail["suggested_filename"], "导出结果.xlsx")


class _FakeContext:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_context(self, **kwargs):
        return self

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _FakeExecPage:
    url = "http://fixture.test/"

    def wait_for_timeout(self, ms):
        pass

    def title(self):
        return "fixture"


class TestExecCoverageWriteback(unittest.TestCase):
    def test_exec_writes_case_id_and_status_to_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            steps = Path(tmp) / "steps.json"
            steps.write_text(json.dumps({"steps": [{"action": "sleep", "ms": 1}]}),
                             encoding="utf-8")
            page = _FakeExecPage()
            fake_pw = _FakeContext(object())
            buffer = io.StringIO()
            with mock.patch("playwright.sync_api.sync_playwright", return_value=fake_pw), \
                 mock.patch("qa_skill_common.bbt_helpers.launch_mes_browser", return_value=_FakeBrowser(page)), \
                 mock.patch("qa_skill_common.bbt_helpers.configure_page_timeouts"), \
                 mock.patch("qa_skill_common.bbt_helpers.attach_error_watchers"), \
                 mock.patch("qa_skill_common.api_wait.ApiWatcher"), \
                 mock.patch.object(C, "_read_fb", return_value={"toasts": [], "form_errors": []}):
                with redirect_stdout(buffer):
                    rc = C.main([
                        "exec", "--steps", str(steps), "--run-dir", str(run_dir),
                        "--case-id", "C01", "--priority", "P1", "--requirement", "R-01",
                        "--oracle-mode", "api",
                    ])
            self.assertEqual(rc, 0, buffer.getvalue())
            coverage = json.loads((run_dir / "coverage.json").read_text(encoding="utf-8"))
            self.assertEqual(coverage["cases"][0]["id"], "C01")
            self.assertEqual(coverage["cases"][0]["status"], "通过")
            contract = json.loads((run_dir / "contract.json").read_text(encoding="utf-8"))
            self.assertEqual(contract["requirements"][0]["case_ids"], ["C01"])


if __name__ == "__main__":
    unittest.main()
