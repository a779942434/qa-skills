#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能仓库完整性闸门：敏感信息、失效链接、无引用脚本。

设计原则：
- 只扫 git tracked 文件；runs/、bug-reports/、knowledge-base/ 等本地产物不扫。
- 敏感信息默认 fail closed；示例/测试里的通用占位路径走显式豁免。
- 一次性脚本不是靠文件名猜，而是靠“是否有文档/测试引用”判定。
- 输出只给路径、行号、规则名，不回显命中的敏感值，避免二次泄漏。

用法：
    python3 tools/check_skill_integrity.py                 # 全部检查
    python3 tools/check_skill_integrity.py --sensitive
    python3 tools/check_skill_integrity.py --links
    python3 tools/check_skill_integrity.py --oneoff
    python3 tools/check_skill_integrity.py --terms-file tools/sensitive_terms.local.txt
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".md", ".py", ".sh", ".bash", ".yaml", ".yml", ".json", ".txt", ".toml", ".ini", ".cfg"}
SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "runs", "bug-reports", "knowledge-base", "evidence", "tmp", "sites", ".playwright-mcp"}
# 测试/示例中的通用占位路径，不算真实 PII。
GENERIC_USER_PATHS = {"/Users/x/", "/Users/user/", "/Users/example/", "/Users/name/"}

HOME_PATH_RE = re.compile(r"(/Users/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\[^\\\s\"']+\\)")
TASK_URL_RE = re.compile(r"https?://[^\s)\]\"']*ones\.shuyilink\.com/project/#/team/[A-Za-z0-9]+/task/[A-Za-z0-9]+")
PRIVATE_IP_RE = re.compile(r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b")
# 只扫描代码里的明显凭据赋值；文档里的“密码 xxx”是规则说明，避免误报。
CREDENTIAL_RE = re.compile(r"(?i)(?:password|passwd|pwd|token|secret)\s*[:=]\s*[\"'][^\"']{6,}[\"']")
MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)")


def tracked_files() -> list[Path]:
    try:
        out = subprocess.check_output(["git", "-C", str(ROOT), "ls-files"], text=True)
    except (OSError, subprocess.CalledProcessError):
        out = "\n".join(str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file())
    files = []
    for line in out.splitlines():
        p = ROOT / line.strip()
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        files.append(p)
    return sorted(files)


def is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def load_terms(path: Path | None) -> list[str]:
    if not path or not path.exists():
        return []
    terms = []
    for line in read(path).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            terms.append(line)
    return terms


def check_sensitive(files: list[Path], terms: list[str]) -> list[str]:
    problems = []
    for path in files:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(ROOT)
        text = read(path)
        for lineno, line in enumerate(text.splitlines(), 1):
            # 测试里的 /Users/x 是通用 fixture，显式豁免；其他测试仍扫 URL/凭据。
            if not is_test_path(path):
                m = HOME_PATH_RE.search(line)
                if m and not any(m.group(0).startswith(p) for p in GENERIC_USER_PATHS):
                    problems.append(f"{rel}:{lineno}: sensitive:absolute-home-path")
            if TASK_URL_RE.search(line):
                problems.append(f"{rel}:{lineno}: sensitive:hardcoded-task-url")
            if PRIVATE_IP_RE.search(line) and any(k in line.lower() for k in ("http", "dubbo", "host", "server", "address", "url")):
                problems.append(f"{rel}:{lineno}: sensitive:private-ip")
            if "scripts/" in rel.as_posix() and CREDENTIAL_RE.search(line) and not is_test_path(path):
                problems.append(f"{rel}:{lineno}: sensitive:credential-literal")
            for term in terms:
                if term and term in line:
                    problems.append(f"{rel}:{lineno}: sensitive:known-term")
                    break
    return problems


def resolve_link(src: Path, target: str) -> Path | None:
    target = target.strip().strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:", "tel:")):
        return None
    target = target.split("#", 1)[0]
    if not target or target.startswith("/") or target.startswith("~"):
        return None
    candidates = [src.parent / target]
    # 技能文档里的 scripts/...、references/... 是相对技能根写的。
    for parent in src.parents:
        if (parent / "SKILL.md").exists():
            candidates.append(parent / target)
            break
    candidates.append(ROOT / target)
    for c in candidates:
        if c.exists():
            return c
    return None


def check_links(files: list[Path]) -> list[str]:
    problems = []
    for path in files:
        if path.suffix.lower() != ".md":
            continue
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(read(path).splitlines(), 1):
            for target in MD_LINK_RE.findall(line):
                if target.strip().startswith("#"):
                    continue
                if resolve_link(path, target) is None:
                    problems.append(f"{rel}:{lineno}: link:missing-target:{target}")
    return problems


def check_oneoff(files: list[Path]) -> list[str]:
    """scripts/ 下的 .py 必须被任何文档/测试/入口引用。"""
    texts = [(p, read(p)) for p in files if p.suffix.lower() in TEXT_SUFFIXES]
    problems = []
    for path in files:
        if path.suffix != ".py":
            continue
        rel = path.relative_to(ROOT)
        if "scripts" not in rel.parts:
            continue
        if "qa_skill_common" in rel.parts or is_test_path(path) or path.name == "__init__.py":
            continue
        name = path.name
        referenced = False
        for other, text in texts:
            if other == path:
                continue
            if name in text:
                referenced = True
                break
        if not referenced:
            problems.append(f"{rel}: oneoff:unreferenced-script")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="技能仓库完整性检查")
    ap.add_argument("--sensitive", action="store_true", help="只查敏感信息")
    ap.add_argument("--links", action="store_true", help="只查 Markdown 链接")
    ap.add_argument("--oneoff", action="store_true", help="只查无引用脚本")
    ap.add_argument("--terms-file", type=Path, default=ROOT / "tools/sensitive_terms.local.txt",
                    help="额外敏感词文件（每行一个，gitignored）")
    args = ap.parse_args(argv)

    run_all = not (args.sensitive or args.links or args.oneoff)
    files = tracked_files()
    problems: list[str] = []
    if run_all or args.sensitive:
        problems += check_sensitive(files, load_terms(args.terms_file))
    if run_all or args.links:
        problems += check_links(files)
    if run_all or args.oneoff:
        problems += check_oneoff(files)

    if problems:
        print("✗ 技能完整性检查未通过：")
        for p in problems:
            print("  - " + p)
        return 1
    print("✓ 技能完整性检查通过（敏感信息 / 链接 / 无引用脚本）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
