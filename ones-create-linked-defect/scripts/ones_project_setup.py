# -*- coding: utf-8 -*-
"""ONES 新项目接入：一次脚本自动发现字段并写入 field-mapping.yaml 的新 profile。

用法:
    python ones_project_setup.py --work-order <工单URL> --profile <新项目名> \\
        [--env-keyword ousida] [--sample-defect <历史缺陷uuid>] [--site-url http://...] [--dry-run]
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml

from ones_config import PROJECT_ROOT
from ones_helpers import (
    _api,
    capture_field_options_fiber,
    connect,
    disconnect,
    get_parent_context,
    open_defect_form,
)


def parse_work_order(url):
    m = re.search(r"/team/([A-Za-z0-9]+)/task/([A-Za-z0-9]{8,})", url)
    if not m:
        raise SystemExit("无法从工单 URL 解析 team/task：" + url)
    return m.group(1), m.group(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-order", required=True)
    ap.add_argument("--profile", required=True, help="field-mapping.yaml 里的新 profile 名")
    ap.add_argument("--env-keyword", default="", help="系统环境搜索关键词（如 ousida），用于捕获系统环境 uuid")
    ap.add_argument("--sample-defect", default="", help="同团队任一历史缺陷 uuid，用于取 issue_type_scope_uuid")
    ap.add_argument("--site-url", default="", help="被测系统地址（可选）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将写入的 profile，不落盘")
    args = ap.parse_args()

    team, task = parse_work_order(args.work_order)
    pw, browser, ctx, page = connect()
    try:
        req, _ = get_parent_context(page, team, task)
        f = req["fields"]
        print("主工单:", req["number"], req["summary"])

        profile = {
            "site": {"url": args.site_url, "feature": req["summary"]},
            "source_project": {"keyword": "", "option_uuid": f["source_project"]},
            "source_customer": {"option_uuid": f["source_customer"]},
            "function_module": {"keyword": "", "name": "", "option_uuid": f["function_module"]},
            "priority": "P2",
            "priority_uuid": f["priority"],
            "people": {
                "product_owner_uuid": f["product_owner"],
                "backend": f["backend"],
                "frontend": f["frontend"],
            },
        }

        if args.env_keyword:
            dlg = open_defect_form(page, team, task, req["summary"] or "")
            opts = capture_field_options_fiber(page, "系统环境", args.env_keyword)
            env = next((o for o in opts if args.env_keyword in o["text"]), None)
            if env:
                profile["system_env"] = {"keyword": args.env_keyword, "name": env["text"], "option_uuid": env["uuid"]}
                print("系统环境:", env["text"], env["uuid"])
            else:
                print("[警告] 未匹配到系统环境选项，请检查 --env-keyword 或手工补")

        if args.sample_defect:
            sr = _api(page, "POST", f"/project/api/project/team/{team}/tasks/info", {"ids": [args.sample_defect]})
            st = (sr or {}).get("tasks", [{}])[0]
            scope = st.get("issue_type_scope_uuid")
            if scope:
                profile["issue_type_scope_uuid"] = scope
                print("缺陷 scope:", scope)
            else:
                print("[警告] 样例缺陷未取到 issue_type_scope_uuid")

        if args.dry_run:
            print("=== dry-run profile ===")
            print(yaml.safe_dump({args.profile: profile}, allow_unicode=True, sort_keys=False))
            return

        path = PROJECT_ROOT / "config" / "field-mapping.local.yaml"
        block = yaml.safe_dump({args.profile: profile}, allow_unicode=True, sort_keys=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n# ============ {args.profile}（由 ones_project_setup 生成，请补 keyword/site.url） ============\n")
            fh.write(block)
        print("已写入 profile:", args.profile, "->", path)
        print("提示：检查 field-mapping.local.yaml 新增段，补 source_project.keyword、function_module.keyword/name 等可读字段。")
    finally:
        disconnect(pw)


if __name__ == "__main__":
    main()
