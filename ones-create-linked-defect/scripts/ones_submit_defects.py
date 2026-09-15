# -*- coding: utf-8 -*-
"""ONES 一键提缺陷 CLI（整合字段缓存 + 登录账号 + 默认严重程度 + 页面复用）。

用法:
    python scripts/ones_submit_defects.py --bug-report <缺陷清单.md> --work-order <工单URL>
        [--profile <项目名>] [--system-env <环境名或uuid>]

优化点:
    - 只用 get_task_required_fields() 提取建缺陷必填字段，不搬运完整描述；
    - 负责人/验证人自动取当前 ONES 登录账号（get_current_user）；
    - 严重程度默认「一般」（黑盒报告的 S1~S4 仅自用，不据此定级）；
    - issue_type_scope_uuid 优先从 profile 读取，缺失时按项目+缺陷类型直接发现；
    - 不再依赖“先找一张历史缺陷再复制”，历史缺陷只保留为显式兜底。
"""
import argparse
import json
import glob
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_skill_common import bug_report_schema as bug_schema  # noqa: E402
from qa_skill_common import paths as qa_paths  # noqa: E402
from qa_skill_common.bbt_helpers import wait_app_ready
from ones_config import load_field_mapping  # noqa: E402
from ones_helpers import (  # noqa: E402
    DEFAULT_SEVERITY,
    build_defect_fields,
    connect,
    create_linked_defect,
    dedup_check,
    disconnect,
    get_current_user,
    get_issue_type_fields,
    get_issue_type_scope,
    get_parent_context,
    list_related_tasks,
    upload_task_evidences_api,
)


def parse_work_order(url):
    m = re.search(r"/team/([A-Za-z0-9]+)/task/([A-Za-z0-9]{8,})", url)
    if not m:
        m = re.search(r"/team/([A-Za-z0-9]+)/.*?/task/([A-Za-z0-9]{8,})", url)
    if not m:
        m = re.search(r"team=([A-Za-z0-9]+).*?task=([A-Za-z0-9]{8,})", url)
    if not m:
        raise SystemExit("无法从工单 URL 解析 team/task：" + url)
    return m.group(1), m.group(2)


def expand_keys(tokens):
    keys = set()
    for tok in tokens:
        tok = str(tok).strip()
        if not tok:
            continue
        m = re.fullmatch(r"(?:bug[-_]?)?(\d+)", tok, re.IGNORECASE)
        if m:
            keys.add(f"BUG-{int(m.group(1)):03d}")
        else:
            keys.add(tok.upper())
    return keys


def parse_bug_report(md_path):
    """解析缺陷清单（契约单一来源：qa_skill_common.bug_report_schema）。

    标题格式 `### BUG-编号：标题`；字段与证据行规则见 schema；
    解析出错时打印 [清单校验] 提示（不静默丢字段）。
    """
    text = Path(md_path).read_text(encoding="utf-8")
    result = bug_schema.parse(text)
    for err in result["errors"]:
        print(f"[清单校验] {err}", file=sys.stderr)
    return result["bugs"]


def resolve_option_uuid(field_defs, field_uuid, wanted):
    """把选项 uuid 或可读名称解析为 uuid；未提供字段定义时按 uuid 原样使用。"""
    if not wanted:
        return None
    if not field_defs:
        return wanted
    fd = next((f for f in field_defs if f.get("uuid") == field_uuid), None)
    if not fd:
        raise RuntimeError(f"字段定义中未找到 {field_uuid}")
    options = fd.get("options") or []
    exact_uuid = [o for o in options if o.get("uuid") == wanted]
    if exact_uuid:
        return exact_uuid[0]["uuid"]
    wanted_l = str(wanted).strip().lower()
    exact_name = [o for o in options if str(o.get("value") or "").strip().lower() == wanted_l]
    if len(exact_name) == 1:
        return exact_name[0]["uuid"]
    contains = [o for o in options if wanted_l in str(o.get("value") or "").lower()]
    if len(contains) == 1:
        return contains[0]["uuid"]
    if not contains:
        raise RuntimeError(f"字段 {fd.get('name') or field_uuid} 未找到选项: {wanted}")
    raise RuntimeError(
        f"字段 {fd.get('name') or field_uuid} 匹配到多个选项: "
        + ", ".join(str(o.get("value")) for o in contains)
    )


def profile_overrides(profile, field_defs=None):
    """将 profile 中的 uuid 或可读名称解析成 field_values 覆盖值。"""
    ov = {}
    if not profile:
        return ov
    src = profile.get("source_project") or {}
    cust = profile.get("source_customer") or {}
    env = profile.get("system_env") or {}
    mod = profile.get("function_module") or {}

    def first(section):
        return section.get("option_uuid") or section.get("name") or section.get("keyword")

    for fuuid, wanted in (
        ("5nUKjALP", first(src)),
        ("Jtnem8qs", first(cust)),
        ("R3UqL3Vm", first(env)),
        ("W9qkyVXr", first(mod)),
        ("field012", profile.get("priority_uuid") or profile.get("priority")),
    ):
        value = resolve_option_uuid(field_defs, fuuid, wanted)
        if value:
            ov[fuuid] = value
    return ov


