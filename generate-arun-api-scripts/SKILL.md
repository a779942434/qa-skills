---
name: generate-arun-api-scripts
description: >-
  把 OpenAPI/JSON/YAML 接口文档与自然语言业务流程转换为 ARun 平台可粘贴的自动化接口脚本 JSON。
  生成规则沿用 ARun 现有接口脚本样本：完整复制接口步骤字段、省略平台自增/审计字段、
  沿用样本环境默认值、在 teardown_code 中做响应数据提取与 assert、check 字段留空。
  当用户提供 Swagger/OpenAPI 文档并要求生成 ARun 接口脚本、自动化用例脚本、
  「生成这样 JSON 脚本并粘贴到 ARun」时使用；用户只给接口文档加一句话业务流
  （如「对问题点定义做主从表增删改查并全程校验」）也可直接生成。
---

# ARun 自动化接口脚本生成

## 目标

把「接口文档（OpenAPI/Swagger 或等价手工清单）」+「业务流程（自然语言描述）」转成可直接粘贴到
ARun 平台的步骤数组 JSON，数组元素是「纯脚本步骤」或「接口步骤」。

## 输入要求

三种输入模式，按用户实际给了什么选，优先用更短的：

- **模式一（默认优先，最短）**：接口文档 + 一句话业务流。URL/方法/参数从 OpenAPI/Swagger 文档推导，步骤骨架按 `references/business-templates.md` 展开，用户无需描述接口与变量链。
- **模式二**：接口文档 + 自述业务流。最低可执行输入 = 每个接口的 URL/method/请求体参数（必填/可选/类型）/响应关键字段 + 调用顺序 + 每个变量来源（前一步提取 / `setup_code` 计算 / 流程显式给值 / 基础数据提取）。
- **模式三（需反问一次）**：用户只给意图时，先按最小问题清单反问（接口文档在哪？对哪个实体做哪些操作？）再生成。

信息缺失时兜底不脑补：缺方法默认 `POST`；缺响应提取路径只生成流程显式要求的提取，不猜字段名；必填来源不明保留 `$fieldName` 并列「待确认/需造数」；缺环境参数沿用样本默认值（见 `references/template.md`）。

## 业务流模板（一句话展开，默认优先）

用户输入命中模板名时，模板负责步骤骨架、标准断言与变量链，用户不用逐条交代调用顺序和校验逻辑。模板清单（详见 [references/business-templates.md](references/business-templates.md)）：

- 基础模板：`crud`（5 步）、`crud+detail`（10 步，骨架参照 examples/问题点定义表_steps.json）。
- 模式模板：`count-before-after`（前后数量对比）、`generate-cancel`（生成-撤销-清零）、`status-verify`（状态流转校验）、`loop-items`（循环逐个处理）、`passthrough-body`（整值透传）、`if-switch`（条件分支）。
- 完整链路：`production-schedule`（生产排产全链路约 30 步）、`shift-handover`（交接班）。

模板展开规则、标准断言与 MES 域默认值（`enableInd=1`、`page=1`、`size=30`、`"前缀"+随机数` 造数）见 [references/business-templates.md](references/business-templates.md)。

展开后输出紧凑步骤清单，走下面的「自动生成流程」交给 build_arun.py（controller / json2text / project 覆盖均支持），不逐条贴完整字段骨架。

### 控制流自动识别（for / if）——用户描述到就自动加

话术命中下列意思时，不要把步骤平铺，直接包成 `controller` 步骤（嵌套也支持），不用等用户给控制器 JSON：

- **for 循环**：`循环` / `逐个` / `每个都` / `依次` / `重复 N 次` / `直到处理完`
  → `{"controller":"for","mode":"times","times":"${<计数变量>}","interval":"2","break_on_success":false,"continue_on_failure":false,"close":true,"steps":[...]}`；
  次数/列表来自前一步 teardown 提取（`arun.set('<计数变量>', len(...))`）。
- **if 条件**：`如果` / `若` / `当……时` / `否则` / `为空则` / `不为空才` / `只有……才`
  → `{"controller":"if","condition":"${a} == ${b}","steps":[...],"elif_branches":[],"else_steps":[],"elseClose":true,"ignore":false,"close":true}`；
  条件不满足直接跳过用 `"elseClose": true`，多分支用 `elif_branches` / `else_steps`。
- **语法要点**：控制器字段（`times` / `condition`）用 ARun 平台 `${var}` 插值；控制器内部接口步骤的 body 仍用 `$var`，两者共存不替代。
- 命中模板名 `loop-items` / `if-switch` 时按 `references/business-templates.md` 展开骨架。

## 生成流程

0. 优先识别业务流模板（`crud` / `crud+detail`）：命中则按 business-templates.md 展开步骤骨架，跳到步骤 3；未命中再走逐步解析。
1. 解析接口文档，整理「接口名 / URL / method / 入参 / 出参」。
2. 解析业务流，拆成有序步骤；每一步映射一个接口，标出需要的入参变量和要保存的响应变量。
3. 判断是否生成前置「通用数据获取」脚本步骤：流程用到产品/车间/设备/工艺路线等基础数据时才加。
4. 逐步骤生成 JSON：
   - 脚本步骤：`{"script": "<python>", "name": "<名称>"}`。
   - 接口步骤：按 references/template.md 的完整字段复制，省略平台自增/审计字段。
5. 输出前做自查：JSON 可解析、每个接口步骤含完整 `data`、`body.json` 中每个 `$var` 有来源或被列入待确认清单。

