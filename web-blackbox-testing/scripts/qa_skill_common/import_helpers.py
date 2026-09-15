# -*- coding: utf-8 -*-
"""导入边界执行器：混合文件、部分成功、失败文件下载与解析。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook

from .api_wait import ApiWatcher
from .bbt_helpers import close_surface_stack, wait_dialog_open


@dataclass(frozen=True)
class ImportCase:
    case_id: str
    label: str
    row: list
    expected: str = "failure"  # success / failure
    expected_message: str = ""
    duplicate_of: str = ""


def write_import_workbook(path, headers, cases_or_rows) -> Path:
    """写出导入文件；元素可为 ImportCase 或普通 row。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for item in cases_or_rows:
        row = item.row if isinstance(item, ImportCase) else item
        ws.append(list(row))
    wb.save(target)
    return target


def parse_failed_import(path) -> list[dict]:
    """解析失败文件，最后非空列为失败内容。"""
    ws = load_workbook(path, data_only=True).active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    if not rows:
        return []
    headers = [str(x or "").strip() for x in rows[0]]
    out = []
    for values in rows[1:]:
        if not any(v not in (None, "") for v in values):
            continue
        item = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
        item["_raw"] = values
        item["_message"] = str(values[-1] or "").strip() if values else ""
        out.append(item)
    return out


def validate_import_result(result: dict, expected_success: int = None,
                           expected_failed: int = None,
                           required_messages: list[str] = None) -> dict:
    data = (result.get("response_data") or result.get("result") or {})
    success = int(data.get("successCount") or 0)
    failed = int(data.get("failedCount") or 0)
    messages = [
        str(x.get("msg", ""))
        for x in (data.get("failedMessageList") or [])
        if isinstance(x, dict)
    ]
    checks = {
        "success_count": expected_success is None or success == expected_success,
        "failed_count": expected_failed is None or failed == expected_failed,
        "messages": all(any(needle in msg for msg in messages) for needle in (required_messages or [])),
    }
    return {"ok": all(checks.values()), "checks": checks, "success": success,
            "failed": failed, "messages": messages}


def _terminal_import_response(response) -> bool:
    try:
        if "simpleExcel/task/findOne" not in response.url or int(response.status) >= 400:
            return False
        data = (response.json() or {}).get("data") or {}
        return data.get("status") not in (None, 0, 1)
    except Exception:
        return False


def run_import(page, file_path, *, tab_text=None, dialog_timeout=8,
               result_timeout=45, download_failed=True, failed_path=None) -> dict:
    """执行 Element Plus 导入并等待 terminal findOne 返回。

    上传后若页面存在“新增导入/开始导入/确定”按钮则点击；否则依赖 change 自动触发。
    """
    if tab_text:
        tab = page.locator(".el-tabs__item", has_text=tab_text).first
        if tab.count():
            tab.click()
            page.wait_for_timeout(700)
    caret = page.locator("button.el-dropdown__caret-button:visible").first
    caret.wait_for(state="visible", timeout=5000)
    page.wait_for_timeout(150)
    caret.click()
    page.wait_for_timeout(250)
    menu = page.locator(".el-dropdown-menu__item:visible", has_text="导入 Excel").first
    try:
        menu.wait_for(state="visible", timeout=1500)
    except Exception:
        caret.click()
        page.wait_for_timeout(250)
        menu.wait_for(state="visible", timeout=5000)
    menu.click()
    wait_dialog_open(page, dialog_timeout)
    dialog = page.locator(".el-overlay-dialog:visible:has(input[type=file])").last
    dialog.wait_for(state="visible", timeout=int(float(dialog_timeout) * 1000))
    watcher = ApiWatcher(page)
    input_el = dialog.locator("input[type=file]").first

    def action():
        input_el.set_input_files(str(file_path))
        page.wait_for_timeout(250)
        for text in ("新增导入", "开始导入", "确定"):
            btn = dialog.get_by_role("button", name=text, exact=True)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=2500)
                break

    try:
        result = watcher.wait_action(
            action, url_contains="simpleExcel/task/findOne",
            predicate=_terminal_import_response, timeout=result_timeout,
        )
    finally:
        watcher.close()
    if not result:
        return {"ok": False, "reason": "terminal_result_timeout", "file": str(file_path)}
    response = result[0] if isinstance(result, list) else result
    # wait_action returns a Network-style dict; read the terminal body from the page response is not
    # available there, so use a fresh matching request after the fact when needed.
    current = page.locator(".el-overlay-dialog:visible").last
    text = ""
    try:
        text = (current.inner_text() or "").strip()
    except Exception:
        pass
    out = {
        "ok": True,
        "file": str(file_path),
        "network": response,
        "dialog_text": text,
        "response_data": {},
        "failed_file": "",
        "failed_rows": [],
    }
    m = re.search(r"成功(\d+)条", text)
    if m:
        out["response_data"]["successCount"] = m.group(1)
    m = re.search(r"失败(\d+)条", text)
    if m:
        out["response_data"]["failedCount"] = m.group(1)
    messages = []
    for row_no, msg in re.findall(r"第(\d+)行\s+(.+?)(?=\s+第\d+行|\s+下载失败文件|$)", text):
        messages.append({"row": f"第{row_no}行", "msg": msg.strip()})
    out["response_data"]["failedMessageList"] = messages
    if download_failed and "下载失败文件" in text:
        btn = current.get_by_role("button", name="下载失败文件", exact=True)
        if btn.count() and btn.first.is_visible():
            target = Path(failed_path) if failed_path else Path(file_path).with_name(
                Path(file_path).stem + "_导入失败.xlsx"
            )
            try:
                with page.expect_download(timeout=20000) as info:
                    btn.first.click()
                info.value.save_as(str(target))
                out["failed_file"] = str(target)
                out["failed_rows"] = parse_failed_import(target)
            except Exception as exc:
                out["download_error"] = str(exc)[:300]
    close_surface_stack(page, timeout=4)
    return out
