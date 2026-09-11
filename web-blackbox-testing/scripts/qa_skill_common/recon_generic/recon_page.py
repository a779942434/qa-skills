# -*- coding: utf-8 -*-
"""通用页面侦察：dump URL/标题/按钮/表格/行/可见弹窗。

通过兼容入口运行：`python scripts/recon-generic/recon_page.py --url <页面URL>`。

限量与检索（2026-09-11，借鉴 playwright-cli 的 `snapshot --depth` / `find <text>`）：
  --limit N     表格行等列表的显示上限（默认 50；<=0 表示不截断）
  --find TEXT   只在侦察结果里检索该文本，只输出命中项（不 dump 全量，省 token）
  --json        以 JSON 输出完整结构（含 counts），便于程序与下游消费
"""
import argparse
import json

from playwright.sync_api import sync_playwright

from ..bbt_helpers import launch_mes_browser, recon_page_structure
from ..bbt_osd_common import goto, login_for_page

# 参与 --find 检索的字段（顺序即输出顺序）
_FIND_KEYS = ("buttons", "headers", "rows", "dialogs", "inputs")
_KEY_LABEL = {"buttons": "按钮", "headers": "表头", "rows": "行",
              "dialogs": "弹窗", "inputs": "输入框"}


def _as_text(item):
    return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


def find_in_structure(s, needle):
    """在侦察结果里做子串检索，返回 [(字段, 序号, 文本), ...]。

    对应 playwright-cli 的 `find <text>`：大页面只回传命中节点，不 dump 全量。
    """
    hits = []
    for key in _FIND_KEYS:
        for i, item in enumerate(s.get(key) or []):
            text = _as_text(item)
            if needle in text:
                hits.append((key, i, text))
    return hits


def render_text(s):
    """把侦察结果渲染成默认文本输出（含 counts 截断提示）。"""
    counts = s.get("counts") or {}
    rows = s.get("rows") or []
    lines = [
        "URL: {}".format(s.get("url", "")),
        "TITLE: {}".format(s.get("title", "")),
        "按钮: {}".format(json.dumps(s.get("buttons") or [], ensure_ascii=False)),
        "表头: {}".format(s.get("headers") or []),
    ]
    total = counts.get("rows", len(rows))
    shown = len(rows)
    lines.append("行数: {}".format(total) + ("（显示前 {}）".format(shown) if total > shown else ""))
    for r in rows:
        lines.append("  行: {}".format(r))
    lines.append("弹窗:")
    for d in s.get("dialogs") or []:
        lines.append("  {}".format(d))
    extra = {k: v for k, v in counts.items() if k in ("buttons", "inputs", "dialogs") and v}
    if extra:
        lines.append("计数: " + ", ".join("{}={}".format(_KEY_LABEL.get(k, k), v) for k, v in extra.items()))
    return "\n".join(lines)


def render_find(s, needle):
    """把 --find 的命中渲染成文本。"""
    hits = find_in_structure(s, needle)
    lines = ["URL: {}".format(s.get("url", "")), "TITLE: {}".format(s.get("title", "")),
             "检索 {!r}：命中 {} 项".format(needle, len(hits))]
    for key, i, text in hits:
        lines.append("  [{}#{}] {}".format(_KEY_LABEL.get(key, key), i, text))
    return "\n".join(lines)


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--limit", type=int, default=50,
                    help="表格行等列表的显示上限（默认 50；<=0 表示不截断）")
    ap.add_argument("--find", default=None,
                    help="只在侦察结果里检索该文本，只输出命中项（省 token）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出完整结构")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    with sync_playwright() as pw:
        browser = launch_mes_browser(pw)
        page = browser.new_context(viewport={"width": 1680, "height": 950}, locale="zh-CN").new_page()
        try:
            login_for_page(page, args.url)
            goto(page, args.url)
            s = recon_page_structure(page, max_rows=args.limit)
            if args.json:
                print(json.dumps(s, ensure_ascii=False, indent=2))
            elif args.find:
                print(render_find(s, args.find))
            else:
                print(render_text(s))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
