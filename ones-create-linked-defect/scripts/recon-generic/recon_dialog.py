# -*- coding: utf-8 -*-
"""通用弹窗字段侦察：打开指定按钮后 dump 表单字段结构（label + 控件类型）。
用法: python recon_dialog.py --url <页面URL> --button 新增
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright
from bbt_osd_common import login_ousida, goto


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--button", default="新增")
    args = ap.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1680, "height": 950}, locale="zh-CN").new_page()
        try:
            login_ousida(page)
            goto(page, args.url)
            page.locator(f"button:has-text('{args.button}')").first.click()
            page.wait_for_timeout(2000)
            data = page.evaluate(
                """() => {
                    const ds=[...document.querySelectorAll('[role=dialog],.el-dialog,.el-drawer')].filter(d=>{const r=d.getBoundingClientRect();return r.width>0&&r.height>0;});
                    const d=ds[ds.length-1];
                    return {
                        text:(d.innerText||'').trim().replace(/\\n+/g,' | ').slice(0,1200),
                        items:[...d.querySelectorAll('.el-form-item')].map((it,i)=>({i,label:(it.querySelector('.el-form-item__label')||{}).innerText||'',hasSelect:!!it.querySelector('.el-select'),inputs:[...it.querySelectorAll('input')].map(x=>x.type)}))
                    };
                }"""
            )
            print("弹窗文本:", data["text"])
            print("字段:")
            for it in data["items"]:
                print(f"  [{it['i']}] {it['label']} select={it['hasSelect']} inputs={it['inputs']}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
