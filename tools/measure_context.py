#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""量化技能集在典型任务下的「读取量」，防止结构改动后 token 反弹。

用法: python3 tools/measure_context.py
输出: 常驻(description) 与 三种任务场景的必读字数 / token 估算。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


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
        "qa_skill_common/references/datagrip.md",
    ],
}


def main():
    d = descriptions()
    print(f"常驻（各技能 description 合计）: {d} 字 ≈ {round(d*0.6)}~{d} tokens")
    for name, files in SETS.items():
        tot = sum(nchars(f) for f in files)
        print(f"\n{name}: {tot} 字 ≈ {round(tot*0.6)}~{tot} tokens")
        for f in files:
            print(f"   {nchars(f):>6} 字  {f}")


if __name__ == "__main__":
    main()
