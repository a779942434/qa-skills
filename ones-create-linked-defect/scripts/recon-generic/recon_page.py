# -*- coding: utf-8 -*-
"""通用页面侦察：dump URL/标题/按钮/表格/行/可见弹窗。
用法: python recon_page.py --url <页面URL>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from bbt_osd_common import login_ousida, goto
from bbt_helpers import recon_page_structure


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1680, "height": 950}, locale="zh-CN").new_page()
        try:
            login_ousida(page)
            goto(page, args.url)
            s = recon_page_structure(page)
            print("URL:", s["url"])
            print("TITLE:", s["title"])
            print("按钮:", json.dumps(s["buttons"], ensure_ascii=False))
            print("表头:", s["headers"])
            print("行数:", len(s["rows"]))
            for r in s["rows"]:
                print("  行:", r)
            print("弹窗:")
            for d in s["dialogs"]:
                print("  ", d)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
