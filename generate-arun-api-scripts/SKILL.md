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

把两部分输入转成一个可直接粘贴到 ARun 平台的步骤数组 JSON：

1. **接口文档**：OpenAPI / Swagger 的 JSON 或 YAML，或等价的手工接口清单。
2. **业务流程**：自然语言描述，按顺序说清每一步调哪个接口、入参从哪来、取响应里哪个字段存成哪个变量。

输出为一个 JSON 数组，数组元素是「纯脚本步骤」或「接口步骤」。

## 输入要求

三种输入模式，按用户实际给了什么选，优先用更短的：

- **模式一（默认优先，最短）**：接口文档 + 一句话业务流。用户给 OpenAPI/Swagger 文档（本地文件或 URL）与一句话（如「对问题点定义做主从表增删改查并全程校验」）。URL / 方法 / 参数从文档推导，步骤骨架按 [references/business-templates.md](references/business-templates.md) 的模板展开，用户无需逐条描述接口与变量链。
- **模式二**：接口文档 + 自述业务流。用户描述调用顺序与变量来源，AI 逐步映射（本技能原有流程，最低可执行输入见下）。
- **模式三（最简，需反问一次）**：用户只给意图（如「帮我生成问题点定义的增删改查脚本」）。AI 先按最小问题清单反问一次（接口文档在哪？对哪个实体做哪些操作？），收集完再生成，不要求用户预先写全描述。

模式二的最低可执行输入：

- 每个接口的 URL（path）、HTTP 方法、请求体参数及必填/可选/类型、响应体关键字段。
- 业务流的调用顺序；每个变量的来源：前一步提取 / `setup_code` 计算 / 流程显式给值 / 基础数据提取。

信息缺失时按规则处理，不要脑补：

- 缺方法：默认 `POST`。
- 缺响应提取路径：只生成流程显式要求的提取，不猜字段名。
- 必填字段来源不明：保留 `$fieldName`，并在最终回复中列出「待确认/需造数」清单。
- 缺环境参数：沿用样本默认值（见 references/template.md）。
- 模式三下缺失信息由一轮反问补齐；反问后仍缺的按上面规则兜底。

## 业务流模板（一句话展开，默认优先）

用户输入命中模板名时，模板负责步骤骨架、标准断言与变量链，用户不用逐条交代调用顺序和校验逻辑。模板清单（详见 [references/business-templates.md](references/business-templates.md)）：

- 基础模板：`crud`（5 步）、`crud+detail`（10 步，骨架参照 examples/问题点定义表_steps.json）。
- 模式模板：`count-before-after`（前后数量对比）、`generate-cancel`（生成-撤销-清零）、`status-verify`（状态流转校验）、`loop-items`（循环逐个处理）、`passthrough-body`（整值透传）、`if-switch`（条件分支）。
- 完整链路：`production-schedule`（生产排产全链路约 30 步）、`shift-handover`（交接班）。

模板展开规则、标准断言与 MES 域默认值（`enableInd=1`、`page=1`、`size=30`、`"前缀"+随机数` 造数）见 [references/business-templates.md](references/business-templates.md)。

展开后输出紧凑步骤清单，走下面的「自动生成流程」交给 build_arun.py（controller / json2text / project 覆盖均支持），不逐条贴完整字段骨架。

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

- **接口步骤字段**：完整复制 references/template.md，但省略 `id`、`updator`、`creator`、`case_id`、`created`、`updated`、`locked_time`、`owner_id`。
- **默认值**：`api_type=1`、`project=13`、`origin=1`、`body_type="json"`、`loop=true`、`ssl=false`、`delay=0`、`cycles=1`、`verify=false`、`jsonschemaOpen=true`、`jsonschemaUpdate=false`。
- **Dubbo 默认值**：`registry_center.address=118.31.126.238:21811`、`protocol=1`、`timeout=3`；接口相关字段留空。
- **空占位结构**：`params`、`headers`、`retrying`、`variables`、`extract` 各一条 `{"checked": true, ...空值}`；`form_data`、`form_urlencoded` 各一条；`check` 一条空校验；`hook` 两侧空数组。
- **`setup_code`**：固定以 `# python 请求之前执行` 开头，随后生成随机数、时间或基础数据提取。
- **`teardown_code`**：固定以 `# python 请求之后执行` 开头，随后用 `res.json()['data']...` 提取并 `arun.set(...)`；业务断言用 `assert 条件, '中文失败提示'`。
- **请求体**：写在 `body.json`，变量一律 `$var` 引用。变量来源只允许：前一步提取、`setup_code` 计算、流程显式给值、基础数据提取。
- **前置造数**：仅当需要基础数据时生成 `{"script": ..., "name": "通用数据获取"}`，用 `ARun.meta_data.get_env_base_test_data()` 与 `ARun.meta_data.get_key_value(jsonpath)` 提取。

