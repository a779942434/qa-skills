# ARun 脚本可用函数集（仅限样本已出现）

生成 `setup_code` / `teardown_code` 时只允许使用下面的能力。遇到不在清单里的函数，先向用户确认。

## 运行时变量 / 上下文

| 名称 | 说明 |
| --- | --- |
| `res` | 当前接口请求的响应对象，用 `res.json()` 取 JSON 响应体 |
| `arun` | 运行时上下文，`arun.set(key, value)` 写变量，`arun.get(key)` 读变量（生成脚本统一用 `arun`） |
| `ARun` | 平台元数据上下文，`ARun.meta_data.*` 读取环境/基础数据；原样本脚本步骤里也出现过 `ARun.set`，生成时统一用 `arun.set` |

## 已知方法

### ARun.meta_data

```python
base_dict = ARun.meta_data.get_env_base_test_data()
value = ARun.meta_data.get_key_value("$..CORE_DATA_INDEX['产品信息']['产品']['1'].id")
```

- `get_env_base_test_data()`：取环境基础测试数据字典。
- `get_key_value(jsonpath)`：按 JSONPath 取基础数据中的某个值。

### arun 运行时读写

```python
arun.set("productId", value)
total = arun.get("total")
```

### 响应提取

```python
data = res.json()['data']
workstationRouteId = data[0]['id']
arun.set("workstationRouteId", workstationRouteId)
```

### 标准 Python 内置

```python
import random
subOrderNum = random.randint(100, 999)
arun.set("subOrderNum", subOrderNum)
```

### common_utils 时间工具

```python
queryStartTime = common_utils.get_date_time_with_delta(
    delta_day=0, out_format="tsms", date_time="", head_tail="HEAD"
)
queryEndTime = common_utils.get_date_time_with_delta(
    delta_day=6, out_format="tsms", date_time="", head_tail="TAIL"
)
arun.set("queryStartTime", queryStartTime)
arun.set("queryEndTime", queryEndTime)
```

## 变量引用语法

在 `body.json` 中引用变量时使用字符串 `$var`，例如：

```json
{
  "productId": "$productId",
  "workstationRouteId": "$workstationRouteId"
}
```
