# 变量传递示例（精简版）

完整接口步骤字段见 `template.md`，这里只展示「脚本步骤」和「变量链」，避免重复贴全量骨架。

## 纯脚本步骤示例

```json
{
  "script": "base_dict=ARun.meta_data.get_env_base_test_data()\nindex = arun.get(\"CORE_DATA_INDEX\")\nif base_dict:\n    arun.set(\"productId\", ARun.meta_data.get_key_value(f\"$..{index}['产品信息']['产品']['1'].id\"))\n    arun.set(\"locationId\", ARun.meta_data.get_key_value(f\"$..{index}['地点组织']['车间']['1'].id\"))",
  "name": "通用数据获取"
}
```

## 紧凑步骤清单示例（交给 build_arun.py）

```json
[
  {
    "name": "通用数据获取",
    "script": "base_dict=ARun.meta_data.get_env_base_test_data()\nindex = arun.get(\"CORE_DATA_INDEX\")\nif base_dict:\n    arun.set(\"productId\", ARun.meta_data.get_key_value(f\"$..{index}['产品信息']['产品']['1'].id\"))\n    arun.set(\"locationId\", ARun.meta_data.get_key_value(f\"$..{index}['地点组织']['车间']['1'].id\"))"
  },
  {
    "name": "产品工艺路线获取",
    "method": "POST",
    "url": "linkim-pc/admin-console/main-data/workstation-route-definition/list",
    "body": {
      "productId": "$productId"
    },
    "teardown_code": "workstationRouteId = res.json()['data'][0]['id']\narun.set('workstationRouteId', workstationRouteId)"
  }
]
```

运行：`python3 generate-arun-api-scripts/scripts/build_arun.py steps.json`（默认生成到桌面 `~/Desktop/steps_arun.json`）

## 变量链

| 步骤 | 写入变量 | 来源 |
| --- | --- | --- |
| 通用数据获取 | `productId` / `locationId` | `ARun.meta_data.get_key_value` |
| 产品工艺路线获取 | `workstationRouteId` | `res.json()['data'][0]['id']` |
| 新增 | `subOrderNum` / `queryStartTime` / `queryEndTime` | `setup_code` |
| 查询列表 | `subOrderId` / `subProductionOrder` | `res.json()['data']['records'][-1]` |

规则：请求体里用 `$var` 引用上表变量；每个 `$var` 必须能追溯到「前一步提取 / setup_code 计算 / 流程显式给值 / 基础数据提取」之一。
