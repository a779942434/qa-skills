# ARun 业务流模板（一句话展开）

用户只需给「接口文档 + 一句话业务流」（如「对问题点定义做主从表增删改查并全程校验」），
按本模板展开步骤骨架。

> 模板只是步骤骨架，不是事实来源：URL / 方法 / body 字段以接口文档为准；
> 文档没有的必填字段用 `$fieldName` 占位并列入待确认清单（见 SKILL.md 避坑清单）。
>
> 所有模板（含 controller / json2text / project 覆盖）统一走「紧凑步骤清单 + build_arun.py」。

## 模板一：crud（主表增删改查 + 全程校验，5 步）

适用：对单个实体做 新增 → 查询 → 编辑 → 删除 → 校验。

| # | 步骤名 | method / URL | body | teardown_code |
| --- | --- | --- | --- | --- |
| 1 | 新增 | `POST <实体URL>` | 唯一业务字段 `"<前缀>测试"+随机数`、枚举随机、`enableInd=1` 等领域默认值 | — |
| 2 | 新增后查询 | `POST <实体URL>/page` | 唯一业务字段 `xxxLike: $<字段>`、`page:1, size:30` | `records = res.json()['data']['records']`；`assert records, '<实体>新增后未查询到记录'`；`arun.set('<实体>Id', records[-1]['id'])` |
| 3 | 编辑 | `PUT <实体URL>` | `"id": "$<实体>Id"`、唯一字段改 `"<前缀>测试编辑"+随机数` | — |
| 4 | 删除 | `POST <实体URL>/batch-delete` | `["$<实体>Id"]` | — |
| 5 | 删除后校验 | `POST <实体URL>/page` | `"id": "$<实体>Id"`、`page:1, size:30` | `assert int(res.json()['data']['total']) == 0, '<实体>删除后仍能查询到记录'` |

## 模板二：crud+detail（主从表增删改查 + 全程校验，10 步）

适用：主表 + 子表（明细）两个实体，子表挂在主表 `id` 下。
完整样例见 `examples/问题点定义表_steps.json`（问题点定义 + 问题点定义明细）。

| # | 步骤名 | 说明 |
| --- | --- | --- |
| 1 | 主表新增 | 同 crud 新增 |
| 2 | 主表查询 | 取主表 `id` → `arun.set('<主表>Id', ...)` |
| 3 | 主表编辑 | `"id": "$<主表>Id"` |
| 4 | 子表新增 | body 带 `"<主表外键>": "$<主表>Id"`（如 `issueDefinitionId`） |
| 5 | 子表查询 | 取子表 `id` → `arun.set('<子表>Id', ...)` |
| 6 | 子表编辑 | `"id": "$<子表>Id"` |
| 7 | 子表删除 | `POST <子表URL>/batch-delete`，body `["$<子表>Id"]` |
| 8 | 子表删除校验 | 按子表 `id` 查 `total == 0` |
| 9 | 主表删除 | `POST <主表URL>/batch-delete`，body `["$<主表>Id"]` |
| 10 | 主表删除校验 | 按主表 `id` 查 `total == 0` |

## 模板三：count-before-after（前后数量对比）

适用：操作会产生/删除记录，需断言数量变化（如一键排产前后、派单前后）。

| # | 步骤 | teardown_code 要点 |
| --- | --- | --- |
| 1 | 操作前查询（同一查询接口） | 列表：`arun.set('<前缀>Before', len(res.json()['data']))`；分页：`arun.set('<前缀>Before', int(res.json()['data']['total']))` |
| 2 | 操作 | 动作接口，通常无提取 |
| 3 | 操作后查询（同一查询接口） | `assert <后> > <前>, '<动作>失败，请检查数据'`；需要 id 时追加 `arun.set('<实体>Id', res.json()['data'][0]['id'])` |

参照样本：`device-plan/list` 前后（工序排产）、`dispatch/info` 前后（派单详情）。

## 模板四：generate-cancel（生成-撤销-清零）

适用：生成类操作及其撤销，校验「生成数量一致、撤销后清零」（如工序计划、工序排产）。

| # | 步骤 | 要点 |
| --- | --- | --- |
| 1 | 触发生成（如 generate-info） | teardown 存中间量：`arun.set('<中间量>', res.json()['data'])` |
| 2 | 确认生成（如 generate） | 整值透传（模板七）；teardown 存生成数：`arun.set('<生成数>', len(res.json()['data']))` |
| 3 | 查询生成结果 | 断言 `int(res.json()['data']['total']) == <生成数>`，中文失败提示 |
| 4 | 状态校验（可选） | 按 hasXxxPlan / statusList 过滤（模板五） |
| 5 | 撤销（如 cancel） | — |
| 6 | 撤销后查询 | 同步骤 3 的查询，断言 `total == 0` |

