# -*- coding: utf-8 -*-
"""通用业务不变量检查与执行器。

不变量是“与具体页面文案无关、任何实现都必须满足”的系统约束，例如数量守恒、
时间顺序、身份唯一和状态合法。页面/接口适配器负责取数，本模块只负责判定。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

CATEGORIES = (
    "quantity", "state", "identity", "time", "lineage", "config", "permission", "aggregation"
)


@dataclass(frozen=True)
class InvariantSpec:
    id: str
    name: str
    category: str
    severity: str
    check: Callable[[Any], Any]
    description: str = ""


def _result(spec: InvariantSpec, passed: bool, detail: Any = None, error: str = "") -> dict:
    return {
        "id": spec.id,
        "name": spec.name,
        "category": spec.category,
        "severity": spec.severity,
        "passed": bool(passed),
        "detail": detail,
        "error": error,
    }


def evaluate(specs: Iterable[InvariantSpec], context: Any = None) -> list[dict]:
    results = []
    for spec in specs:
        try:
            raw = spec.check(context)
            if isinstance(raw, dict):
                passed = bool(raw.get("passed", raw.get("ok", False)))
                detail = raw
            else:
                passed = bool(raw)
                detail = raw
            results.append(_result(spec, passed, detail))
        except Exception as exc:
            results.append(_result(spec, False, None, f"{type(exc).__name__}: {exc}"))
    return results


def check_sum(total: float, parts: Iterable[float], *, tolerance: float = 1e-6) -> dict:
    nums = [float(x) for x in parts]
    actual = sum(nums)
    expected = float(total)
    return {
        "passed": abs(actual - expected) <= tolerance,
        "expected": expected,
        "actual": actual,
        "parts": nums,
        "tolerance": tolerance,
    }


def check_non_negative(value: float) -> dict:
    v = float(value)
    return {"passed": v >= 0, "value": v}


def check_unique(values: Iterable[Any]) -> dict:
    values = list(values)
    seen = set()
    duplicates = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return {"passed": not duplicates, "duplicates": duplicates, "count": len(values)}


def check_time_order(start: Any, end: Any, *, allow_equal: bool = True) -> dict:
    ok = start <= end if allow_equal else start < end
    return {"passed": ok, "start": str(start), "end": str(end), "allow_equal": allow_equal}


def check_state_transition(current: str, target: str, allowed: dict[str, Iterable[str]]) -> dict:
    allowed_targets = list(allowed.get(current, ()))
    return {
        "passed": target in allowed_targets,
        "current": current,
        "target": target,
        "allowed": allowed_targets,
    }


def check_same_identity(left: Any, right: Any) -> dict:
    return {"passed": str(left) == str(right), "left": str(left), "right": str(right)}


def check_no_duplicate_objects(objects: Iterable[dict], key: str = "id") -> dict:
    keys = [obj.get(key) for obj in objects]
    return check_unique(keys)


def check_preserved_quantity(source: float, downstream: float, *, tolerance: float = 1e-6) -> dict:
    a, b = float(source), float(downstream)
    return {"passed": abs(a - b) <= tolerance, "source": a, "downstream": b, "tolerance": tolerance}
