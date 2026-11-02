# -*- coding: utf-8 -*-
"""数据基线对比与清理策略（web-blackbox-testing 配套）。

测试改数据后，必须对比「页面状态 vs 基线」并明确"已恢复 / 未恢复"，避免污染后续回归。
页面状态由调用方按业务提取（如各页签记录标识集合），本工具只做对比与留痕。
"""
import json
from datetime import datetime
from pathlib import Path

DATE = datetime.now().strftime("%Y-%m-%d")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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
        f"- 时间：{_today()}",
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



def cleanup_report(feature, baseline, current, records=None, recovered=True, note=""):
    """生成可写入 data_ledger 的结构化清理报告。"""
    diff = compare_state(baseline, current)
    return {
        "feature": feature,
        "checked_at": _today(),
        "status": "restored" if recovered and not diff else ("retained" if recovered else "not_restored"),
        "recovered": bool(recovered),
        "note": note or "",
        "diff": diff,
        "records": records or {},
    }


def write_cleanup_ledger(out_path, feature, baseline, current, records=None, recovered=True, note=""):
    """把清理结果写入独立 JSON，并可被 RunState/运行包引用。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    report = cleanup_report(feature, baseline, current, records, recovered, note)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
