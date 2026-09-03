# -*- coding: utf-8 -*-
"""通用下拉选项侦察：打开指定按钮后 dump 弹窗第一个下拉的可见选项。
通过兼容入口运行：`python scripts/recon-generic/recon_dropdown.py --url <页面URL> --button 新增`。
"""
import argparse
import json

from playwright.sync_api import sync_playwright

from ..bbt_osd_common import goto, login_for_page
from ..bbt_helpers import launch_mes_browser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--button", default="新增")
    args = ap.parse_args()
    with sync_playwright() as pw:
        browser = launch_mes_browser(pw)
        page = browser.new_context(viewport={"width": 1680, "height": 950}, locale="zh-CN").new_page()
        try:
            login_for_page(page, args.url)
            goto(page, args.url)
            page.locator(f"button:has-text('{args.button}')").first.click()
            page.wait_for_timeout(1800)
            page.locator(".el-dialog .el-select__wrapper").first.click()
            page.wait_for_timeout(800)
            opts = page.locator(".el-select-dropdown__item:visible").all_inner_texts()
            print("下拉选项:", json.dumps([o.strip() for o in opts if o.strip()], ensure_ascii=False))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
