#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安装副本自检：技能目录复制到技能库后，真的能 import、能启动。

为什么需要：仓库里跑得通不代表安装副本跑得通。2026-11-13 实测
`~/.agents/skills/ones-create-linked-defect` 缺 `scripts/qa_skill_common`，
直接 import 报 `ModuleNotFoundError`，但同步脚本只检查了文件存在。

用法：
    python3 tools/check_install.py                    # 默认检查 ~/.codex 与 ~/.agents
    python3 tools/check_install.py --root ~/.codex/skills
    python3 tools/check_install.py --root /tmp/skills --strict

默认：目标根不存在 → warning；存在但技能缺失/导入失败 → 失败。
--strict：目标根不存在也失败（CI 用）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = ("web-blackbox-testing", "web-adversarial-testing", "ones-create-linked-defect",
          "generate-manufacturing-test-cases", "generate-arun-api-scripts")
# 每个技能至少要能启动的入口；没有就跳过，不把“无脚本技能”判失败。
ENTRYPOINTS = {
    "web-blackbox-testing": ("scripts/qa_case.py",),
    "ones-create-linked-defect": ("scripts/ones_helpers.py", "scripts/ones_submit_defects.py"),
}


def run(cmd: list[str], cwd: Path, timeout: int = 40) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:  # noqa: BLE001
        return 124, "", str(exc)


def check_root(root: Path, strict: bool) -> list[str]:
    problems: list[str] = []
    if not root.exists():
        msg = f"目标根不存在: {root}"
        if strict:
            problems.append(msg)
        else:
            print(f"  [跳过] {msg}")
        return problems

    print(f"===== 检查 {root} =====")
    found = 0
    for skill in SKILLS:
        d = root / skill
        if not d.exists():
            print(f"  [跳过] {skill}（未安装）")
            continue
        found += 1
        if not (d / "SKILL.md").exists():
            problems.append(f"{skill}: 缺少 SKILL.md")
            continue
        if skill in ENTRYPOINTS:
            common = d / "scripts/qa_skill_common/__init__.py"
            if not common.exists():
                problems.append(f"{skill}: 缺少 scripts/qa_skill_common/__init__.py")
                continue
            # 只验证 import，不启动浏览器；--help 只验证 argparse/模块导入链。
            code = "import sys; sys.path.insert(0, 'scripts'); import qa_skill_common; print('ok')"
            rc, out, err = run([sys.executable, "-c", code], d)
            if rc != 0 or "ok" not in out:
                problems.append(f"{skill}: import qa_skill_common 失败: {(err or out).strip()[:200]}")
                continue
            for rel in ENTRYPOINTS[skill]:
                entry = d / rel
                if not entry.exists():
                    problems.append(f"{skill}: 缺少入口 {rel}")
                    continue
                rc, out, err = run([sys.executable, rel, "--help"], d)
                if rc != 0:
                    problems.append(f"{skill}: {rel} --help 失败: {(err or out).strip()[:200]}")
        print(f"  [OK] {skill}")
    if found == 0:
        print("  [提示] 该根下没有本仓库技能，跳过")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="检查技能安装副本可导入、可启动")
    ap.add_argument("--root", action="append", type=Path, default=None,
                    help="技能根目录，可重复；默认 ~/.codex/skills 与 ~/.agents/skills")
    ap.add_argument("--strict", action="store_true", help="目标根不存在也失败")
    args = ap.parse_args(argv)

    roots = args.root or [Path.home() / ".codex/skills", Path.home() / ".agents/skills"]
    problems: list[str] = []
    for root in roots:
        problems += check_root(root.expanduser(), args.strict)

    if problems:
        print("\n✗ 安装自检未通过：")
        for p in problems:
            print("  - " + p)
        return 1
    print("\n✓ 安装自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
