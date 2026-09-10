# -*- coding: utf-8 -*-
"""报告 / 缺陷清单骨架生成器（web-blackbox-testing 配套）。

执行脚本在跑完用例后，把结果喂给本工具直接生成 markdown 骨架，
AI 只补充分析与定级，避免手工整理报告消耗 token。
"""
from datetime import datetime

DATE = datetime.now().strftime("%Y-%m-%d")


def gen_report(meta: dict, cases: list, problems: list, uncovered: list,
               evidence: list) -> str:
    """生成测试报告骨架。

    meta:        {功能, 环境, 范围, 结果}
    cases:       [{"id","模块","结果","证据"}]，结果 ∈ 通过/失败/阻塞/未执行
    problems:    [{"id","标题","级别","备注"}]（P0~P4/待确认/环境观察）
    uncovered:   [str] 未覆盖项
    evidence:    [str] 截图/导出/SQL 路径
    """
    lines = [
        f"# 测试报告：{meta.get('功能', '')}",
        "",
        "## 结论",
        f"- 测试时间：{meta.get('时间', DATE)}",
        f"- 环境：{meta.get('环境', '')}",
        f"- 范围：{meta.get('范围', '')}",
        f"- 结果：通过 {sum(1 for c in cases if c.get('结果')=='通过')}，"
        f"失败 {sum(1 for c in cases if c.get('结果')=='失败')}，"
        f"阻塞 {sum(1 for c in cases if c.get('结果')=='阻塞')}",
        "",
        "## 用例执行结果",
        "| 用例ID | 模块 | 结果 | 证据 |",
        "| --- | --- | --- | --- |",
    ]
    for c in cases:
        lines.append(f"| {c.get('id','')} | {c.get('模块','')} | {c.get('结果','')} | {c.get('证据','')} |")
    lines += [
        "",
        "## 问题清单",
    ]
    for p in problems:
        lines.append(f"- {p.get('id','')}：{p.get('标题','')}（{p.get('级别','')}）{p.get('备注','')}")
    lines += [
        "",
        "## 本次未覆盖",
    ]
    lines += [f"- {u}" for u in uncovered]
    lines += [
        "",
        "## 证据",
    ]
    lines += [f"- {e}" for e in evidence]
    lines.append("")
    return "\n".join(lines)


def gen_bug(meta: dict, bugs: list) -> str:
    """生成缺陷清单骨架（契约单一来源：qa_skill_common.bug_report_schema）。

    meta: {功能, 环境, 时间?}
    bugs: [{"编号","标题","严重程度","前置条件","操作步骤","预期结果","实际结果","复现率","证据","需求引用","备注"}]
    """
    from .bug_report_schema import render as _render_bug

    return _render_bug(meta, bugs)


if __name__ == "__main__":
    print("report_gen 可用：gen_report(meta, cases, problems, uncovered, evidence) / gen_bug(meta, bugs)")
