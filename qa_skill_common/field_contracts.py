# -*- coding: utf-8 -*-
"""字段契约注册表：把页面标签、真实控件类型、接口字段和值格式固化。

目标：避免同一字段在 UI 标签、接口参数和值格式之间反复试错，例如
“开始时间/开工日期”都映射到 queryStartTime，查询条件 0/1 分别代表开工/完工。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class FieldContract:
    page: str
    label: str
    control: str
    api_field: str
    value_format: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    def matches(self, name: str) -> bool:
        needle = str(name or "").strip()
        return needle == self.label or needle in self.aliases

    def to_dict(self) -> dict:
        data = asdict(self)
        data["aliases"] = list(self.aliases)
        return data


class FieldContractRegistry:
    def __init__(self):
        self._items: list[FieldContract] = []

    def register(self, contract: FieldContract) -> None:
        key = (contract.page, contract.label, contract.api_field)
        self._items = [x for x in self._items if (x.page, x.label, x.api_field) != key]
        self._items.append(contract)

    def resolve(self, page: str, label: str) -> FieldContract | None:
        for item in reversed(self._items):
            if item.page == page and item.matches(label):
                return item
        return None

    def for_page(self, page: str) -> list[FieldContract]:
        return [x for x in self._items if x.page == page]

    def to_dict(self) -> dict:
        out: dict[str, list[dict]] = {}
        for item in self._items:
            out.setdefault(item.page, []).append(item.to_dict())
        return out


def default_registry() -> FieldContractRegistry:
    reg = FieldContractRegistry()
    contracts = [
        FieldContract(
            "委外计划排产", "开工日期", "date", "queryStartTime",
            "timestamp_ms_day_start", ("开始时间", "开始日期"),
            "日期筛选起点；查询时补到当天 00:00:00",
        ),
        FieldContract(
            "委外计划排产", "完工日期", "date", "queryEndTime",
            "timestamp_ms_day_end", ("结束时间", "结束日期"),
            "日期筛选终点；查询时补到当天 23:59:59",
        ),
        FieldContract(
            "委外计划排产", "查询条件", "select", "queryType",
            "0=开工日期;1=完工日期", (),
            "UI 文本切换到接口 queryType 的映射",
        ),
        FieldContract(
            "委外计划排产", "生产订单分单号", "select/multi", "subProductionOrderList",
            "list[string]", (), "筛选为多选；无选择时请求不传该字段",
        ),
        FieldContract(
            "委外计划排产", "地点组织", "cascader/multi", "locationIdList",
            "list[string]", ("地点",), "筛选为多选，提交后请求包含 locationIdList",
        ),
        FieldContract(
            "委外计划排产", "委外状态", "select/multi", "statusList",
            "list[int];待委外=0;部分委外=1;全部委外=2", ("状态",),
            "空选表示全部",
        ),
    ]
    for item in contracts:
        reg.register(item)
    return reg
