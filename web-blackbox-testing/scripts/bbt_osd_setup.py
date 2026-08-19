# -*- coding: utf-8 -*-
"""欧斯达造数入口：一次登录按依赖顺序造 产品 → 工艺路线(工序) → BOM（幂等）。

用法:
    python scripts/bbt_osd_setup.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.sync_api import sync_playwright
from bbt_osd_common import login_ousida, ensure_product, ensure_craft, ensure_proc, ensure_bom

PRODUCT = "测试产品-QA0818"
CODE = "QA0818"
ROUTE = "测试工艺QA"
PROCS = [("注塑", "1"), ("装配", "2")]
BOMS = [("增白剂", 1, 2), ("DWY125K-01上盖", 1, 1)]


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1680, "height": 950}, locale="zh-CN").new_page()
        try:
            login_ousida(page)
            ensure_product(page, PRODUCT, CODE)
            ensure_craft(page, PRODUCT, ROUTE)
            ensure_proc(page, ROUTE, PROCS)
            ensure_bom(page, PRODUCT, BOMS)
            print("\n造数完成")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
