# -*- coding: utf-8 -*-
"""数据基线对比与清理策略（web-blackbox-testing 配套）。

测试改数据后，必须对比「页面状态 vs 基线」并明确"已恢复 / 未恢复"，避免污染后续回归。
页面状态由调用方按业务提取（如各页签记录标识集合），本工具只做对比与留痕。
"""
from datetime import datetime

DATE = datetime.now().strftime("%Y-%m-%d")


def compare_state(baseline: dict, current: dict):
    """对比基线状态与当前状态，返回差异说明列表。

    入参形如 {"待用计划": ["GD198", ...], "当前计划": [...], "暂停计划": [...]}。
    """
    diff = []
    for key in sorted(set(baseline) | set(current)):
        b = set(baseline.get(key, []) or [])
        c = set(current.get(key, []) or [])
        added = c - b
        removed = b - c
        if added:
            diff.append(f"{key} 新增: {sorted(added)}")
        if removed:
            diff.append(f"{key} 减少: {sorted(removed)}")
    return diff


def write_cleanup_note(out_path, feature, baseline, current, recovered=True, note=""):
    """把清理结论写成 markdown 留痕（追加到测试产物或独立文件）。"""
    lines = [
        f"# 数据清理留痕：{feature}",
        f"- 时间：{DATE}",
        f"- 恢复结果：{'已恢复' if recovered else '未恢复（明确记录，避免影响后续回归）'}",
        f"- 备注：{note}",
        "",
        "## 状态差异",
    ]
    diff = compare_state(baseline, current)
    lines += diff if diff else ["（无差异）"]
    lines.append("")
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    return out_path


if __name__ == "__main__":
    print("data_cleanup 可用：compare_state(baseline, current) / write_cleanup_note(...)")
