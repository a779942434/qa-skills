# -*- coding: utf-8 -*-
"""ONES 一键提缺陷 CLI（整合字段缓存 + 登录账号 + 默认严重程度 + 页面复用）。

用法:
    python scripts/ones_submit_defects.py --bug-report <缺陷清单.md> --work-order <工单URL> --profile ousida

优化点:
    - 只用 get_task_required_fields() 提取建缺陷必填字段，不搬运完整描述；
    - 负责人/验证人自动取当前 ONES 登录账号（get_current_user）；
    - 严重程度默认「一般」（黑盒报告的 S1~S4 仅自用，不据此定级）；
    - issue_type_scope_uuid 优先从 profile 读取（换项目只改 field-mapping.yaml）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ones_config import load_field_mapping  # noqa: E402
from ones_helpers import (  # noqa: E402
    DEFAULT_SEVERITY,
    _api,
    build_defect_fields,
    connect,
    create_linked_defect,
    dedup_check,
    disconnect,
    get_current_user,
    get_parent_handlers,
    get_task_required_fields,
    list_related_tasks,
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
    text = Path(md_path).read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^### ", text)
    bugs = []
    for b in blocks[1:]:
        m = re.match(r"(BUG-[A-Za-z0-9-]+)[：:]\s*(.+)", b.strip())
        if not m:
            continue
        key, title = m.group(1), m.group(2).strip()
        evidence = []
        for em in re.finditer(r"(?m)^\s*[-*]\s*(.+)$", b):
            line = re.sub(r"^证据[:：]\s*", "", em.group(1).strip())
            for tok in re.split(r"[\s、,，]+", line):
                tok = tok.strip()
                if re.search(r"\.(?:png|jpg|jpeg|gif|xlsx|csv|txt)$", tok, re.IGNORECASE):
                    evidence.append(tok)
        bugs.append({"key": key, "title": title, "evidence": evidence, "desc": b.strip()})
    return bugs


def profile_overrides(profile):
    ov = {}
    if not profile:
        return ov
    src = profile.get("source_project") or {}
    cust = profile.get("source_customer") or {}
    env = profile.get("system_env") or {}
    mod = profile.get("function_module") or {}
    for fu, v in (
        ("5nUKjALP", src.get("option_uuid")),
        ("Jtnem8qs", cust.get("option_uuid")),
        ("R3UqL3Vm", env.get("option_uuid")),
        ("W9qkyVXr", mod.get("option_uuid")),
        ("field012", profile.get("priority_uuid")),
    ):
        if v:
            ov[fu] = v
    return ov


def check_profile(profile):
    """校验 profile 必需字段是否齐全，返回警告列表。"""
    warnings = []
    if not profile:
        return ["未指定 --profile，字段依赖主工单兜底，缺陷类型 scope 可能缺失"]
    src = profile.get("source_project") or {}
    env = profile.get("system_env") or {}
    mod = profile.get("function_module") or {}
    checks = [
        ("来源项目 option_uuid", src.get("option_uuid")),
        ("系统环境 option_uuid", env.get("option_uuid")),
        ("功能模块 option_uuid", mod.get("option_uuid")),
        ("优先级 priority_uuid", profile.get("priority_uuid")),
        ("缺陷类型 issue_type_scope_uuid", profile.get("issue_type_scope_uuid")),
    ]
    for label, v in checks:
        if not v:
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
        tokens = [t for t in re.split(r"\s+", name) if t]
        hit = False
        for token in tokens:
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
    import time as _time
    from ones_helpers import resolve_settings
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
            const ct = (p && p !== document.body) ? p : target;
            ct.click();
            return true;
        }"""
    )
    page.wait_for_timeout(3000)
    up = page.locator("input.upload-input")
    if up.count() == 0:
        return False, "未找到上传控件"
    up.first.set_input_files([str(f) for f in files])
    page.wait_for_timeout(2500)
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
        _time.sleep(1)
    return True, "未出现上传确认弹窗（可能已直接挂载）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bug-report", required=True, help="缺陷清单 md 路径")
    ap.add_argument("--work-order", required=True, help="ONES 工单 URL")
    ap.add_argument("--profile", default=None, help="field-mapping.yaml 项目段名（如 ousida）")
    ap.add_argument("--sample-defect", default=None, help="可选：字段模板缺陷 uuid")
    ap.add_argument("--only", action="append", default=[], help="只提交指定编号，可重复")
    ap.add_argument("--bugs", default="", help="逗号分隔编号，支持数字简写")
    ap.add_argument("--handler", choices=["backend", "frontend"], default="backend", help="处理人：后端/前端（默认后端）")
    ap.add_argument("--severity", default=DEFAULT_SEVERITY, help="严重程度（默认一般）")
    ap.add_argument("--dry-run", action="store_true", help="只解析校验不建单")
    ap.add_argument("--skip-evidence", action="store_true", help="跳过证据补传")
    args = ap.parse_args()

    team, task = parse_work_order(args.work_order)
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
    overrides = profile_overrides(profile)
    scope_uuid = (profile or {}).get("issue_type_scope_uuid")
    profile_warnings = check_profile(profile)
    evidence_base = [str(Path(args.bug_report).resolve().parent)]
    if profile and profile.get("site", {}).get("evidence_dir"):
        proj_root = Path(__file__).resolve().parent.parent
        evidence_base.insert(0, str(proj_root / profile["site"]["evidence_dir"]))

    print("解析到缺陷:", ", ".join(b["key"] for b in bugs))
    print("字段覆盖表:", json.dumps(overrides, ensure_ascii=False))
    print("issue_type_scope_uuid:", scope_uuid or "(未配置)")
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
        req = get_task_required_fields(page, team, task)
        print("主工单:", req["number"], req["summary"])
        front_uuid, back_uuid = get_parent_handlers(page, team, task)
        handler = front_uuid if args.handler == "frontend" else (back_uuid or front_uuid)
        current = get_current_user(page)
        print("当前登录账号:", current["name"], current["uuid"], "| 处理人:", handler)

        if not scope_uuid and args.sample_defect:
            sr = _api(page, "POST", f"/project/api/project/team/{team}/tasks/info", {"ids": [args.sample_defect]})
            st = (sr or {}).get("tasks", [{}])[0]
            scope_uuid = st.get("issue_type_scope_uuid")
            print("样例缺陷 scope:", scope_uuid)

        results = []
        for b in bugs:
            fvs = build_defect_fields(
                page, team, task, b["title"], b["desc"], handler,
                sample_defect_uuid=args.sample_defect,
                overrides=overrides,
                severity_text=args.severity,
            )
            number, uuid = create_linked_defect(
                page, team, task, b["title"], fvs,
                assign=current["uuid"], issue_type_scope_uuid=scope_uuid,
            )
            print(f"  {b['key']} 已创建 #{number} uuid={uuid}")
            results.append({"key": b["key"], "number": number, "uuid": uuid})
            if not args.skip_evidence:
                files, _missing = resolve_evidence(b, evidence_base)
                if files:
                    ok, msg = attach_evidence(page, team, uuid, files)
                    print(f"    证据补传: {ok} {msg} ({len(files)} 个文件)")

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
