# -*- coding: utf-8 -*-
"""判定入口（qa_action）：把「下结论」统一到一条路径。

由来（2026-10-16 复盘）：历史误报几乎都来自三种做法——
  ① 只看单层信号就下结论；② 靠 DOM 猜控件能力（多选/只读/日期）；③ 裸 dump 让判据被截断。
本模块把「四源判定 + 控件能力行为判定 + 限长输出」收成三个入口。

约定（见 web-blackbox-testing/SKILL.md 红线 7）：**要下结论的动作走这里**，
不要自己拼单信号判据，也不要靠 DOM class 猜控件类型。
"""
from __future__ import annotations

import json
import os
import time

from . import output as _output
from . import bbt_helpers as _bbt  # 以模块属性调用：便于替换/测试，也避免绑定死引用

# control() 支持的 expect（multi/single 为行为判定，其余委托 assert_control_type）
CONTROL_EXPECTS = ("multi", "single", "input", "select", "date", "readonly",
                   "cascader", "checkbox", "textarea")

# 判定埋点：跨进程可观测（用例由 qa_case 以子进程执行，故走文件而非内存计数）。
# 未设置 QA_JUDGE_LOG 时静默跳过；任何异常都不得影响判定本身。
def _record(kind, payload):
    path = os.environ.get("QA_JUDGE_LOG")
    if not path:
        return
    try:
        rec = {"ts": round(time.time(), 3), "kind": kind}
        for k in ("ok", "reason", "expect", "actual"):
            if k in payload:
                rec[k] = payload[k]
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def summarize(path):
    """统计判定埋点文件，供 qa_case run/report 输出使用。

    返回 ``{"total": n, "verdict": a, "control": b, "failed": c, "path": str}``；
    文件不存在/为空时 total=0（调用方据此提示"是否绕过了判定入口"）。
    """
    out = {"total": 0, "verdict": 0, "control": 0, "failed": 0, "path": str(path)}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                out["total"] += 1
                k = rec.get("kind")
                if k in ("verdict", "control"):
                    out[k] += 1
                if rec.get("ok") is False:
                    out["failed"] += 1
    except Exception:
        pass
    return out


def control(page, item, expect, *, values=("A", "B"), timeout=3):
    """控件能力【行为判定】——禁止靠 DOM class、有无 `.el-tag` 或选项数量猜。

    expect:
      - ``multi``  : 连续选中两个值，两个都保留 => 多选
      - ``single`` : 连续选中两个值，只保留最后一个 => 单选
      - 其他       : 交给 ``assert_control_type``（input/select/date/readonly/cascader/checkbox/textarea）

    返回 ``{ok, expect, actual, reason, ...}``；探测异常返回 ``ok=False``（不静默放过）。
    """
    exp = str(expect or "").strip().lower()
    if exp in ("multi", "single"):
        vals = [v for v in (values or ()) if str(v).strip()]
        if len(vals) < 2:
            return {"ok": False, "expect": exp, "actual": "unknown",
                    "reason": "probe_needs_two_values"}
        try:
            is_multi = bool(_bbt.select_is_multiple(page, item, vals))
        except Exception as exc:  # 探测失败不能算通过
            return {"ok": False, "expect": exp, "actual": "unknown",
                    "reason": "probe_failed: %s" % exc}
        actual = "multi" if is_multi else "single"
        res = {"ok": actual == exp, "expect": exp, "actual": actual,
               "reason": "behaviour_probe", "probed_values": vals}
        _record("control", res)
        return res
    res = dict(_bbt.assert_control_type(item, expect, timeout=timeout) or {})
    res.setdefault("expect", exp)
    _record("control", res)
    return res


def verdict(page, action, *, expect=None, api_watcher=None, data_diff=None, keyword=None,
            response_required=None, timeout=60.0):
    """执行动作并按**四源**判定（新接口 + toast + 内联错误 + 数据变化）。

    expect: ``None``=只取自动判定；``success``/``blocked``/``silent``/``http_error``=额外断言，
    断言结果放在 ``match`` 字段（**不吞掉原始 signals**）。
    """
    res = _bbt.judge_action(page, action, api_watcher=api_watcher, data_diff=data_diff,
                            keyword=keyword, response_required=response_required, timeout=timeout)
    if expect:
        res["expect"] = expect
        res["match"] = (res.get("reason") == expect)
    _record("verdict", res)
    return res


def emit_verdict(result, *, out_dir=None, name=None, kind="verdict"):
    """输出判定结果：**判定字段永不截断**（统一走 output，避免裸 dump 砍判据）。"""
    return _output.emit(result, kind=kind, out_dir=out_dir, name=name)
