# -*- coding: utf-8 -*-
"""测试批次与数据配方工具：批次隔离、唯一编号、前置条件校验。"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


def make_batch_id(prefix: str, now: datetime | None = None, short: bool = True) -> str:
    """生成带日期和随机后缀的测试批次号，避免重试污染旧数据。"""
    dt = now or datetime.now()
    clean = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", str(prefix or "QA")).strip("-") or "QA"
    suffix = uuid.uuid4().hex[:8] if short else uuid.uuid4().hex
    return f"{clean}-{dt.strftime('%Y%m%d')}-{suffix}"


def make_numbered_codes(batch_id: str, stem: str, count: int, width: int = 2) -> list[str]:
    if count < 0:
        raise ValueError("count 不能为负数")
    return [f"{batch_id}-{stem}-{i:0{width}d}" for i in range(1, count + 1)]


@dataclass(frozen=True)
class DataRecipe:
    """一条可复用的数据配方；requires 表示必须先满足的业务前置。"""
    name: str
    values: dict[str, Any] = field(default_factory=dict)
    requires: tuple[str, ...] = ()
    notes: str = ""


class RecipeRegistry:
    def __init__(self):
        self._items: dict[str, DataRecipe] = {}

    def register(self, recipe: DataRecipe) -> None:
        self._items[recipe.name] = recipe

    def get(self, name: str) -> DataRecipe:
        if name not in self._items:
            raise KeyError(f"未注册的数据配方: {name}")
        return self._items[name]


def validate_recipe(recipe: DataRecipe, resolver: Callable[[str], Any]) -> dict:
    """用 resolver 检查 required 前置是否可用；不伪造缺失数据。"""
    missing = []
    details = {}
    for key in recipe.requires:
        try:
            value = resolver(key)
        except Exception as exc:
            value = None
            details[key] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
        else:
            details[key] = {"ok": bool(value), "value": value}
        if not value:
            missing.append(key)
    return {"ok": not missing, "recipe": recipe.name, "missing": missing, "details": details}


def default_registry() -> RecipeRegistry:
    reg = RecipeRegistry()
    reg.register(DataRecipe(
        "委外计划排产-零件默认生成",
        values={"product": "已启用产品", "dates": "有效范围", "demand": ">0"},
        requires=("enabled_product", "workstation_route"),
        notes="零件委外默认生成链路",
    ))
    reg.register(DataRecipe(
        "委外计划排产-工序导入",
        values={"product": "已启用产品", "route": "属于产品", "procedure": "属于路线"},
        requires=("enabled_product", "workstation_route", "procedure_in_route"),
        notes="工序导入必须同时具备产品、路线、工序三层匹配",
    ))
    reg.register(DataRecipe(
        "停用产品导入独立验证",
        values={"product": "已停用产品"},
        requires=("disabled_product", "enabled_route", "procedure_in_route"),
        notes="若没有可用路线，导入会先命中路线错误，无法独立验证产品停用提示",
    ))
    return reg
