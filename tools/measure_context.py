#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化技能集的「读取量」与「真实会话用量」，防止结构改动后 token 反弹。

两种口径：

1. **字符代理（可 CI）**：统计典型任务路径必读文件的字符数。快、但可被
   「把文字从 SKILL.md 挪进 reference」操纵，所以只作辅助。
2. **真实遥测（`--sessions`）**：直接读本机 `~/.codex/sessions` 的
   `token_count` 事件，给出每会话 轮次/输入/缓存/未缓存/输出。
   这是 ground truth，不进 CI 阻断（本机私有路径、粒度不齐、含用户等待）。

成本模型（实测）：会话成本 ≈ Σ(每轮重发 context) ≈ `N × avg_context`。
大富会话 347 轮 / 84.47M 输入（缓存 99.7%）→ 初始前缀占 15%，
**会话中新增内容占 85%**。所以「轮次」与「每轮输出体量」才是主杠杆，
静态文档瘦身只值几个百分点。

用法:
    python3 tools/measure_context.py              # 字符代理 + 预算对比
    python3 tools/measure_context.py --check      # 超预算即非零退出（CI 闸门）
    python3 tools/measure_context.py --sessions   # 真实遥测（本机会话）
    python3 tools/measure_context.py --sessions --limit 10
"""
import argparse
import glob
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SESSIONS_GLOB = os.path.expanduser("~/.codex/sessions/**/rollout-*.jsonl")

# 缓存计价系数：等效全价输入 = cached × CACHE_PRICE + uncached
CACHE_PRICE = 0.1

# ---- 预算（字符数）。超出即 --check 失败。改结构前先改这里，别偷偷调松 ----
# 注意：必读集允许略高——「动手前就该知道」的前提类规则（如沙箱内浏览器/网络本就不可用、
# 权限直接升级）必须内联在 SKILL.md，不能降级成按需 reference，否则模型会先白试一遍。
# 真凭据是下面两个组合场景（常见 / 含提缺陷），它们才是成本主路径。
BUDGETS = {
    "必读·标准功能测": 12200,
    "常见·生成+执行": 21500,
    "含提缺陷·+ones": 33500,
}
SINGLE_FILE_MAX = 7000          # 单个 SKILL.md
PROMPT_TEMPLATE_MAX = 900       # prompt-template.md
REFERENCE_MAX = 7500            # 单个 reference .md（防"把 SKILL 内容搬进 reference"式反弹）
DESCRIPTIONS_MAX = 1100         # 常驻 description 合计（每个会话都在）
                                # 不设太紧：description 决定技能能否被触发，压太狠会漏触发


def nchars(rel):
    return len((ROOT / rel).read_text(encoding="utf-8"))


def descriptions():
    total = 0
    for f in sorted(ROOT.glob("*/SKILL.md")):
        t = f.read_text(encoding="utf-8")
        m = re.search(r"description:\s*>-\n((?:\s+.*\n)+)", t)
        total += len(m.group(1).strip()) if m else 0
    return total


SETS = {
    # 标准功能测的最小必读：两个 SKILL + 用例输出模板
    "必读·标准功能测": [
        "web-blackbox-testing/SKILL.md",
        "generate-manufacturing-test-cases/SKILL.md",
        "generate-manufacturing-test-cases/references/template.md",
    ],
    # 常见：再加载"生成细则"与"执行策略"（正常出用例+跑用例都会读）
    "常见·生成+执行": [
        "web-blackbox-testing/SKILL.md",
        "generate-manufacturing-test-cases/SKILL.md",
        "generate-manufacturing-test-cases/references/template.md",
        "generate-manufacturing-test-cases/references/method.md",
        "web-blackbox-testing/references/playwright-strategy.md",
    ],
    # 含提缺陷：再加 ones 链路
    "含提缺陷·+ones": [
        "web-blackbox-testing/SKILL.md",
        "generate-manufacturing-test-cases/SKILL.md",
        "generate-manufacturing-test-cases/references/template.md",
        "generate-manufacturing-test-cases/references/method.md",
        "web-blackbox-testing/references/playwright-strategy.md",
        "ones-create-linked-defect/SKILL.md",
        "ones-create-linked-defect/references/ones-ui.md",
    ],
    # 按需（场景/排障），不进上面的常规口径
    "按需·可选（不叠加）": [
        "generate-manufacturing-test-cases/references/scenarios.md",
        "web-blackbox-testing/references/toolbox.md",
        "web-blackbox-testing/references/test-scope.md",
        "web-blackbox-testing/references/advanced-ui.md",
        "web-blackbox-testing/references/constraints.md",
        "web-blackbox-testing/references/ipc-ui.md",
        "web-blackbox-testing/references/import-export.md",
        "web-blackbox-testing/references/master-data-setup.md",
        "web-blackbox-testing/references/reporting.md",
        "qa_skill_common/references/environment.md",
        "qa_skill_common/references/bug-report.md",
        "qa_skill_common/references/element-plus-recipe.md",
        "qa_skill_common/references/datagrip.md",
    ],
}


def run_chars(check=False):
    """字符代理口径。返回 (是否全部达标, 结果 dict)。"""
    results = {}
    ok_all = True
    d = descriptions()
    results["常驻·description 合计"] = (d, DESCRIPTIONS_MAX)
    over = check and d > DESCRIPTIONS_MAX
    print(f"常驻（各技能 description 合计）: {d} 字 ≈ {round(d*0.6)}~{d} tokens"
          f"  [预算 {DESCRIPTIONS_MAX}]{'  ✗ 超预算' if over else '  ✓'}")
    if over:
        ok_all = False

    for name, files in SETS.items():
        tot = sum(nchars(f) for f in files)
        results[name] = (tot, BUDGETS.get(name))
        budget = BUDGETS.get(name)
        flag = ""
        if budget:
            flag = "  [预算 {}]".format(budget)
            if check and tot > budget:
                ok_all = False
                flag += "  ✗ 超预算"
            elif tot <= budget:
                flag += "  ✓"
        print(f"\n{name}: {tot} 字 ≈ {round(tot*0.6)}~{tot} tokens{flag}")
        for f in files:
            print(f"   {nchars(f):>6} 字  {f}")

    if check:
        print("\n--- 单文件预算 ---")
        for f in sorted(ROOT.glob("*/SKILL.md")):
            c = len(f.read_text(encoding="utf-8"))
            bad = c > SINGLE_FILE_MAX
            ok_all = ok_all and not bad
            print(f"   {c:>6} 字  {f.relative_to(ROOT)}{'  ✗ 超预算' if bad else ''}")
        print("\n--- reference 单文件预算 ---")
        for f in sorted(ROOT.glob("*/references/*.md")):
            c = len(f.read_text(encoding="utf-8"))
            bad = c > REFERENCE_MAX
            ok_all = ok_all and not bad
            print(f"   {c:>6} 字  {f.relative_to(ROOT)}{'  ✗ 超预算' if bad else ''}")
        pt = ROOT / "prompt-template.md"
        if pt.exists():
            c = len(pt.read_text(encoding="utf-8"))
            bad = c > PROMPT_TEMPLATE_MAX
            ok_all = ok_all and not bad
            print(f"   {c:>6} 字  prompt-template.md"
                  f"{'  ✗ 超预算' if bad else ''}  [预算 {PROMPT_TEMPLATE_MAX}]")
    return ok_all, results


def _is_qa_session(cwd):
    """按 cwd 判定是否 QA 技能会话。

    返回 True / False / **None（未知）** 三态：rollout 头部没有 session_meta 或
    cwd 为空时返回 None——调用方对未知一律**保留**，避免静默丢数据。
    """
    s = str(cwd or "")
    if not s:
        return None
    return "qa-skills" in s


def _session_cwd(path, max_lines=5):
    """从 rollout 头部读 session_meta.cwd；取不到返回空串。"""
    for i, line in enumerate(_iter_lines(path)):
        if i >= max_lines:
            break
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") == "session_meta":
            return str((o.get("payload") or {}).get("cwd") or "")
    return ""


def run_sessions(limit=0, only_qa=True):
    """真实遥测：解析本机 rollout 的 token_count 事件。

    ``only_qa=True`` 时按 rollout 头部的 cwd 过滤出 qa-skills 项目的会话；
    cwd 未知的一律保留并单独计数（宁滥勿缺）。传 ``only_qa=False`` 看全部。
    """
    rows = []
    scanned = qa_hits = unknown_cwd = 0
    for path in sorted(glob.glob(SESSIONS_GLOB, recursive=True)):
        scanned += 1
        cwd = _session_cwd(path)
        qa = _is_qa_session(cwd)
        if qa is True:
            qa_hits += 1
        elif qa is None:
            unknown_cwd += 1
        if only_qa and qa is False:
            continue                       # 明确属于其它项目 -> 过滤
        turns = 0
        last = None
        for line in _iter_lines(path):
            try:
                o = json.loads(line)
            except Exception:
                continue
            pl = o.get("payload") or {}
            if o.get("type") == "response_item" and pl.get("type") == "function_call":
                turns += 1
            elif o.get("type") == "event_msg" and pl.get("type") == "token_count":
                u = (pl.get("info") or {}).get("total_token_usage") or {}
                if u:
                    last = u
        if not last:
            continue
        uncached = max(0, last.get("input_tokens", 0) - last.get("cached_input_tokens", 0))
        fpe = last.get("cached_input_tokens", 0) * CACHE_PRICE + uncached
        rows.append({
            "file": os.path.basename(path),
            "cwd": cwd,
            "turns": turns,
            "input": last.get("input_tokens", 0),
            "cached": last.get("cached_input_tokens", 0),
            "uncached": uncached,
            "output": last.get("output_tokens", 0),
            "fpe": int(fpe),
        })
    rows.sort(key=lambda r: -r["fpe"])
    if limit:
        rows = rows[:limit]
    if not rows:
        print("未找到带用量的会话（{}）".format(SESSIONS_GLOB))
        return []
    print("{:<52}{:>7}{:>12}{:>12}{:>10}{:>10}{:>12}".format(
        "会话", "轮次", "输入(M)", "缓存(M)", "未缓存(M)", "输出(k)", "等效全价(M)"))
    for r in rows:
        print("{:<52}{:>7}{:>12.2f}{:>12.2f}{:>10.2f}{:>10.1f}{:>12.2f}".format(
            r["file"][:52], r["turns"], r["input"] / 1e6, r["cached"] / 1e6,
            r["uncached"] / 1e6, r["output"] / 1e3, r["fpe"] / 1e6))
    print("\n等效全价输入 = 缓存×{:.1f} + 未缓存（缓存计价系数，改 CACHE_PRICE 可调）"
          .format(CACHE_PRICE))
    if only_qa:
        print("过滤口径：扫描 {} 份 rollout；命中 QA {} 份；cwd 未知保留 {} 份"
              "（--all-sessions 可看全部）".format(scanned, qa_hits, unknown_cwd))
    else:
        print("口径：全部 {} 份 rollout（--all-sessions）".format(scanned))
    return rows


def _iter_lines(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                yield line
    except Exception:
        return


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="超预算即非零退出（CI 闸门）")
    ap.add_argument("--sessions", action="store_true", help="输出真实会话用量（本机）")
    ap.add_argument("--limit", type=int, default=0, help="--sessions 的显示条数")
    ap.add_argument("--all-sessions", action="store_true",
                    help="--sessions 时不过滤项目（默认只看 qa-skills）")
    args = ap.parse_args(argv)

    if args.sessions:
        run_sessions(limit=args.limit, only_qa=not args.all_sessions)
        return 0

    ok, _ = run_chars(check=args.check)
    if args.check:
        print("\n结果：{}".format("全部达标 ✓" if ok else "存在超预算 ✗"))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