自动推导规则（命中即可用，减少用户描述）：

- **同名字段自动传递**：前一步响应提取的字段名与后续步骤 body 字段同名时，自动用 `$字段名` 引用（如新增响应有 `id`，后续 body 的 `id` 自动接 `$id`），无需用户交代变量链。
- **标准断言模板**：CRUD 类校验固定用 `assert records, '...新增后未查询到记录'` / `assert int(res.json()['data']['total']) == 0, '...删除后仍能查询到记录'`，用户不用描述校验逻辑。
- **MES 域默认值**：`enableInd=1`、`page=1`、`size=30`、造数命名 `"前缀"+str(random.randint(100000, 999999))`（编辑追加"编辑"字样）、枚举随机 `random.randint(0, 2)`——见 references/business-templates.md，用户不用写。

## 可用函数集

仅使用 references/helper-functions.md 中列出的函数，遇到新函数先向用户确认，不臆造。

## 输出结构

默认以聊天中的可复制 JSON 代码块交付，不写文件；用户要求落盘时再指定路径。

- 完整字段模板：见 [references/template.md](references/template.md)
- 可用函数说明：见 [references/helper-functions.md](references/helper-functions.md)
- 变量传递示例：见 [references/example.md](references/example.md)
- 业务流模板（crud / crud+detail 一句话展开）：见 [references/business-templates.md](references/business-templates.md)

## 自动生成流程（默认，省 token）

步骤较多时，不要逐条输出完整接口字段骨架。统一走「紧凑步骤清单 + 自动跑脚本」：

1. 输出一份步骤清单 `steps.json`（JSON 数组），每个元素只写：
   - 接口步骤：`name` / `url` / `method`（默认 POST）/ `body` / `setup_code` / `teardown_code`，可加 `project`（覆盖默认 13）/ `json2text`（整值透传）/ `ignore`
   - 脚本步骤：`name` / `script`
   - 控制流步骤：`{"controller": "for"|"if", "steps": [...], 其余控制器字段原样}`（嵌套步骤同样支持上面两种）
2. 自动运行脚本生成完整 JSON：

   ```bash
   python3 generate-arun-api-scripts/scripts/build_arun.py steps.json
   # 默认输出到桌面 ~/Desktop/<步骤清单名>_arun.json；
   # 指定路径用 -o，输出到 stdout 用 -o -
   ```

3. 脚本自动补齐 sample 的全部默认字段（dubbo/params/headers 等）、省略平台自增字段、校验 `$var` 来源。
4. 校验生成结果（步骤数、URL、无平台自增字段、`$var` 链完整）后，不贴完整 JSON，只在最终回复里给出桌面文件路径。
5. 小改动（如统一改 URL 前缀）只改步骤清单再重跑脚本，不重发全量 JSON。

`setup_code` / `teardown_code` 在清单里只写业务代码，脚本会自动加 `# python 请求之前执行` / `# python 请求之后执行` 首行。

注意：写入 `~/Desktop` 属于沙箱外写操作，自动跑脚本时用非沙箱权限（require_escalated）执行。

## 省 token 交付策略

1. 小改动只发增量，不重发全量：像「统一改 URL 前缀」这类全局替换，直接给替换规则和替换后的字符串，不要整份 JSON 再贴一遍。
2. 最终交付优先用紧凑 JSON（`json.dumps(..., ensure_ascii=False)` 不带 indent）；用户明确要求易读再 pretty。
3. 复杂流程先用「步骤参数清单」与用户对齐接口/字段/变量链，确认无误后再一次性产出最终 JSON，避免来回返工。
4. 同一次对话里，已输出过的公共字段骨架不要重复引用；只列本次变化点。

## 避坑清单

1. 不脑补接口参数：Swagger/流程没写、又无法从前置步骤得到的必填字段，用 `$fieldName` 占位并单独提示。
2. 不臆造辅助函数：只用样本已出现的函数，新函数先确认。
3. `check` 保持空校验结构，断言统一放 `teardown_code`，避免与 ARun 实际用法冲突。
4. 变量大小写与命名：`arun.set`/`arun.get` 用小写 `arun`，`meta_data` 用大写 `ARun.meta_data`。
5. 每个 `$var` 必须能追溯到来源；追溯不到的列进「待确认/需造数」。
6. 模板只是步骤骨架，不是事实来源：展开后必须按接口文档核对 URL / 方法 / body 字段；文档没有的必填字段用 `$fieldName` 占位并提示，不因模板有就硬填。