参照样本：工序计划 生成/撤销、工序排产 生成/撤销。

## 模板五：status-verify（状态流转校验）

适用：操作后验证记录进入期望状态（已关闭 / 进行中 / 已生成某计划）。

- 查询 body 带状态过滤：`statusList: [<状态码>]`、`hasXxxPlan: 1`、`queryType: 0/1` 等。
- teardown 固定：`assert <过滤查询命中的 id> == arun.get('<记录 id>'), '<期望状态>未生效，请检查流程'`。
- 状态/枚举参数语义写进 `desc`（如「queryType：0 分单开工日期；1 分单完工日期」），便于排障。

参照样本：`statusList=[4]` 已关闭、`statusList=[2]` 进行中、`hasProcedurePlan=1`、`hasDevicePlan=1`。

## 模板六：loop-items（循环逐个处理，controller: for）

适用：对上游提取的列表逐个执行同一操作（如把未下班用户逐个下班）。紧凑清单直接写 `controller` 字段，脚本递归构建嵌套步骤：

```json
{
  "controller": "for",
  "steps": [ <单个操作步骤紧凑清单> ],
  "mode": "times",
  "times": "${<计数变量>}",
  "interval": "2",
  "break_on_success": false,
  "continue_on_failure": false,
  "close": true
}
```

- 计数变量由前一步提取：`arun.set('<计数变量>', len(<列表>))`。
- 子步骤 setup 从列表取第一个元素：`<列表> = arun.get('<列表变量>')`；`if <列表>: <元素> = <列表>[0]`，再拆字段 `arun.set(...)`。

参照样本：交接班「将当前未下班用户下班」。

## 模板七：passthrough-body（整值透传，json2text）

适用：下游接口的 body 就是上游响应原样（确认派单 / 确定生成 / 撤销派单）。清单里加 `"json2text": true`，脚本会写入 `data.json2text`：

- 上游 teardown：`arun.set('<变量>', res.json()['data'])`。
- 下游步骤 `body` 写 `"$<变量>"`，并加 `"json2text": true`（平台按文本提交 JSON）。

参照样本：确定生成 `body: "$subOrderList"`、确认派单 `body: "$dispatch_info"`、撤销派单 `body: "$dispatch_idList"`。

## 模板八：if-switch（条件分支执行，controller: if）

适用：满足条件才执行某步骤（如班次变化才切换班次）。紧凑清单直接写 `controller` 字段：

```json
{
  "controller": "if",
  "steps": [ <条件命中时的步骤紧凑清单> ],
  "elif_branches": [],
  "else_steps": [],
  "elseClose": true,
  "condition": "${<变量1>} != ${<变量2>} or ...",
  "ignore": false,
  "close": true
}
```

- 条件用 `${var}` 占位符（平台语法），不是 Python。
- 比较的变量来自前两步提取（如班次快照 id / 日期）。

参照样本：交接班「切换为当前班次」。

## 完整链路一：production-schedule（生产排产全链路）

一句话触发：「走一遍生产排产全链路」；「生产排产：新增→编辑→生成工序计划→撤销→工序排产→撤销→关闭/重启→派单→撤销→删除」。

前置数据：通用数据获取（productId / locationId）→ 产品工艺路线获取（workstationRouteId）→ 工艺路线工序 id（procedureId）。

主链路（约 30 步，全部可走紧凑步骤清单）：

1. **新增** sub-order：body 用 `productId / workstationRouteId / subOrderNum / startTime / endTime / locationId`；setup 用 `common_utils.get_date_time_with_delta` 生成时间区间。
2. **查询** sub-order/page：取 subOrderId、subProductionOrder。
3. **编辑**：PUT，body 带 id + 全部字段（样本中顶层 method 为 POST、data.method 为 PUT，以 data.method 为准）。
4. **生成工序计划**：generate-info（存 subOrderList）→ generate（整值透传）→ 查 procedure-plan/page 断言数量 == generateSum → 查 sub-order `hasProcedurePlan=1` 校验 → cancel → 查数量 == 0。
5. **工序排产**：available-device/list（`deviceRule=2`，取 deviceId）→ schedule-preview（存 detailList）→ device-plan/list 前测 → schedule 一键排产（`auditInd=0`）→ device-plan/list 后测断言 > 前测 → device-plan/page 断言 total == 后测 → sub-order `hasDevicePlan=1` 校验 → cancel-schedule → device-plan/list 断言 == 0。
6. **关闭/重启**：sub-order/close（idList）→ 查 `statusList=[4]` → cancel-close（body `["$subOrderId"]`）→ 查 `statusList=[2]`。
7. **派单**：dispatch/preview（存 dispatch_info + dispatch_info_sum）→ dispatch/confirm（整值透传）→ dispatch/info 断言 total == sum（存 idList）→ dispatch/cancel（整值透传）→ dispatch/info 断言 total == 0。
8. **清理**：procedure-plan/cancel → sub-order/batch-delete（body `["$subOrderId"]`）→ sub-order/page 断言 total == 0。

