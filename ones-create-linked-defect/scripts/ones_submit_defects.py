# -*- coding: utf-8 -*-
"""ONES 一键提缺陷 CLI（两阶段提交 + 账本幂等 + 渲染态校验）。

用法:
    # Phase A：建单/关联/附件，先拿单号（默认，推荐）
    python scripts/ones_submit_defects.py --bug-report <清单.md> --work-order <工单URL> \
        --profile <项目> --mode fast

    # Phase B：补描述内嵌图（可稍后单独跑；失败不阻塞 Phase A）
    python scripts/ones_submit_defects.py --ledger <账本.json> --work-order <工单URL> \
        --repair-images

    # 只校验账面 + 描述图渲染态
    python scripts/ones_submit_defects.py --ledger <账本.json> --work-order <工单URL> \
        --verify-only

设计约束（2026-11-13 复盘后固化）:
    - 建单与描述美化分离；Phase A 成功即交付单号，Phase B 失败只降级。
    - 每个缺陷有稳定 submission_key；重试先查账本，已有 task_uuid 就复用。
    - 附件走 API 并以附件接口核验；描述图走附件 API + 签名 URL，不再用 CKEditor 图片按钮。
    - 成功判定为渲染态：src 非 data:、浏览器 naturalWidth>0、文件名齐全。
"""
import argparse
import json
import glob
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_skill_common import bug_report_schema as bug_schema  # noqa: E402
from qa_skill_common import oracle  # noqa: E402
from qa_skill_common import paths as qa_paths  # noqa: E402
from qa_skill_common.bbt_helpers import wait_app_ready
from ones_config import load_field_mapping  # noqa: E402
from ones_submission import (  # noqa: E402
    STATE_ATTACHED,
    STATE_CREATED,
    STATE_FAILED,
    STATE_INLINE_OK,
    STATE_INLINE_PENDING,
    STATE_LINKED,
    STATE_VERIFIED,
    SubmissionLedger,
    submission_key,
)
from ones_helpers import (  # noqa: E402
    DEFAULT_SEVERITY,
    append_task_description_images_api,
    build_defect_fields,
    connect,
    create_linked_defect,
    dedup_check,
    disconnect,
    ensure_task_attachment,
    get_current_user,
    get_issue_type_fields,
    get_issue_type_scope,
    get_parent_context,
    get_task_attachments,
    link_task_to_parent,
    list_related_tasks,
    sanitize_text,
    verify_task_description_images,
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


def key_in_wanted(key, wanted):
    if not wanted:
        return True
    upper = str(key).upper()
    if upper in {w.upper() for w in wanted}:
        return True
    for w in wanted:
        m = re.fullmatch(r"BUG[-_]?(\d{1,3})", str(w), re.IGNORECASE)
        if m and upper.endswith(f"-{int(m.group(1)):03d}"):
            return True
    return False


def filter_wanted(bugs, wanted):
    """支持完整 key 与数字后缀简写（BUG-ZZ-001 可写 001）。"""
    if not wanted:
        return bugs
    keys = {b["key"].upper() for b in bugs}
    exact = {w for w in wanted if w.upper() in keys}
    suffixes = set()
    for w in wanted:
        m = re.fullmatch(r"BUG[-_]?(\d{1,3})", w, re.IGNORECASE)
        if m:
            suffixes.add(f"-{int(m.group(1)):03d}")
    return [b for b in bugs
            if b["key"].upper() in exact
            or any(b["key"].upper().endswith(s) for s in suffixes)]


def parse_bug_report(md_path):
    """解析缺陷清单（契约单一来源：qa_skill_common.bug_report_schema）。"""
    text = Path(md_path).read_text(encoding="utf-8")
    result = bug_schema.parse(text)
    for err in result["errors"]:
        print(f"[清单校验] {err}", file=sys.stderr)
    return result["bugs"]


def parse_defects_json(json_path):
    """读取结构化 defects.json，并转换为 ONES 提交所需的 bug 结构。"""
    path = Path(json_path).expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    records = data.get("defects") if isinstance(data, dict) else None
    if records is None:
        raise SystemExit(f"结构化缺陷文件缺少 defects 数组: {path}")
    evidence_items = []
    evidence_path = path.parent / "evidence" / "index.json"
    if evidence_path.exists():
        try:
            evidence_items = json.loads(evidence_path.read_text(encoding="utf-8")).get("items") or []
        except Exception:
            evidence_items = []
    evidence_map = {str(x.get("id")): x for x in evidence_items}
    bugs = []
    for rec in records:
        gate = oracle.validate_defect(rec, strict=False)
        if not gate["ok"]:
            raise SystemExit(
                f"结构化缺陷未通过门槛 {rec.get('id', '')}: " + "; ".join(gate["errors"])
            )
        evidence_files = list(rec.get("evidence_files") or [])
        missing_evidence_ids = []
        for eid in rec.get("evidence_ids") or []:
            item = evidence_map.get(str(eid))
            if not item or not item.get("path"):
                missing_evidence_ids.append(str(eid))
            elif item["path"] not in evidence_files:
                evidence_files.append(item["path"])
        if missing_evidence_ids:
            raise SystemExit(
                f"结构化缺陷证据ID不存在 {rec.get('id', '')}: "
                + ", ".join(missing_evidence_ids)
            )
        evidence_files = list(dict.fromkeys(str(x) for x in evidence_files if x))
        fields = {
            "严重程度": rec.get("severity_local") or rec.get("severity") or "一般",
            "环境": rec.get("environment", "") if isinstance(rec.get("environment"), str)
            else json.dumps(rec.get("environment") or {}, ensure_ascii=False),
            "前置条件": rec.get("preconditions", ""),
            "操作步骤": rec.get("steps", ""),
            "预期结果": rec.get("expected", ""),
            "实际结果": rec.get("actual", ""),
            "复现率": rec.get("reproducibility", ""),
            "证据": " ".join(str(x) for x in evidence_files),
            "需求引用": ", ".join(str(x) for x in (rec.get("requirement_refs") or [])),
            "分类": rec.get("classification", ""),
            "置信度": rec.get("confidence", ""),
            "复现方式": rec.get("reproduction_method", ""),
            "证据ID": ", ".join(str(x) for x in (rec.get("evidence_ids") or [])),
            "ONES单号": rec.get("ones_key", ""),
            "备注": rec.get("notes", ""),
        }
        desc_lines = [f"{k}：{v}" for k, v in fields.items() if v not in (None, "")]
        bugs.append({
            "key": rec.get("id", ""),
            "title": rec.get("title", ""),
            "severity": fields["严重程度"],
            "fields": fields,
            "evidence": evidence_files,
            "desc": "\n".join(desc_lines),
        })
    return bugs, evidence_map


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
        tokens = [t for t in re.split(r"[\s、,，;；]+", name) if t]
        hit = False
        for token in tokens:
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
            if not re.search(r"\.(?:png|jpg|jpeg|gif|xlsx|csv|txt)$", token, re.IGNORECASE):
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
    # 去重并保持顺序，避免同一文件上传两次
    unique = []
    seen = set()
    for p in found:
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique, missing


def attach_evidence(page, team_uuid, defect_uuid, files):
    """幂等上传附件：同名同大小已存在则复用；最终以附件接口文件名核验。"""
    try:
        for path in files:
            ensure_task_attachment(page, team_uuid, defect_uuid, path)
        expected = [Path(p).name for p in files]
        deadline = time.time() + 30
        missing = expected
        while True:
            data = get_task_attachments(page, team_uuid, defect_uuid) or {}
            present = {a.get("name") for a in (data.get("attachments") or [])}
            missing = [n for n in expected if n not in present]
            if not missing or time.time() >= deadline:
                break
            time.sleep(0.6)
        if missing:
            return False, f"附件接口未确认: {', '.join(missing)}"
        return True, f"附件接口已确认 {len(files)} 个文件"
    except Exception as exc:  # noqa: BLE001
        return False, f"附件接口上传失败: {exc}"


def inline_description_evidence(page, team_uuid, defect_uuid, files, timeout=90, number=None):
    """Phase B：附件 API + 签名 URL 写描述，渲染态校验。"""
    images = [Path(p) for p in files
              if Path(p).suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp')]
    if not images:
        return True, '无图片证据，跳过描述内嵌'
    try:
        result = append_task_description_images_api(
            page, team_uuid, defect_uuid, images, timeout=timeout, number=number,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f'描述内嵌图片失败: {exc}'
    if not result.get('verified'):
        return False, f"描述内嵌图片未校验通过: {result.get('report')}"
    report = result.get('report') or {}
    return True, (
        f"描述内嵌图片 {len(result.get('inserted') or [])} 个，"
        f"当前共 {report.get('count', 0)} 张，占位 {len(report.get('placeholder') or [])} 个"
    )


def default_ledger_path(base_dir):
    return Path(base_dir) / "ones-submission-ledger.json"


def find_bug(bugs, key):
    for b in bugs:
        if b["key"] == key:
            return b
    return None


def main():
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=False)
    source.add_argument("--bug-report", help="缺陷清单 md 路径（旧格式兼容）")
    source.add_argument("--defects-json", help="结构化 defects.json（优先入口）")
    ap.add_argument("--work-order", required=True, help="ONES 工单 URL")
    ap.add_argument("--profile", default=None, help="field-mapping.yaml 项目段名（如 <项目名>）")
    ap.add_argument("--sample-defect", default=None, help="可选：字段模板缺陷 uuid（仅显式兜底，不作为常规前置）")
    ap.add_argument("--system-env", default=None, help="系统环境名称或选项 uuid；可替代 profile.system_env.option_uuid")
    ap.add_argument("--only", action="append", default=[], help="只提交指定编号，可重复")
    ap.add_argument("--bugs", default="", help="逗号分隔编号，支持数字简写")
    ap.add_argument("--handler", choices=["backend", "frontend"], help="处理人：后端/前端（默认后端；UI 展示/交互类缺陷提前端）")
    ap.add_argument("--severity", default=DEFAULT_SEVERITY, help="严重程度（默认一般）")
    ap.add_argument("--mode", choices=["fast", "full"], default="fast",
                    help="fast=Phase A 建单/关联/附件后立即返回；full=同时补描述图（默认 fast）")
    ap.add_argument("--ledger", default=None, help="提交账本 JSON；默认 <缺陷清单目录>/ones-submission-ledger.json")
    ap.add_argument("--repair-images", action="store_true", help="Phase B：按账本补描述内嵌图（需 --ledger）")
    ap.add_argument("--verify-only", action="store_true", help="只校验账本/描述图，不建单（需 --ledger）")
    ap.add_argument("--dry-run", action="store_true", help="只解析校验不建单")
    ap.add_argument("--skip-evidence", action="store_true", help="跳过证据补传")
    ap.add_argument("--no-inline-evidence", action="store_true", help="兼容旧参数：只传附件，不内嵌描述")
    ap.add_argument("--no-redact", action="store_true",
                    help="关闭描述净化（默认过滤本地路径/账号密码/租户标注等只应留在本地的信息）")
    ap.add_argument("--redact-pattern", action="append", default=None,
                    help="追加净化规则，形如 '正则==替换文本'，可重复（与 profile.redact.patterns 合并）")
    ap.add_argument("--inline-timeout", type=float, default=90, help="描述内嵌图片超时秒数（默认90）")
    args = ap.parse_args()

    team, task = parse_work_order(args.work_order)
    phase_b_only = bool(args.repair_images or args.verify_only)
    if phase_b_only and not args.ledger:
        raise SystemExit("--repair-images / --verify-only 必须显式指定 --ledger")
    if not phase_b_only and not (args.bug_report or args.defects_json):
        raise SystemExit("创建缺陷必须提供 --bug-report 或 --defects-json")

    bugs = []
    evidence_base = []
    br_dir = None
    if not phase_b_only:
        if args.defects_json:
            source_path = Path(args.defects_json).expanduser()
            if not source_path.is_absolute():
                source_path = Path.cwd() / source_path
            if not source_path.exists():
                raise SystemExit(f"未找到结构化缺陷文件：{source_path}")
            args.defects_json = str(source_path.resolve())
            bugs, _ = parse_defects_json(args.defects_json)
            br_dir = source_path.parent
        else:
            resolved = qa_paths.find_bug_report(args.bug_report)
            if resolved is None:
                searched = "\n".join("  - " + str(d) for d in qa_paths.bug_report_search_dirs())
                raise SystemExit(
                    f"未找到缺陷清单：{args.bug_report}\n"
                    f"可传绝对路径，或把清单放到以下任一目录（或用 ONES_BUG_REPORTS_DIR 指定）：\n{searched}"
                )
            args.bug_report = str(resolved)
            bugs = parse_bug_report(args.bug_report)
            br_dir = Path(args.bug_report).resolve().parent

        wanted = expand_keys(args.only)
        if args.bugs:
            wanted |= expand_keys(args.bugs.split(","))
        if wanted:
            bugs = filter_wanted(bugs, wanted)
        if not bugs:
            print("未解析到 BUG 段，请检查缺陷清单格式（### BUG-编号：标题）")
            return

        evidence_base = [str(br_dir)]
        if args.defects_json:
            evidence_base.insert(0, str(Path(args.defects_json).parent))
        try:
            for sub in sorted(br_dir.iterdir()):
                if sub.is_dir():
                    evidence_base.append(str(sub))
        except OSError:
            pass

    field_map = load_field_mapping()
    profile = field_map.get(args.profile) if args.profile else None
    if not phase_b_only:
        ev_dir = ((profile or {}).get("site") or {}).get("evidence_dir")
        if ev_dir:
            ev_path = Path(ev_dir).expanduser()
            if not ev_path.is_absolute():
                ev_path = Path(__file__).resolve().parent.parent / ev_path
            evidence_base.insert(0, str(ev_path))
            evidence_base.insert(0, str(ev_path.parent))
        feature = (profile or {}).get("site", {}).get("feature", "")
        for b in bugs:
            if feature and not b["title"].startswith("【"):
                b["title"] = f"【{feature}】{b['title']}"
        profile_warnings = check_profile(profile)
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

    ledger_path = Path(args.ledger).expanduser().resolve() if args.ledger else default_ledger_path(br_dir)
    if phase_b_only and not ledger_path.exists():
        raise SystemExit(f"提交账本不存在: {ledger_path}")

    pw, browser, ctx, page = connect()
    try:
        ledger = SubmissionLedger(ledger_path, task)
        if not phase_b_only:
            print(f"提交账本: {ledger_path}")

        req, parent_fv = get_parent_context(page, team, task)
        print("主工单:", req["number"], req["summary"])

        if args.repair_images:
            _repair_images(page, team, task, ledger, args)
            return
        if args.verify_only:
            _verify_ledger(page, team, ledger)
            return

        handler = req["fields"]["frontend"] if args.handler == "frontend" else (req["fields"]["backend"] or req["fields"]["frontend"])
        current = get_current_user(page)
        print("当前登录账号:", current["name"], current["uuid"], "| 处理人:", handler)

        scope_uuid = (profile or {}).get("issue_type_scope_uuid")
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

        redact_patterns = list(((profile or {}).get("redact") or {}).get("patterns") or [])
        for item in (args.redact_pattern or []):
            if "==" in item:
                pat, rep = item.split("==", 1)
                redact_patterns.append([pat, rep])
        if not args.no_redact:
            for b in bugs:
                b["desc"], hits = sanitize_text(b["desc"], redact_patterns)
                if hits:
                    summary = ", ".join(f"{h['pattern'][:28]}×{h['count']}→{h['replacement']}" for h in hits)
                    print(f"  描述净化 {b['key']}: {summary}")

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
            rec = _phase_a_one(
                page, team, task, b, fvs, files, current, scope_uuid,
                ledger, skip_evidence=args.skip_evidence,
            )
            results.append(rec)
            if args.skip_evidence or args.no_inline_evidence or args.mode == "fast":
                if files:
                    ledger.mark(b["key"], STATE_INLINE_PENDING)
                else:
                    ledger.mark(b["key"], STATE_INLINE_OK)
                continue
            if files:
                ok, msg = inline_description_evidence(
                    page, team, rec["uuid"], files,
                    timeout=args.inline_timeout, number=rec.get("number"),
                )
                print(f"    描述内嵌图片: {ok} {msg}")
                ledger.mark(b["key"], STATE_INLINE_OK if ok else STATE_FAILED,
                            inline_message=msg)
            else:
                ledger.mark(b["key"], STATE_INLINE_OK)

        _print_results(ledger, results, ledger_path)

        if args.mode == "fast":
            pending = [r for r in ledger.pending_inline() if any(x["key"] == r["bug_key"] for x in results)]
            if pending:
                print("\nPhase A 已完成。描述内嵌图待补（Phase B，失败不影响单号）：")
                print(f"  python scripts/ones_submit_defects.py --work-order {args.work_order} "
                      f"--ledger {ledger_path} --repair-images")
    finally:
        disconnect(pw)


def _phase_a_one(page, team, parent, bug, fvs, files, current, scope_uuid, ledger,
                 skip_evidence=False):
    """单条缺陷 Phase A：复用账本 → 创建/补关联 → 附件核验。"""
    key = bug["key"]
    rec = ledger.get(key)
    if not rec:
        same = ledger.find_by_title(bug["title"])
        if same and same.get("task_uuid"):
            raise RuntimeError(
                f"{key} 与账本中 {same.get('bug_key')} 标题相同，疑似重复；"
                f"已有 #{same.get('number')} uuid={same.get('task_uuid')}，拒绝重复建单"
            )
    if rec and rec.get("task_uuid") and rec.get("state") != STATE_CREATED:
        print(f"  {key} 账本已存在 #{rec.get('number')} uuid={rec['task_uuid']}，跳过创建")
        number, uuid = rec.get("number"), rec["task_uuid"]
    elif rec and rec.get("task_uuid") and rec.get("state") == STATE_CREATED:
        number, uuid = rec.get("number"), rec["task_uuid"]
        link_task_to_parent(page, team, parent, uuid)
        ledger.mark(key, STATE_LINKED, number=number, task_uuid=uuid)
        print(f"  {key} 补关联 #{number} uuid={uuid}")
    else:
        rec = ledger.upsert(key, bug["title"], evidence_files=[str(p) for p in files])
        def _created(number, uuid):
            ledger.mark(key, STATE_CREATED, number=number, task_uuid=uuid,
                        evidence_files=[str(p) for p in files])
            print(f"  {key} 已创建 #{number} uuid={uuid}（先落账，再关联）")
        number, uuid = create_linked_defect(
            page, team, parent, bug["title"], fvs,
            assign=current["uuid"], issue_type_scope_uuid=scope_uuid,
            on_created=_created,
        )
        ledger.mark(key, STATE_LINKED, number=number, task_uuid=uuid)
        print(f"  {key} 已关联主工单 #{number}")

    done_state = (rec or {}).get("state")
    if not skip_evidence and done_state not in (STATE_ATTACHED, STATE_INLINE_PENDING,
                                                STATE_INLINE_OK, STATE_VERIFIED):
        if files:
            ok, msg = attach_evidence(page, team, uuid, files)
            print(f"    附件绑定: {ok} {msg} ({len(files)} 个文件)")
            if not ok:
                raise RuntimeError(
                    f"{key} 已创建并关联 #{number} uuid={uuid}，"
                    f"但附件未确认，已落账；请勿重复创建，按此 uuid 重试附件"
                )
            ledger.mark(key, STATE_ATTACHED, number=number, task_uuid=uuid,
                        attachment_files=[str(p) for p in files])
        else:
            ledger.mark(key, STATE_ATTACHED, number=number, task_uuid=uuid,
                        attachment_files=[])
    return {"key": key, "number": number, "uuid": uuid}


def _repair_images(page, team, parent, ledger, args):
    wanted = expand_keys(args.only)
    if args.bugs:
        wanted |= expand_keys(args.bugs.split(","))
    pending = [r for r in ledger.pending_inline()
               if key_in_wanted(r.get("bug_key"), wanted) and r.get("task_uuid")]
    if not pending:
        pending = [r for r in ledger.all()
                   if key_in_wanted(r.get("bug_key"), wanted)
                   and r.get("task_uuid")
                   and r.get("state") in (STATE_INLINE_PENDING, STATE_FAILED)
                   and (r.get("attachment_files") or r.get("evidence_files"))]
    if not pending:
        print("账本中没有待补图的缺陷。")
        return
    for rec in pending:
        key = rec["bug_key"]
        files = [Path(p) for p in (rec.get("attachment_files") or rec.get("evidence_files") or [])]
        if not files:
            ledger.mark(key, STATE_INLINE_OK)
            print(f"  {key} 无图片证据，标记完成")
            continue
        print(f"  {key} #{rec.get('number')} uuid={rec.get('task_uuid')} 补图 {len(files)} 个")
        ok, msg = inline_description_evidence(
            page, team, rec.get("task_uuid"), files,
            timeout=args.inline_timeout, number=rec.get("number"),
        )
        print(f"    {ok} {msg}")
        ledger.mark(key, STATE_INLINE_OK if ok else STATE_FAILED, inline_message=msg)
    _print_results(ledger, [], Path(args.ledger).expanduser().resolve())


def _verify_ledger(page, team, ledger):
    print("=== 账本校验 ===")
    bad = 0
    for rec in ledger.all():
        key, uuid = rec.get("bug_key"), rec.get("task_uuid")
        if not uuid:
            print(f"  {key} | 未创建")
            bad += 1
            continue
        report = verify_task_description_images(page, team, uuid)
        state = STATE_VERIFIED if report.get("ok") and rec.get("state") in (
            STATE_INLINE_OK, STATE_VERIFIED) else rec.get("state")
        if state == STATE_VERIFIED:
            ledger.mark(key, STATE_VERIFIED)
        print(f"  {key} | #{rec.get('number')} | {state} | 图片 {report.get('count', 0)} | "
              f"占位 {len(report.get('placeholder') or [])} | 坏图 {len(report.get('broken') or [])}")
        if not report.get("ok"):
            bad += 1
    print(f"=== 校验完成：{len(ledger.all()) - bad}/{len(ledger.all())} 通过 ===")


def _print_results(ledger, results, ledger_path):
    print("=== 结果表 ===")
    rows = results or ledger.all()
    for r in rows:
        key = r.get("key") or r.get("bug_key")
        rec = ledger.get(key) or {}
        print(f"  {key} | #{rec.get('number')} | {rec.get('task_uuid')} | {rec.get('state')}")
    print(f"账本: {ledger_path}")


if __name__ == "__main__":
    main()
