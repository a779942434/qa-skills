# -*- coding: utf-8 -*-
"""缺陷清单 schema —— web 产出与 ones 解析的**唯一契约**。

之前契约只隐含在两边文档里：web 手写 markdown、ones 用正则解析；任一边改格式就断链。
本模块把「标题格式 + 字段名 + 证据行」固化为可执行契约，生成侧与解析侧都调它：

    契约:  ### BUG-<编号>：<标题>
           - 严重程度：一般
           - 环境：...
           - 前置条件 / 操作步骤 / 预期结果 / 实际结果 / 复现率
           - 证据：a.png b.png（纯文件名/通配符，可换行）
           - 需求引用 / 备注

接口：
    render(meta, bugs) -> str        生成缺陷清单 markdown（web 侧用）
    parse(text) -> {"bugs": [...], "errors": [...]}   解析（ones 侧用）
    validate(text) -> [errors]       只校验

自检（往返契约测试）：python qa_skill_common/bug_report_schema.py
"""
from __future__ import annotations

import re
from datetime import datetime

# 契约字段（顺序即渲染顺序）
FIELDS = (
    "严重程度", "环境", "前置条件", "操作步骤", "预期结果",
    "实际结果", "复现率", "证据", "需求引用", "备注",
)
# 必填字段（缺则报错，不静默）
REQUIRED_FIELDS = ("严重程度",)

HEADING_RE = re.compile(
    r"(?m)^#{2,3}\s*(BUG-[A-Za-z0-9-]+)\s*(?:【[^】]*】)?\s*[：:]\s*(.+?)\s*$"
)
FIELD_RE = re.compile(r"(?m)^\s*[-*]\s*([^：:\n]+)[：:]\s*(.*)$")
EVIDENCE_EXT_RE = re.compile(r"\.(?:png|jpg|jpeg|gif|xlsx|csv|txt)$", re.IGNORECASE)
EVIDENCE_SPLIT_RE = re.compile(r"[\s、,，;；]+")


def _extract_evidence(raw):
    out = []
    for tok in EVIDENCE_SPLIT_RE.split(raw or ""):
        tok = tok.strip()
        if tok and EVIDENCE_EXT_RE.search(tok):
            out.append(tok)
    return out


def parse(text):
    """解析缺陷清单，返回 {"bugs": [...], "errors": [...]}。

    每个 bug: {key, title, severity, fields{...}, evidence[...], desc}
    （保留 key/title/evidence/desc 以兼容既有调用方。）
    """
    errors = []
    bugs = []
    headers = list(HEADING_RE.finditer(text or ""))
    if (text or "").strip() and not headers:
        errors.append("未找到任何缺陷标题：应为 `### BUG-编号：标题` 或 `## BUG-编号【严重程度】标题`")

    for i, m in enumerate(headers):
        key, title = m.group(1), m.group(2).strip()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[m.end():end]

        fields = {}
        for fm in FIELD_RE.finditer(body):
            name = fm.group(1).strip()
            if name in FIELDS:
                fields[name] = fm.group(2).strip()

        evidence = _extract_evidence(fields.get("证据", ""))
        if not evidence:
            # 兜底：扫描 body 中的列表行
            evidence = _extract_evidence("\n".join(x.group(1) for x in FIELD_RE.finditer(body)))

        missing = [f for f in REQUIRED_FIELDS if not fields.get(f)]
        if missing:
            errors.append(f"{key}: 缺必填字段 {', '.join(missing)}")

        bugs.append({
            "key": key,
            "title": title,
            "severity": fields.get("严重程度", ""),
            "fields": fields,
            "evidence": evidence,
            "desc": body.strip(),
        })
    return {"bugs": bugs, "errors": errors}


def validate(text):
    """只校验，返回错误列表（空=通过）。"""
    return parse(text)["errors"]


def render(meta, bugs):
    """按契约生成缺陷清单 markdown（web 侧产出用）。"""
    date = meta.get("时间") or datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# 缺陷清单：{meta.get('功能', '')}",
        "",
        f"- 测试时间：{date}",
        f"- 环境：{meta.get('环境', '')}",
        "",
    ]
    for b in bugs:
        lines += [
            f"### {b.get('编号', b.get('key', 'BUG-XXX'))}：{b.get('标题', b.get('title', ''))}",
            "",
            f"- 严重程度：{b.get('严重程度') or b.get('severity') or '待确认'}",
            f"- 环境：{b.get('环境') or meta.get('环境', '')}",
            f"- 前置条件：{b.get('前置条件', '')}",
            f"- 操作步骤：{b.get('操作步骤', '')}",
            f"- 预期结果：{b.get('预期结果', '')}",
            f"- 实际结果：{b.get('实际结果', '')}",
            f"- 复现率：{b.get('复现率', '')}",
            f"- 证据：{b.get('证据', '')}",
            f"- 需求引用：{b.get('需求引用', '')}",
            f"- 备注：{b.get('备注', '')}",
            "",
        ]
    return "\n".join(lines)


def _selftest():
    """往返契约测试：render -> parse，字段与证据不得丢失。"""
    meta = {"功能": "演示功能", "环境": "http://demo.test", "时间": "2026-09-10"}
    bugs = [{
        "编号": "BUG-01", "标题": "示例缺陷", "严重程度": "一般",
        "前置条件": "有数据", "操作步骤": "1. 打开页面", "预期结果": "正常",
        "实际结果": "报错", "复现率": "3/3", "证据": "BUG-01.png export_*.xlsx",
        "需求引用": "PRD-3.2", "备注": "待确认",
    }]
    md = render(meta, bugs)
    res = parse(md)
    assert not res["errors"], res["errors"]
    b = res["bugs"][0]
    assert b["key"] == "BUG-01", b
    assert b["title"] == "示例缺陷", b          # 标题不得残留前导冒号
    assert b["severity"] == "一般", b
    assert b["fields"]["操作步骤"] == "1. 打开页面", b
    assert b["evidence"] == ["BUG-01.png", "export_*.xlsx"], b
    # 缺必填字段必须报错
    bad = parse("### BUG-02：无严重程度\n\n- 预期结果：x\n")
    assert bad["errors"], bad
    print("bug_report_schema 自检通过：往返字段/证据一致，缺字段可检出")


if __name__ == "__main__":
    _selftest()
