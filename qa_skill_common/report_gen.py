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
    """生成缺陷清单骨架（与 ones-create-linked-defect 兼容）。

    meta: {环境}
    bugs: [{"编号","标题","严重程度","前置条件","操作步骤","预期结果","实际结果","复现率","证据","需求引用","备注"}]
    """
    lines = [
        f"# 缺陷清单：{meta.get('功能', '')}",
        "",
        f"- 测试时间：{meta.get('时间', DATE)}",
        f"- 环境：{meta.get('环境', '')}",
        "",
    ]
    for b in bugs:
        lines += [
            f"### {b.get('编号','BUG-XXX')}：{b.get('标题','')}",
            "",
            f"- 严重程度：{b.get('严重程度','待确认')}",
            f"- 环境：{meta.get('环境', '')}",
            f"- 前置条件：{b.get('前置条件','')}",
            f"- 操作步骤：{b.get('操作步骤','')}",
            f"- 预期结果：{b.get('预期结果','')}",
            f"- 实际结果：{b.get('实际结果','')}",
            f"- 复现率：{b.get('复现率','')}",
            f"- 证据：{b.get('证据','')}",
            f"- 需求引用：{b.get('需求引用','')}",
            f"- 备注：{b.get('备注','')}",
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":
    print("report_gen 可用：gen_report(meta, cases, problems, uncovered, evidence) / gen_bug(meta, bugs)")