## 完整链路二：shift-handover（交接班）

一句话触发：「走一遍交接班流程」；「交接班：查人→查班次→未下班用户循环下班→条件切换班次→上班→下班」。

前置数据：通用数据获取（stationId / deviceId）。

1. **刷卡查人** onDutySwipingCardCheck（`$carNumber` 由平台/环境变量提供）→ workId。
2. **查当前班次** queryCurrentShiftOfTheStation：GET，URL 带 `?stationId=$stationId`，teardown 防御式提取 shiftSnapshootId1 / shiftDateTime1。
3. **查候选班次** getCandidateShiftDtoAndCurrent → shiftSnapshootId / shiftDateTime。
4. **for 循环**（times=${count}）：把未下班用户逐个 offDuty/swipingCard（模板六）。
5. **if 条件**：shiftSnapshootId1 / shiftDateTime1 有变化时 switchShifts（模板八）。
6. **上班** onDuty/swipingCard（stationId / userId=$workId）。
7. **再查班次**（验证切换结果）。
8. **下班** offDuty/swipingCard。

本链路含 controller / json2text 步骤，全部走紧凑步骤清单。

## 变量链（模板固定，无需用户交代）

| 变量 | 来源 |
| --- | --- |
| `<实体>Id`（主表/子表 id） | 各自新增后查询 `records[-1]['id']` |
| 唯一业务字段（如 `issueType`） | `setup_code`：`"<前缀>测试" + str(random.randint(100000, 999999))`；编辑步追加「编辑」字样 |
| 枚举字段（如 `craftEquipmentType`） | `setup_code`：`random.randint(0, 2)` |
| 前后数量（`<前缀>Before` / 后测） | `len(res.json()['data'])` 或 `int(res.json()['data']['total'])` |
| 生成数 / 中间量 | 确认生成步骤 teardown 提取 |
| 列表透传（subOrderList / detailList / dispatch_info） | 上游 teardown `arun.set('<变量>', res.json()['data'])`，下游 `json2text` 透传 |
| 状态校验命中 id | 过滤查询 `records[-1]['id']` 与 `arun.get('<记录 id>')` 比较 |

## MES 域默认值（模板自动补，用户不用写）

- `enableInd=1`、`incloudDetail=false`（若接口文档有该字段）
- 列表查询固定 `page=1`、`size=30`
- 造数命名：`"<业务前缀>测试" + str(random.randint(100000, 999999))`（编辑再加「编辑」）
- 详情/枚举字段随机：`random.randint(0, 2)`
- 状态/枚举语义以接口文档为准，样本参考：`statusList` 1=待排产、2=进行中、4=已关闭；`queryType` 0=开工、1=完工；`deviceRule` 2=按分单地点组织；`auditInd=0` 不审核；`hasProcedurePlan` / `hasDevicePlan=1` 已生成

## 展开规则

1. 识别模板名（crud / crud+detail / count-before-after / generate-cancel / status-verify / loop-items / passthrough-body / if-switch / production-schedule / shift-handover）+ 实体名 + 接口文档。
2. 按骨架生成步骤：URL / 方法 / body 字段从接口文档推导并逐一核对；文档没有的必填字段 → `$fieldName` 占位 + 待确认清单。
3. 所有步骤统一走「紧凑步骤清单 + build_arun.py」：脚本递归构建 controller 步骤（for/if，可嵌套）、保留 `json2text` / `ignore`、支持 `project` 覆盖、校验 body 与 url 里的 `$var`。
4. `desc` 注释约定：状态/枚举参数语义写进 desc（queryType / deviceRule / hasXxxPlan），生成时自动带注释。
5. 样本注意：编辑/GET 步骤可能出现顶层 method 与 data.method 不一致（顶层 POST、data 内 PUT/GET），以 data.method 为准。
