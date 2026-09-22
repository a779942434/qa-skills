# -*- coding: utf-8 -*-
"""统一输出限长契约（会话成本主线：压 context 增长）。

背景（实测）：单会话工具输出累计 2.09M 字符、86 条 >2k 字符、361 次
DOM dump；context 从 36.8k 涨到 435.6k。会话成本 ≈ Σ(每轮重发 context)，
而「会话中新增内容」占其中 85%——所以**输出体量**是最贵的一项。

两条铁律：

1. **判定字段永不截断**：toast / 内联错误 / HTTP 状态 / data_diff 是
   「多信号交叉判定」（SKILL 红线 A#7）的唯一依据。截断它们会把
   「有 toast 的校验拦截」误判成「静默无反馈」——这正是 2026-09-03
   BUG-009 的真实误报路径。
2. **观察字段按上限截断并给出 total**：元素列表 / 文本 dump / 表格行
   只帮助理解页面，截断不改变结论。

安全默认：**白名单式可截断**。只有明确列在 `TRUNCATABLE_KEYS` 里的
键才会被截断，其余一律完整保留——避免新字段名悄悄被剪掉。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

# 只允许截断这些「观察类」键；其余键一律完整保留（安全默认）
TRUNCATABLE_KEYS = (
    "elements", "rows", "buttons", "headers", "inputs", "dialogs", "texts",
    "visible_dialogs", "options", "items", "fields", "cells", "candidates",
    "snapshots", "nodes", "columns", "cards", "tabs", "labels",
    "tables", "dialog_text", "records", "log_lines",
)

# 判定类键：显式声明，供 emit_signals 与调用方自检
SIGNAL_KEYS = (
    "toasts", "form_errors", "http", "data_diff", "feedback", "signals",
    "console_errors", "page_errors", "blocked", "processed", "reason",
)

DEFAULT_MAX_CHARS = 2000


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _safe_name(name: str) -> str:
    s = re.sub(r"[^\w\-.]+", "_", str(name or "").strip(), flags=re.UNICODE).strip("_")
    return (s or "output")[:80]


def safe_name(name: str) -> str:
    """把任意字符串规整成安全文件名（公开别名，供调用方复现同一命名）。"""
    return _safe_name(name)


def _write_full(text: str, out_dir, name: str, kind: str) -> str:
    """把完整输出落盘，返回路径（失败返回空串，绝不阻断主流程）。"""
    if not out_dir:
        return ""
    try:
        base = Path(out_dir).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        stem = _safe_name(name or kind)
        path = base / ("{}.{}.json".format(stem, _safe_name(kind)))
        i = 1
        while path.exists() and path.stat().st_size and path.read_text(encoding="utf-8", errors="ignore") != text:
            path = base / ("{}.{}.{}.json".format(stem, _safe_name(kind), i))
            i += 1
        path.write_text(text, encoding="utf-8")
        return str(path)
    except Exception:
        return ""


def _counts_of(value) -> int:
    if isinstance(value, (list, tuple, str, dict)):
        return len(value)
    return 1


def _shrink(value, keep: int):
    """把可截断值裁剪到 keep 项，返回 (裁剪后, 被省略数)。"""
    if isinstance(value, list):
        if keep >= len(value):
            return value, 0
        return value[:max(0, keep)], len(value) - max(0, keep)
    if isinstance(value, str):
        return value[:max(0, keep)], max(0, len(value) - max(0, keep))
    if isinstance(value, dict):
        keys = list(value.keys())
        if keep >= len(keys):
            return value, 0
        return {k: value[k] for k in keys[:max(0, keep)]}, len(keys) - max(0, keep)
    return value, 0


def emit(payload, *, kind="generic", max_chars=DEFAULT_MAX_CHARS, out_dir=None,
         name=None, trunable_keys=None, full=None):
    """输出 payload，超过 max_chars 时截断观察字段并给出 counts/full_path。

    - payload 非 dict 时按 ``{"value": payload}`` 处理。
    - 不可截断键（判定字段 + 未知键）永远完整保留；若它们本身就超预算，
      则整体超预算输出，并标 ``over_budget: true``（**绝不为了省 token 丢判据**）。
    - full=True 时跳过截断，直接输出全量（供 --full 使用）。
    - 截断发生时把全量写入 out_dir，并在结果里给 ``full_path``。
    """
    if not isinstance(payload, dict):
        payload = {"value": payload}
    text = _dump(payload)
    if full or len(text) <= max_chars:
        return text

    keys = tuple(trunable_keys) if trunable_keys else TRUNCATABLE_KEYS
    kept = {k: v for k, v in payload.items() if k not in keys}
    shrink = {k: v for k, v in payload.items() if k in keys}
    counts = {k: _counts_of(v) for k, v in shrink.items()}

    full_path = _write_full(text, out_dir, name, kind)

    # 逐步收紧可截断字段，直到整体落进预算（若不可截断部分本身超预算则直接停）
    keep_ratio = 0.5
    best = None
    for _ in range(8):
        omitted = {}
        trial = dict(kept)
        for k, v in shrink.items():
            keep = int(counts[k] * keep_ratio)
            new, om = _shrink(v, keep)
            trial[k] = new
            if om:
                omitted[k] = om
        trial["counts"] = counts
        if omitted:
            trial["omitted"] = omitted
        if full_path:
            trial["full_path"] = full_path
        trial["truncated"] = True
        candidate = _dump(trial)
        if len(candidate) <= max_chars:
            best = candidate
            break
        keep_ratio /= 2

    if best is None:
        trial = dict(kept)
        for k, v in shrink.items():
            trial[k] = [] if isinstance(v, list) else ""
        trial["counts"] = counts
        if full_path:
            trial["full_path"] = full_path
        trial["truncated"] = True
        candidate = _dump(trial)
        if len(candidate) > max_chars:
            # 不可截断部分本身超预算：保判据，超预算输出
            trial = dict(kept)
            trial["counts"] = counts
            if full_path:
                trial["full_path"] = full_path
            trial["truncated"] = True
            trial["over_budget"] = True
            trial["budget"] = max_chars
            candidate = _dump(trial)
        best = candidate
    return best


def emit_signals(signals, *, kind="signals", max_chars=DEFAULT_MAX_CHARS,
                 out_dir=None, name=None):
    """输出判定信号：判定字段永不截断，观察字段受预算约束。

    signals 形如::

        {"toasts": [...], "form_errors": [...], "http": [...],
         "data_diff": {...}, "elements": [...]}
    """
    if not isinstance(signals, dict):
        signals = {"signals": signals}
    return emit(signals, kind=kind, max_chars=max_chars, out_dir=out_dir, name=name)


def summarize(payload, *, max_items=10) -> dict:
    """只取规模摘要（条数 + 前若干项），用于把大结构压成一行。"""
    if not isinstance(payload, dict):
        payload = {"value": payload}
    out = {}
    for k, v in payload.items():
        n = _counts_of(v)
        if isinstance(v, (list, tuple)):
            out[k] = {"total": n, "head": list(v)[:max_items]}
        elif isinstance(v, dict):
            out[k] = {"total": n, "keys": list(v.keys())[:max_items]}
        else:
            out[k] = v
    return out


if __name__ == "__main__":
    demo = {"toasts": ["请选择生成方式"], "form_errors": [],
            "http": [{"url": "/api/x", "status": 200, "ms": 88}],
            "elements": [{"i": i, "text": "x" * 40} for i in range(200)]}
    print(emit(demo, kind="demo", max_chars=400, out_dir=os.environ.get("OUT_DIR") or None, name="demo"))
