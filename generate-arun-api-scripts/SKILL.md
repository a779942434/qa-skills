---
name: generate-arun-api-scripts
description: >-
  把 OpenAPI/JSON/YAML 接口文档与自然语言业务流程转换为 ARun 平台可粘贴的自动化接口脚本 JSON。
  生成规则沿用 ARun 现有接口脚本样本：完整复制接口步骤字段、省略平台自增/审计字段、
  沿用样本环境默认值、在 teardown_code 中做响应数据提取与 assert、check 字段留空。
  当用户提供 Swagger/OpenAPI 文档并要求生成 ARun 接口脚本、自动化用例脚本、
  「生成这样 JSON 脚本并粘贴到 ARun」时使用。
---

# ARun 自动化接口脚本生成

## 目标

把两部分输入转成一个可直接粘贴到 ARun 平台的步骤数组 JSON：

1. **接口文档**：OpenAPI / Swagger 的 JSON 或 YAML，或等价的手工接口清单。
2. **业务流程**：自然语言描述，按顺序说清每一步调哪个接口、入参从哪来、取响应里哪个字段存成哪个变量。

输出为一个 JSON 数组，数组元素是「纯脚本步骤」或「接口步骤」。

## 输入要求

最低可执行输入：

- 每个接口的 URL（path）、HTTP 方法、请求体参数及必填/可选/类型、响应体关键字段。
- 业务流的调用顺序；每个变量的来源：前一步提取 / `setup_code` 计算 / 流程显式给值 / 基础数据提取。

信息缺失时按规则处理，不要脑补：

- 缺方法：默认 `POST`。
- 缺响应提取路径：只生成流程显式要求的提取，不猜字段名。
- 必填字段来源不明：保留 `$fieldName`，并在最终回复中列出「待确认/需造数」清单。
- 缺环境参数：沿用样本默认值（见 references/template.md）。

## 生成流程

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

## 可用函数集

仅使用 references/helper-functions.md 中列出的函数，遇到新函数先向用户确认，不臆造。

## 输出结构

默认以聊天中的可复制 JSON 代码块交付，不写文件；用户要求落盘时再指定路径。

- 完整字段模板：见 [references/template.md](references/template.md)
- 可用函数说明：见 [references/helper-functions.md](references/helper-functions.md)
- 变量传递示例：见 [references/example.md](references/example.md)

## 使用生成脚本（推荐，省 token）

步骤较多时，不要逐条输出完整接口字段骨架。优先输出「紧凑步骤清单」并让用户本地跑生成脚本：

1. 输出一份步骤清单 `steps.json`（JSON 数组），每个元素只写：
   - 接口步骤：`name` / `url` / `method`（默认 POST）/ `body` / `setup_code` / `teardown_code`
   - 脚本步骤：`name` / `script`
2. 用户运行：

   ```bash
   python scripts/build_arun.py steps.json -o arun_script.json
   ```

3. 脚本自动补齐 sample 的全部默认字段（dubbo/params/headers 等）、省略平台自增字段、校验 `$var` 来源。
4. 小改动（如统一改 URL 前缀）只改 `steps.json` 再重跑脚本，不重发全量 JSON。

`setup_code` / `teardown_code` 在清单里只写业务代码，脚本会自动加 `# python 请求之前执行` / `# python 请求之后执行` 首行。

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
