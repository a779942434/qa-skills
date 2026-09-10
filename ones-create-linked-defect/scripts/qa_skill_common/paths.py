# -*- coding: utf-8 -*-
"""统一产物路径解析（web-blackbox-testing / ones-create-linked-defect 共用）。

所有测试产物（缺陷清单、测试报告、用例、知识库归档）都相对「产物根 workspace」解析，
保证两个技能在同一台机器上得到**同一路径**，避免「web 产出、ones 找不到」。

解析优先级：
    workspace_root():
        1. 环境变量 QA_WORKSPACE
        2. 从本文件位置向上查找标记 .qa-workspace / .git
        3. 回退 ~/.codex/qa-workspace
    bug_reports_dir():    QA_BUG_REPORTS_DIR > <workspace>/bug-reports
    knowledge_base_dir(): <workspace>/knowledge-base

关键：从**本文件位置**推导（刻意不用 cwd），因此与当前工作目录、与安装方式
（仓库内 / ~/.codex/skills）无关，两个技能必然一致。
"""
from __future__ import annotations

import os
from pathlib import Path

MARKERS = (".qa-workspace", ".git")


def workspace_root() -> Path:
    """解析产物根目录。"""
    env = os.environ.get("QA_WORKSPACE", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for base in (here, *here.parents):
        if any((base / m).exists() for m in MARKERS):
            return base
    return Path.home() / ".codex" / "qa-workspace"


def bug_reports_dir() -> Path:
    """缺陷清单目录（web 产出、ones 读取，同一处）。"""
    env = os.environ.get("QA_BUG_REPORTS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return workspace_root() / "bug-reports"


def knowledge_base_dir() -> Path:
    """知识库归档目录。"""
    return workspace_root() / "knowledge-base"


def test_reports_dir() -> Path:
    return knowledge_base_dir() / "test-reports"


def test_cases_dir() -> Path:
    return knowledge_base_dir() / "test-cases"


def notes_dir() -> Path:
    return knowledge_base_dir() / "notes"


def _skill_root():
    """定位本包所属技能目录（含 SKILL.md 的那层）；独立安装时用于兼容老位置。"""
    for base in Path(__file__).resolve().parents:
        if (base / "SKILL.md").exists():
            return base
    return None


def bug_report_search_dirs() -> list:
    """ones 定位缺陷清单时的候选目录（按优先级）。"""
    dirs = []
    for env in ("ONES_BUG_REPORTS_DIR", "QA_BUG_REPORTS_DIR"):
        val = os.environ.get(env, "").strip()
        if val:
            dirs.append(Path(val).expanduser())
    dirs.append(bug_reports_dir())
    dirs.append(knowledge_base_dir() / "bug-reports")  # 历史归档位置
    dirs.append(Path.cwd() / "bug-reports")
    dirs.append(Path.cwd() / "knowledge-base" / "bug-reports")
    skill = _skill_root()
    if skill:
        dirs.append(skill / "bug-reports")  # 旧默认位置（技能目录）
    seen, out = set(), []
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find_bug_report(name):
    """按文件名/相对路径定位缺陷清单；绝对路径直接使用。找不到返回 None。"""
    p = Path(str(name)).expanduser()
    if p.is_absolute():
        return p if p.exists() else None
    for d in bug_report_search_dirs():
        cand = d / name
        if cand.exists():
            return cand
    return p if p.exists() else None


def ensure_dirs() -> dict:
    """确保关键产物目录存在，返回路径字典。"""
    out = {
        "workspace": workspace_root(),
        "bug_reports": bug_reports_dir(),
        "knowledge_base": knowledge_base_dir(),
    }
    for key in ("bug_reports", "knowledge_base"):
        Path(out[key]).mkdir(parents=True, exist_ok=True)
    return out


if __name__ == "__main__":
    import json

    print(json.dumps({
        "workspace_root": str(workspace_root()),
        "bug_reports_dir": str(bug_reports_dir()),
        "knowledge_base_dir": str(knowledge_base_dir()),
        "search_dirs": [str(d) for d in bug_report_search_dirs()],
    }, ensure_ascii=False, indent=2))