def check_profile(profile):
    """校验 profile 可选字段，返回非阻塞警告列表。"""
    warnings = []
    if not profile:
        return ["未指定 --profile；scope 可自动发现，但系统环境等缺陷特有字段需由主工单、--system-env 或 sample 提供"]
    src = profile.get("source_project") or {}
    env = profile.get("system_env") or {}
    mod = profile.get("function_module") or {}

    def has_value(section):
        return bool(section.get("option_uuid") or section.get("name") or section.get("keyword"))

    checks = [
        ("来源项目 option_uuid/name/keyword", has_value(src)),
        ("系统环境 option_uuid/name/keyword", has_value(env)),
        ("功能模块 option_uuid/name/keyword", has_value(mod)),
        ("优先级 priority_uuid/priority", bool(profile.get("priority_uuid") or profile.get("priority"))),
    ]
    for label, ok in checks:
        if not ok:
            warnings.append(f"缺少 {label}")
    return warnings

def apply_overrides(field_values, overrides):
    out = []
    for f in field_values:
        fu = f.get("field_uuid")
        if fu in overrides:
            f = dict(f)
            f["value"] = overrides[fu]
        out.append(f)
    return out


def resolve_evidence(bug, base_dirs):
    found, missing = [], []
    for name in bug["evidence"]:
        # 支持多个文件用 空格/中英文顿号逗号分号 分隔
        tokens = [t for t in re.split(r"[\s、,，;；]+", name) if t]
        hit = False
        for token in tokens:
            # 支持通配符（如 template_*.xlsx / export_*.xlsx）
            if "*" in token or "?" in token:
                resolved = False
                for base in base_dirs:
                    hits = sorted(glob.glob(str(Path(base) / token)))
                    if hits:
                        found.extend(Path(h) for h in hits)
                        resolved = True
                        break
                if resolved:
                    hit = True
                continue
            if not re.search(r"\.(?:png|jpg|jpeg|gif|xlsx|csv|txt)$", token):
                continue
            p = Path(token)
            if p.exists():
                found.append(p)
                hit = True
                continue
            for base in base_dirs:
                cand = Path(base) / token
                if cand.exists():
                    found.append(cand)
                    hit = True
                    break
        if not hit:
            missing.append(name)
    return found, missing


