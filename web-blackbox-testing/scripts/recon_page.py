# -*- coding: utf-8 -*-
"""统一页面侦察器（web-blackbox-testing 配套）。

一次输出页面关键结构，避免多轮碎片化侦察：
    python recon_page.py [URL] [--new-tab] [--out 目录] [--cdp 端口]

输出：URL / 标题 / 登录态 / 筛选控件 / 按钮 / 表格列头 / 可见弹窗字段映射。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bbt_helpers import connect, disconnect, snap  # noqa: E402


def recon(page, url=None, out_dir=None, feature="recon"):
    """对当前页（或跳转到 url）做一次完整结构侦察。"""
    if url:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
    print("URL:", page.url)
    print("TITLE:", page.title())

    u = page.locator("input[name=username], input[type=password]")
    print("登录态:", "需要登录（存在用户名/密码框）" if u.count() else "已登录或无需登录")

    print("---输入框（前 12）---")
    for i in range(min(page.locator("input").count(), 12)):
        inp = page.locator("input").nth(i)
        try:
            ph = inp.get_attribute("placeholder") or ""
            v = inp.input_value()
            print(f"  input[{i}] ph={ph} value={v!r}")
        except Exception:
            pass
    print("---按钮（前 20）---")
    for b in page.locator("button").all()[:20]:
        try:
            t = b.inner_text().strip()
            if t:
                print(" ", repr(t[:40]))
        except Exception:
            pass
    print("---表格列头---")
    ths = page.locator(".el-table th")
    cols = []
    for i in range(ths.count()):
        try:
            t = ths.nth(i).inner_text().strip()
            if t:
                cols.append(t)
        except Exception:
            pass
    print(" ", " | ".join(cols) if cols else "（无表格或表头为空）")

    print("---可见弹窗---")
    found = False
    for i in range(page.locator("[role=dialog]").count()):
        d = page.locator("[role=dialog]").nth(i)
        try:
            if d.is_visible():
                found = True
                print(f"  dialog[{i}]:", d.inner_text().replace(chr(10), " | ")[:400])
                items = d.locator(".ones-form-item, .el-form-item")
                for j in range(items.count()):
                    it = items.nth(j)
                    try:
                        lab = it.locator(".ones-form-item-label, .el-form-item__label").inner_text().strip()
                    except Exception:
                        lab = ""
                    if lab:
                        print(f"    字段: {lab}")
        except Exception:
            pass
    if not found:
        print("  （无可见弹窗）")

    if out_dir:
        p = snap(page, "recon", out_dir, feature=feature)
        print("截图:", p)


def main():
    ap = argparse.ArgumentParser(description="统一页面侦察器")
    ap.add_argument("url", nargs="?", help="目标 URL（缺省用当前页）")
    ap.add_argument("--new-tab", action="store_true", help="开新标签页（干净状态）")
    ap.add_argument("--out", default=None, help="截图输出目录")
    ap.add_argument("--cdp", default="http://127.0.0.1:9334", help="CDP 地址")
    args = ap.parse_args()

    pw, browser, ctx, page = connect(args.cdp, new_page=args.new_tab)
    try:
        recon(page, url=args.url, out_dir=args.out)
    finally:
        disconnect(pw)


if __name__ == "__main__":
    main()
