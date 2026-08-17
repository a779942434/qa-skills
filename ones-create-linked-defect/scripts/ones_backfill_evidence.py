# -*- coding: utf-8 -*-
"""给已建缺陷补传/回填证据文件。

用法:
    python scripts/ones_backfill_evidence.py --team 2YPZxEgX --defect <缺陷uuid> 文件1 文件2 ...
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ones_helpers import connect, disconnect, resolve_settings


def attach_files(page, team_uuid, defect_uuid, files):
    base = resolve_settings()["ones_url"].rstrip("/")
    page.goto(f"{base}/project/#/team/{team_uuid}/task/{defect_uuid}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    page.evaluate(
        """() => {
            let target = null;
            const walk = (el) => {
                if (target) return;
                if (el.childElementCount === 0 && el.textContent && el.textContent.trim() === '文件') { target = el; return; }
                for (const c of el.children) walk(c);
            };
            walk(document.body);
            if (!target) return false;
            let p = target;
            while (p && p !== document.body && !p.onclick && !p.closest('[class*=tab]')) p = p.parentElement;
            (p && p !== document.body ? p : target).click();
            return true;
        }"""
    )
    page.wait_for_timeout(3000)
    up = page.locator("input.upload-input")
    if up.count() == 0:
        return False, "未找到上传控件"
    up.first.set_input_files([str(f) for f in files])
    page.wait_for_timeout(3000)
    for _ in range(6):
        clicked = page.evaluate(
            """() => {
                const ds = Array.from(document.querySelectorAll('[role=dialog]'));
                for (const d of ds) {
                    const r = d.getBoundingClientRect();
                    const t = (d.innerText || '');
                    if (r.width > 0 && r.height > 0 && t.includes('上传文件') && !t.includes('选择关联关系')) {
                        const btn = Array.from(d.querySelectorAll('button')).find(b => (b.innerText || '').trim() === '确定');
                        if (btn) { btn.click(); return true; }
                    }
                }
                return false;
            }"""
        )
        if clicked:
            page.wait_for_timeout(3000)
            return True, "已确认上传"
        time.sleep(1)
    return True, "未出现上传确认弹窗（可能已直接挂载）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", required=True)
    ap.add_argument("--defect", required=True, help="缺陷任务 uuid")
    ap.add_argument("files", nargs="+", help="要补传的文件路径")
    args = ap.parse_args()

    missing = [f for f in args.files if not Path(f).exists()]
    if missing:
        raise SystemExit("文件不存在: " + ", ".join(missing))

    pw, browser, ctx, page = connect()
    try:
        ok, msg = attach_files(page, args.team, args.defect, args.files)
        print(f"补传结果: {ok} {msg} ({len(args.files)} 个文件)")
    finally:
        disconnect(pw)


if __name__ == "__main__":
    main()