## 字段与变量规则（不可自行变更）

- **接口步骤字段**：完整复制 `references/template.md`，省略 `id`、`updator`、`creator`、`case_id`、`created`、`updated`、`locked_time`、`owner_id`。
- **默认值**：`api_type=1`、`project=13`、`origin=1`、`body_type="json"`、`loop=true`、`ssl=false`、`delay=0`、`cycles=1`、`verify=false`、`jsonschemaOpen=true`、`jsonschemaUpdate=false`。
- **Dubbo 默认值**：`registry_center.address=118.31.126.238:21811`、`protocol=1`、`timeout=3`；接口相关字段留空。
- **空占位结构**：`params`、`headers`、`retrying`、`variables`、`extract` 各一条 `{"checked": true, ...空值}`；`form_data`、`form_urlencoded` 各一条；`check` 一条空校验；`hook` 两侧空数组。
- **`setup_code`**：固定以 `# python 请求之前执行` 开头，随后生成随机数、时间或基础数据提取。
- **`teardown_code`**：固定以 `# python 请求之后执行` 开头，随后用 `res.json()['data']...` 提取并 `arun.set(...)`；业务断言用 `assert 条件, '中文失败提示'`。
- **请求体**：写在 `body.json`，变量一律 `$var` 引用。变量来源只允许：前一步提取、`setup_code` 计算、流程显式给值、基础数据提取。
- **前置造数**：仅当需要基础数据时生成 `{"script": ..., "name": "通用数据获取"}`，用 `ARun.meta_data.get_env_base_test_data()` 与 `ARun.meta_data.get_key_value(jsonpath)` 提取。

自动推导规则（命中即可用，减少用户描述）：

- **同名字段自动传递**：前一步提取的字段名与后续 body 字段同名时自动用 `$字段名` 引用（如新增响应有 `id`，后续 body `id` 自动接 `$id`）。
- **标准断言模板**：CRUD 固定用 `assert records, '...新增后未查询到记录'` / `assert int(res.json()['data']['total']) == 0, '...删除后仍能查询到记录'`。
- **MES 域默认值**：`enableInd=1`、`page=1`、`size=30`、造数命名 `"前缀"+str(random.randint(100000, 999999))`（编辑追加「编辑」）、枚举随机 `random.randint(0, 2)`。

## 可用函数集

仅使用 references/helper-functions.md 中列出的函数，遇到新函数先向用户确认，不臆造。

## 输出结构

默认以聊天中的可复制 JSON 代码块交付，不写文件；要求落盘时再指定路径。参考文档：
`references/template.md`（完整字段模板）、`references/helper-functions.md`（可用函数）、
`references/example.md`（变量传递示例）、`references/business-templates.md`（业务流模板一句话展开）。

## 自动生成流程（默认，省 token）

步骤较多时，不要逐条输出完整接口字段骨架。统一走「紧凑步骤清单 + 自动跑脚本」：

1. 输出一份步骤清单 `steps.json`（JSON 数组），每个元素只写：
   - 接口步骤：`name` / `url` / `method`（默认 POST）/ `body` / `setup_code` / `teardown_code`，可加 `project`（覆盖默认 13）/ `json2text`（整值透传）/ `ignore`
   - 脚本步骤：`name` / `script`
   - 控制流步骤：`{"controller":"for"|"if","steps":[...],其余控制器字段原样}`（可嵌套上面两种）
2. 跑脚本生成完整 JSON：`python3 generate-arun-api-scripts/scripts/build_arun.py steps.json`
   （默认输出 `~/Desktop/<清单名>_arun.json`；`-o` 指定路径，`-o -` 输出到 stdout）。
3. 脚本自动补齐 sample 的全部默认字段（dubbo/params/headers 等）、省略平台自增字段、校验 `$var` 来源。
4. 校验结果（步骤数、URL、无平台自增字段、`$var` 链完整）后**不贴完整 JSON**，最终回复只给桌面文件路径。小改动（如统一改 URL 前缀）只改清单重跑脚本。

`setup_code` / `teardown_code` 在清单里只写业务代码，脚本自动补首行注释。
注意：写入 `~/Desktop` 属沙箱外写操作，跑脚本时要非沙箱权限（require_escalated）。

## 省 token 交付策略

1. 小改动只发增量：如「统一改 URL 前缀」，给替换规则与替换后字符串，不重贴整份 JSON。
2. 交付优先用紧凑 JSON（`json.dumps(..., ensure_ascii=False)` 不带 indent）；要求易读再 pretty。
3. 复杂流程先用「步骤参数清单」对齐接口/字段/变量链，确认后一次性产出，避免返工。
4. 已输出过的公共字段骨架不重复引用，只列本次变化点。

## 避坑清单

1. 不脑补接口参数：文档没写又无法从前置步骤得到的必填字段，用 `$fieldName` 占位并单独提示。
2. 不臆造辅助函数：只用样本已出现的函数，新函数先确认。
3. `check` 保持空校验结构，断言统一放 `teardown_code`。
4. 大小写：`arun.set`/`arun.get` 用小写 `arun`；`ARun.meta_data` 用大写 `ARun`。
5. 每个 `$var` 必须能追溯来源；追溯不到的列进「待确认/需造数」。
6. 模板只是骨架不是事实来源：展开后必须按接口文档核对 URL/method/body；文档没有的必填字段用 `$fieldName` 占位，不硬填。
