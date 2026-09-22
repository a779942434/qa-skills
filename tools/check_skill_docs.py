#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能文档结构闸门：防止瘦身把「红线」等硬约束删掉或稀释。

为什么不用关键词匹配：把 7 条红线合并成 1 条超长句，关键词照样命中。
所以这里断言的是 **条数** + **每条必含动作动词**（禁止/必须/不得/只用/…）。
这是低成本方案：能防「删条」，防不住「合并稀释」——后者需要逐条语义锚，
本轮不做（见计划 Assumptions）。

用法:
    python3 tools/check_skill_docs.py            # 通过打印 OK
    python3 tools/check_skill_docs.py -v         # 显示逐条明细
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_SKILL = ROOT / "web-blackbox-testing/SKILL.md"

# 红线最少条数（A 段）。必须等于当前实际条数：留余量会让「新增的红线被删掉」
# 恰好逃过闸门（8 条时下限设 7，删掉第 8 条仍然通过——实测过）。
RED_LINE_MIN = 8
# 必须逐条存在的关键红线（计数挡不住"删掉某一条"，这里按语义锚点兜住）
RED_LINE_MUST_HAVE = ("输出限长", "判定信号", "多信号", "不脑补", "标准用户操作")
# 每条红线必须含约束性表述（禁止/必须/…），否则视为空话被稀释
ACTION_VERBS = ("禁止", "必须", "不得", "不许", "不要", "只用", "只做",
                "只操作", "仅", "一律", "统一", "不泄露", "不碰", "不写入",
                "不编造", "不执行", "不下载", "不脑补", "不写")

# 除红线外必须留存的结构锚点
REQUIRED_MARKERS = (
    ("停顿边界", "C 段停顿边界（何时该停下来问用户）"),
    ("结束闸门", "结束闸门（数据清理与留档纪律）"),
    ("必守", "必守清单标题"),
)


def _sections(text):
    """按 markdown 标题切段，返回 [(标题, 正文)]。"""
    out, cur_title, buf = [], None, []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if cur_title is not None:
                out.append((cur_title, "\n".join(buf)))
            cur_title, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    if cur_title is not None:
        out.append((cur_title, "\n".join(buf)))
    return out


def check_red_lines(text):
    """返回 (条数, 不合格条目列表)。"""
    items = []
    for title, body in _sections(text):
        if "红线" in title:
            for line in body.splitlines():
                m = re.match(r"^\s*(\d+)[.、)]\s*(.+)$", line)
                if m:
                    items.append(m.group(2).strip())
    bad = [it for it in items if not any(v in it for v in ACTION_VERBS)]
    return items, bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    problems = []
    if not WEB_SKILL.exists():
        print("✗ 找不到 {}".format(WEB_SKILL))
        return 1
    text = WEB_SKILL.read_text(encoding="utf-8")

    items, bad = check_red_lines(text)
    print("红线条数: {}（下限 {}）".format(len(items), RED_LINE_MIN))
    if len(items) < RED_LINE_MIN:
        problems.append("红线只剩 {} 条，少于下限 {}".format(len(items), RED_LINE_MIN))
    if bad:
        problems.append("{} 条红线缺少动作动词（疑似被稀释）".format(len(bad)))
    if args.verbose:
        for i, it in enumerate(items, 1):
            mark = "✓" if it not in bad else "✗"
            print("  {} {}. {}".format(mark, i, it[:70]))

    for marker, label in REQUIRED_MARKERS:
        if marker not in text:
            problems.append("缺少结构锚点：{}（{}）".format(marker, label))

    for kw in RED_LINE_MUST_HAVE:
        if kw not in text:
            problems.append("缺少关键红线关键词：{}".format(kw))

    # 判定信号不得被截断：这条是防误报的红线，必须留在文档里
    if "判定信号" not in text and "多信号" not in text:
        problems.append("缺少「多信号/判定信号」表述（防误报红线被删）")

    if problems:
        print("\n✗ 文档闸门未通过：")
        for p in problems:
            print("  - {}".format(p))
        return 1
    print("\n✓ 文档闸门通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
