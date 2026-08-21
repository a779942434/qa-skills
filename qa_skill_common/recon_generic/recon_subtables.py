# -*- coding: utf-8 -*-
"""通用主子表侦察：点击每行主表行，dump 出现的子表（按表头）。
通过兼容入口运行：`python scripts/recon-generic/recon_subtables.py --url <页面URL> --max-rows 5`。
"""
import argparse

from playwright.sync_api import sync_playwright

from ..bbt_osd_common import goto, login_ousida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--max-rows", type=int, default=5)
    args = ap.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1680, "height": 950}, locale="zh-CN").new_page()
        try:
            login_ousida(page)
            goto(page, args.url)
            n = page.locator(".el-table__row").count()
            print("主表行数:", n)
            for i in range(min(n, args.max_rows)):
                page.locator(".el-table__row").nth(i).locator("td").nth(1).click()
                page.wait_for_timeout(2000)
                print(f"===== 第{i+1}行 =====")
                tables = page.evaluate(
                    """() => Array.from(document.querySelectorAll('.el-table')).map(t=>({
                        hdr:Array.from(t.querySelectorAll('th')).map(x=>(x.innerText||'').trim()).filter(Boolean),
                        rows:Array.from(t.querySelectorAll('.el-table__row')).map(r=>(r.innerText||'').trim().replace(/\\n+/g,' | '))
                    }))"""
                )
                for t in tables:
                    if t["hdr"]:
                        print("表头:", t["hdr"])
                        for r in t["rows"]:
                            print("   ", r)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