def attach_evidence(page, team_uuid, defect_uuid, files):
    """把证据直接绑定到刚创建的 defect_uuid，并以附件接口确认成功。"""
    try:
        ok, _data, missing, uploaded = upload_task_evidences_api(
            page, team_uuid, defect_uuid, files, timeout=90,
        )
    except Exception as exc:
        return False, f"附件接口上传失败: {exc}"
    if ok:
        return True, f"附件接口已确认新增 {len(uploaded)} 个文件"
    return False, f"附件接口超时，缺少: {', '.join(missing)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bug-report", required=True, help="缺陷清单 md 路径")
    ap.add_argument("--work-order", required=True, help="ONES 工单 URL")
    ap.add_argument("--profile", default=None, help="field-mapping.yaml 项目段名（如 <项目名>）")
    ap.add_argument("--sample-defect", default=None, help="可选：字段模板缺陷 uuid（仅显式兜底，不作为常规前置）")
    ap.add_argument("--system-env", default=None, help="系统环境名称或选项 uuid；可替代 profile.system_env.option_uuid")
    ap.add_argument("--only", action="append", default=[], help="只提交指定编号，可重复")
    ap.add_argument("--bugs", default="", help="逗号分隔编号，支持数字简写")
    ap.add_argument("--handler", choices=["backend", "frontend"], help="处理人：后端/前端（默认后端；UI 展示/交互类缺陷提前端）")
    ap.add_argument("--severity", default=DEFAULT_SEVERITY, help="严重程度（默认一般）")
    ap.add_argument("--dry-run", action="store_true", help="只解析校验不建单")
    ap.add_argument("--skip-evidence", action="store_true", help="跳过证据补传")
    args = ap.parse_args()

    team, task = parse_work_order(args.work_order)

    # 清单定位：绝对路径直用；否则在统一产物根 + 历史位置中查找
    resolved = qa_paths.find_bug_report(args.bug_report)
    if resolved is None:
        searched = "\n".join("  - " + str(d) for d in qa_paths.bug_report_search_dirs())
        raise SystemExit(
            f"未找到缺陷清单：{args.bug_report}\n"
            f"可传绝对路径，或把清单放到以下任一目录（或用 ONES_BUG_REPORTS_DIR 指定）：\n{searched}"
        )
    args.bug_report = str(resolved)

    bugs = parse_bug_report(args.bug_report)
    wanted = expand_keys(args.only)
    if args.bugs:
        wanted |= expand_keys(args.bugs.split(","))
    if wanted:
        bugs = [b for b in bugs if b["key"] in wanted]
    if not bugs:
        print("未解析到 BUG 段，请检查缺陷清单格式（### BUG-编号：标题）")
        return

    field_map = load_field_mapping()
    profile = field_map.get(args.profile) if args.profile else None
    feature = (profile or {}).get("site", {}).get("feature", "")
    for b in bugs:
        if feature and not b["title"].startswith("【"):
            b["title"] = f"【{feature}】{b['title']}"
    scope_uuid = (profile or {}).get("issue_type_scope_uuid")
    profile_warnings = check_profile(profile)
    br_dir = Path(args.bug_report).resolve().parent
    evidence_base = [str(br_dir)]
    # web 约定：证据放在 <产物根>/bug-reports/<功能>/，补入一级子目录以便按文件名命中
    try:
        for sub in sorted(br_dir.iterdir()):
            if sub.is_dir():
                evidence_base.append(str(sub))
    except OSError:
        pass
    if profile and profile.get("site", {}).get("evidence_dir"):
        proj_root = Path(__file__).resolve().parent.parent
        evidence_base.insert(0, str(proj_root / profile["site"]["evidence_dir"]))

    print("解析到缺陷:", ", ".join(b["key"] for b in bugs))
    for w in profile_warnings:
        print(f"[警告] {w}")
    if args.dry_run:
        for b in bugs:
            ev, missing = resolve_evidence(b, evidence_base)
            print(f"  {b['key']} | {b['title'][:40]} | 证据 {len(ev)}/{len(b['evidence'])}")
            for m in missing:
                print(f"    [缺] {m}")
        return

    pw, browser, ctx, page = connect()
    try:
        req, parent_fv = get_parent_context(page, team, task)
        print("主工单:", req["number"], req["summary"])
        handler = req["fields"]["frontend"] if args.handler == "frontend" else (req["fields"]["backend"] or req["fields"]["frontend"])
        current = get_current_user(page)
        print("当前登录账号:", current["name"], current["uuid"], "| 处理人:", handler)

        if not scope_uuid:
            scope_uuid = get_issue_type_scope(page, team, req.get("project_uuid"))
            print("issue_type_scope_uuid: 按项目+缺陷类型自动发现")
        else:
            print("issue_type_scope_uuid: profile 配置")
        print("  scope=", scope_uuid)

        field_defs = get_issue_type_fields(page, team, scope_uuid)
        overrides = profile_overrides(profile, field_defs)
        if args.system_env:
            overrides["R3UqL3Vm"] = resolve_option_uuid(field_defs, "R3UqL3Vm", args.system_env)
        print("字段覆盖表:", json.dumps(overrides, ensure_ascii=False))

        # 先完成字段与证据预检，避免“已建单但证据缺失”的半成品。
        prepared = []
        for b in bugs:
            fvs = build_defect_fields(
                page, team, task, b["title"], b["desc"], handler,
                sample_defect_uuid=args.sample_defect,
                overrides=overrides,
                severity_text=args.severity,
                parent_fv=parent_fv,
                field_defs=field_defs,
            )
            files = []
            if not args.skip_evidence:
                files, ev_missing = resolve_evidence(b, evidence_base)
                if ev_missing:
                    raise RuntimeError(f"{b['key']} 证据文件缺失: {', '.join(ev_missing)}")
            prepared.append((b, fvs, files))

        results = []
        for b, fvs, files in prepared:
            # 创建缺陷、关联主工单、绑定证据按单条缺陷串行完成。
            number, uuid = create_linked_defect(
                page, team, task, b["title"], fvs,
                assign=current["uuid"], issue_type_scope_uuid=scope_uuid,
            )
            print(f"  {b['key']} 已创建并关联 #{number} uuid={uuid}")
            results.append({"key": b["key"], "number": number, "uuid": uuid})
            if files:
                ok, msg = attach_evidence(page, team, uuid, files)
                print(f"    附件绑定: {ok} {msg} ({len(files)} 个文件)")
                if not ok:
                    raise RuntimeError(
                        f"{b['key']} 已创建并关联 #{number} uuid={uuid}，"
                        f"但附件未确认，停止后续建单；请勿重复创建，按此 uuid 重试附件"
                    )

        titles = list_related_tasks(page, team, task, req["summary"] or "")
        dup = dedup_check(titles)
        print("=== 去重校验 ===")
        if dup:
            for t, c in dup.items():
                print(f"  重复 {c} 次: {t[:60]}")
        else:
            print("  无重复")
        print("=== 结果表 ===")
        for r in results:
            print(f"  {r['key']} | {r['number']} | {r['uuid']}")
    finally:
        disconnect(pw)


if __name__ == "__main__":
    main()
