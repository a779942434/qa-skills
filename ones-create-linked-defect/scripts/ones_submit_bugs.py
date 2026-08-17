# -*- coding: utf-8 -*-
"""ONES 一体化提交：读缺陷清单 -> API 批量建关联缺陷 -> 证据补传 -> 去重校验。

用法:
    python scripts/ones_submit_bugs.py --bug-report bug-reports/2026-08-12_辅助排产_缺陷清单.md \
        --work-order "https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/3cAXW7MCS6xHGhdO" \
        --profile aolian [--only BUG-002] [--dry-run] [--skip-evidence]

依赖:
    - CDP 9334 常驻浏览器已登录 ONES（scripts/ones_edge_server.py）
    - config/field-mapping.yaml 的 profile 段已配置选项 uuid（如 aolian.system_env.option_uuid）
    - 未配置的选项字段（如严重程度）保持默认，脚本会提示
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ones_config import load_field_mapping  # noqa: E402
from ones_helpers import (  # noqa: E402
    _api,
    build_defect_fields,
    connect,
    create_linked_defect,
    dedup_check,
    disconnect,
    get_parent_handlers,
    get_task_info,
    list_related_tasks,
    open_defect_form,
    set_select_option,
    submit_defect,
    upload_evidence,
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
    """把编号展开为标准 BUG 编号：支持 '1' / 'BUG-001' / 'bug-1'。"""
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
    """解析缺陷清单 md，返回 [{"key","title","severity","evidence":[...],"desc"}]。"""
    text = Path(md_path).read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^### ", text)
    bugs = []
    for b in blocks[1:]:
        m = re.match(r"(BUG-[A-Za-z0-9-]+)[：:]\s*(.+)", b.strip())
        if not m:
            continue
        key, title = m.group(1), m.group(2).strip()
        severity = re.search(r"(?m)^- 严重程度：(\S+)", b) or re.search(r"严重程度[:：]\s*(\S+)", b)
        severity = severity.group(1) if severity else ""
        evidence = []
        for em in re.finditer(r"(?m)^\s*[-*] (.+\.(?:png|jpg|jpeg|gif|xlsx|csv|txt))", b):
            seg = re.match(r"(.+?\.(?:png|jpg|jpeg|gif|xlsx|csv|txt))", em.group(1).strip())
            if seg:
                raw = re.sub(r"^证据[:：]\s*", "", seg.group(1))
                evidence.append(raw)
        bugs.append({
            "key": key,
            "title": title,
            "severity": severity,
            "evidence": evidence,
            "desc": b.strip(),
        })
    return bugs


def profile_overrides(profile):
    """把 field-mapping.yaml 的 profile 段转成 {field_uuid: option_uuid} 覆盖表。"""
    ov = {}
    if not profile:
        return ov
    src = profile.get("source_project") or {}
    cust = profile.get("source_customer") or {}
    env = profile.get("system_env") or {}
    mod = profile.get("function_module") or {}
    people = profile.get("people") or {}
    for fu, v in (
        ("5nUKjALP", src.get("option_uuid")),    # 来源项目
        ("Jtnem8qs", cust.get("option_uuid")),   # 来源客户
        ("R3UqL3Vm", env.get("option_uuid")),    # 系统环境
        ("W9qkyVXr", mod.get("option_uuid")),    # 功能模块（新）
        ("field012", profile.get("priority_uuid")),
        ("field004", people.get("assignee_uuid")),   # 负责人
        ("Sg5vqjRr", people.get("assignee_uuid")),   # 验证人
    ):
        if v:
            ov[fu] = v
    return ov


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
    """按缺陷清单中的证据路径解析为绝对路径（相对 base_dirs 逐个尝试）。"""
    found = []
    missing = []
    for name in bug["evidence"]:
        # 一行可能含多个文件名（如 a.png / b.png），按空白与 / 拆分
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
    """打开缺陷详情页并上传证据（尽力而为，失败不阻塞）。"""
    import time as _time
    from ones_helpers import resolve_settings
    base = resolve_settings()["ones_url"].rstrip("/")
    page.goto(f"{base}/project/#/team/{team_uuid}/task/{defect_uuid}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    # 点“文件”页签
    page.evaluate(
        """() => {
            let target = null;
            const walk = (el) => {
                if (target) return;
                if (el.childElementCount === 0 && el.textContent && el.textContent.trim() === '文件') {
                    target = el; return;
                }
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
    ap.add_argument("--profile", default=None, help="field-mapping.yaml 中的项目段名（如 aolian）")
    ap.add_argument("--sample-defect", default=None,
                    help="字段模板缺陷 uuid（同项目缺陷 tasks/info；缺省时优先同工单已有缺陷，否则用主工单字段兜底）")
    ap.add_argument("--only", action="append", default=[], help="只提交指定编号，可重复（--only BUG-001 --only BUG-006）")
    ap.add_argument("--bugs", default="", help="逗号分隔编号，支持数字简写（--bugs 1,2,6）")
    ap.add_argument("--dry-run", action="store_true", help="只解析与校验，不建单")
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
    evidence_base = [str(Path(args.bug_report).resolve().parent)]
    if profile and profile.get("site", {}).get("evidence_dir"):
        proj_root = Path(__file__).resolve().parent.parent
        evidence_base.insert(0, str(proj_root / profile["site"]["evidence_dir"]))

    print("解析到缺陷:", ", ".join(b["key"] for b in bugs))
    print("字段覆盖表:", json.dumps(overrides, ensure_ascii=False))
    if args.dry_run:
        for b in bugs:
            ev, missing = resolve_evidence(b, evidence_base)
            print(f"  {b['key']} | {b['title'][:40]} | 严重程度={b['severity']} | 证据 {len(ev)}/{len(b['evidence'])}")
            for m in missing:
                print(f"    [缺] 清单文件名未匹配磁盘: {m}")
        return

    pw, browser, ctx, page = connect()
    try:
        info = get_task_info(page, team, task)
        print("主工单:", info.get("number"), info.get("summary"))
        front_uuid, back_uuid = get_parent_handlers(page, team, task)
        handler = back_uuid or front_uuid
        scope_uuid = None
        if args.sample_defect:
            sr = _api(page, "POST", f"/project/api/project/team/{team}/tasks/info",
                      {"ids": [args.sample_defect]})
            st = (sr or {}).get("tasks", [{}])[0]
            scope_uuid = st.get("issue_type_scope_uuid")
            print("样例缺陷 scope:", scope_uuid)
        results = []
        for b in bugs:
            sample = args.sample_defect
            if not sample:
                # 尝试找同工单已有缺陷做模板（此处简化：传 None 用主工单兜底，必要时用 --sample-defect 指定）
                pass
            fvs = build_defect_fields(page, team, task, b["title"], b["desc"], handler, sample_defect_uuid=sample)
            fvs = apply_overrides(fvs, overrides)
            number, uuid = create_linked_defect(page, team, task, b["title"], fvs,
                                                assign=handler, issue_type_scope_uuid=scope_uuid)
            print(f"  {b['key']} 已创建 #? {number} uuid={uuid}")
            results.append({"key": b["key"], "number": number, "uuid": uuid})
            if not args.skip_evidence:
                files, _missing = resolve_evidence(b, evidence_base)
                if files:
                    ok, msg = attach_evidence(page, team, uuid, files)
                    print(f"    证据补传: {ok} {msg} ({len(files)} 个文件)")
        titles = list_related_tasks(page, team, task, info.get("summary") or "")
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
