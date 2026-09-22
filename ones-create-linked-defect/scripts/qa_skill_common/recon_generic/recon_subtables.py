# -*- coding: utf-8 -*-
"""通用主子表侦察：点击每行主表行，dump 出现的子表（按表头）。
通过兼容入口运行：`python scripts/recon-generic/recon_subtables.py --url <页面URL> --max-rows 5`。
"""
import argparse

from playwright.sync_api import sync_playwright

from ..bbt_osd_common import goto, login_for_page
from ..bbt_helpers import wait_gone
from ..bbt_helpers import launch_mes_browser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--max-rows", type=int, default=5)
    ap.add_argument("--full", action="store_true", help="不截断（旧行为）")
    ap.add_argument("--out-dir", default=None, help="截断时完整结构的落盘目录")
    args = ap.parse_args()
    with sync_playwright() as pw:
        browser = launch_mes_browser(pw)
        page = browser.new_context(viewport={"width": 1680, "height": 950}, locale="zh-CN").new_page()
        try:
            login_for_page(page, args.url)
            goto(page, args.url)
            n = page.locator(".el-table__row").count()
            collected = []
            if args.full:
                print("主表行数:", n)
            for i in range(min(n, args.max_rows)):
                page.locator(".el-table__row").nth(i).locator("td").nth(1).click()
                wait_gone(page, ".el-loading-mask", timeout=5)   # 替代固定 2s
                if args.full:
                    print(f"===== 第{i+1}行 =====")
                tables = page.evaluate(
                    """() => Array.from(document.querySelectorAll('.el-table')).map(t=>({
                        hdr:Array.from(t.querySelectorAll('th')).map(x=>(x.innerText||'').trim()).filter(Boolean),
                        rows:Array.from(t.querySelectorAll('.el-table__row')).map(r=>(r.innerText||'').trim().replace(/[\\n\\t]+/g,' | '))
                    }))"""
                )
                for t in tables:
                    if t["hdr"]:
                        collected.append({"row": i + 1, "hdr": t["hdr"], "rows": t["rows"]})
                        if args.full:
                            print("表头:", t["hdr"])
                            for r in t["rows"]:
                                print("   ", r)
            if not args.full:
                from .. import output as _O
                payload = {"url": page.url, "title": page.title(),
                           "main_rows": n, "tables": collected}
                print(_O.emit(payload, kind="recon_subtables", max_chars=2000,
                              out_dir=args.out_dir, name=_O.safe_name("subtables")))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
