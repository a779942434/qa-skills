---
name: ones-create-linked-defect
version: 2.1.0
description: >-
  ONES 缺陷全流程：根据本地缺陷清单在 ones.shuyilink.com 中处理缺陷工作项——
  新建关联缺陷（关联内容-新建关联工作项-缺陷类型，填内容/必填字段/证据），
  回归后关闭已通过的缺陷单、评论@处理人说明未修复并附证据，
  以及把主工单流转到目标状态（如集成测试通过待验收）。
  当用户给出 ONES 工单链接并要求"新建关联缺陷/关联工作项""提缺陷"
  "把缺陷清单录入 ONES""处理缺陷流转""回归验证/处理缺陷单"
  "bug单关闭后流转主工单"时使用；依赖本机 Edge 登录态和常驻浏览器
  （CDP 默认 9334，可在 config/settings.yaml 调整）。
---

# ONES 缺陷全流程（创建 / 回归后处理 / 主工单流转）

> 本技能自带公共实现（`scripts/qa_skill_common/`），**可独立安装**。
> **只读本文件即可开工**；涉及弹窗/选择器/上传/评论/状态流转时**必须先读** `references/ones-ui.md`。

## 首次使用（3 步）

1. **自检**：`python scripts/check_env.py`（应无 FAIL；WARN 按提示处理）。
2. **一键引导常驻浏览器**：`python scripts/ones_bootstrap.py`（默认 dry-run，只自检并打印步骤）；
   确认后 `python scripts/ones_bootstrap.py --apply` 后台启动常驻 Edge（自动复制本机 Edge 登录态）。
   **首次登录 / 飞书授权**加 `--visible` 完成 SSO，之后切回默认静默运行。
3. **配环境（按需）**：ONES 相关变量与配置文件见 `scripts/qa_skill_common/references/environment.md`。

> **读取顺序**：先读本文件 → 操作 ONES UI 前读 `references/ones-ui.md` → 稳定操作优先调用
> `scripts/ones_helpers.py` 已封装函数，避免自行重造 UI 定位。

## 概述

把本地 `bug-reports/` 缺陷清单登记为工单的关联缺陷工作项，回归后按结果处理：通过的关闭、
未通过的评论 @处理人，最后把主工单流转到目标状态。全程复用本机 Edge 的飞书/ONES 登录态。

支持 Windows 与 macOS：浏览器路径、会话目录由 `scripts/ones_config.py` 按平台自动探测，可用
`config/settings.yaml` 或环境变量覆盖；客户项目/人员/优先级等字段统一维护在
`config/field-mapping.yaml`（换项目只改配置，不动本文件与 references）。

**上游衔接**：本地缺陷清单由 `web-blackbox-testing` 产出（命名 `bug-reports/YYYY-MM-DD_功能名_缺陷清单.md`，
含 环境/操作步骤/预期/实际/复现率/严重程度/需求引用）。本技能负责录入，并按清单文末
「回归验证」段执行关闭或评论 @处理人。

## 前置

1. 常驻浏览器已登录 ONES（CDP 默认 9334）。未启动时 `python scripts/ones_edge_server.py [工单URL]`——
   默认**后台静默启动**（headless），自动准备登录态（v20 Cookie 只能由 Edge 本体解密）。
   监管器每 5 秒检查 `/json/version` + `/json/list`，Edge 假死/退出时自动重启同一受管 profile
   （默认最多 3 次，`--max-restarts 0` 为无限）；首次登录/飞书授权加 `--visible`。
2. 本地缺陷清单在 `<产物根>/bug-reports/`（产物根与查找顺序见 environment.md；目录可在
   `config/settings.yaml` 的 `bug_reports_dir` 或 `ONES_BUG_REPORTS_DIR` 调整），按工单标题中的功能名匹配；
   **注意看文末「回归验证」段**确定每个 BUG 是 通过 / 未通过 / 产品口径不算缺陷。
3. 证据文件（截图、导入 Excel）在对应功能的测试输出目录，索引见 `config/field-mapping.yaml` 的 `evidence_dirs`。

## 新项目接入（一次性）

换新客户项目时先做一次字段/选项发现，写入 `config/field-mapping.yaml` 的 profile；之后日常提缺陷只跑 CLI。

**推荐一键接入**：`python scripts/ones_project_setup.py --work-order <工单URL> --profile <新项目名> [--env-keyword <关键词>]`
（`--dry-run` 先看不落盘）。它完成：

1. 按「项目 + 缺陷类型」查 `issueTypeScopes` 得 `issue_type_scope_uuid`——**不需要工单已有缺陷，也不用历史缺陷复制模板**。
2. 用 `get_task_required_fields()` 从主工单取来源项目、来源客户、功能模块、产品负责人、优先级、前端/后端人员 uuid。
3. 从缺陷类型字段定义读「系统环境 R3UqL3Vm」选项，`--env-keyword` 唯一命中时写入 uuid。

严重程度是全局固定选项（默认「一般」）；负责人/验证人 = 当前登录账号，运行期自动读取，均无需配置。
全局常量见 `references/ones-ui.md`「全局常量表」。

## 工作流

1. **连接浏览器**：`ones_helpers.connect()` 连 CDP（默认 9334）并**复用已有 ONES 页面**；CDP 不健康由
   `ones_edge_server` 监管器自动重启，客户端只等待/重连，不自行杀 Edge。跳飞书授权页时点「授权」完成 SSO。
   不要重复打开多个 ONES 工单页/弹窗（标签页堆积会导致 CDP 超时）。
2. **打开工单**：访问用户给的工单 URL（任务 UUID 在 URL 尾部），读标题与 ID，据此定位本地缺陷清单。
   读字段只用 `get_task_required_fields()`，**不要打印/搬运完整 `field_values` 或描述富文本**。
3. **新建关联缺陷**（清单里有未登记缺陷时）——**优先 API 直连**：
   - 字段选项 uuid 未缓存时，优先后 `ones_project_setup.py --env-keyword` 从字段定义解析写入 profile；
     仅当 GraphQL 字段定义不可用时才用 UI 下拉捕获兜底。
   - 之后走 `build_defect_fields()`（主工单取共有字段，profile 取系统环境等特有字段；提交前校验必填，
     缺值直接报字段名，**不用历史缺陷兜底**）→ `create_linked_defect()` 创建并关联 →
     `upload_task_attachment_api()` 直传本条证据 → `append_task_description_images()` 内嵌图片到描述。
   - 或直接用 `ones_submit_defects.py --profile <项目> --bug-report <清单> --work-order <工单URL>`
     批量提交。批量顺序固定为「单条创建 → 关联 → 附件核验 → 描述内嵌核验」，任一步失败即带 uuid 停止后续建单。
     默认必须内嵌截图；仅明确不需要时加 `--no-inline-evidence`。
   - **处理人规则（必读）**：UI 展示/交互类缺陷（字段显示、带出、界面交互、样式）加 `--handler frontend`；
     数据/逻辑/后端类默认 `--handler backend`。已建单要改处理人时用 `tasks/update` 改 `95jUV2Mb`。
   - **UI 弹窗仅作兜底**：工单抽屉 → 页签「关联内容」→「新建关联工作项」→ 类型搜索「缺陷」→
     填必填字段（来源项目、系统环境、功能模块、产品负责人、负责人/验证人、处理人、优先级）。
     **严重程度默认「一般」；负责人(field004)、验证人(Sg5vqjRr) 固定为当前 ONES 登录账号**
     （黑盒报告里的 P0~P4 只给测试人员自用，不作为 ONES 定级依据）。
   - 交互细节统一用 `ones_helpers.set_select_option / set_desc / upload_evidence / submit_defect`，
     弹窗/字段细节见 `references/ones-ui.md`。
   - 提交后断言弹窗关闭 + 关联内容数量 +1，并用 `list_related_tasks()` + `dedup_check()` 查重；
     发现同标题重复立即提示处理。
4. **回归后处理缺陷单**（以清单「回归验证」为准）：
   - 通过 / 产品口径不算缺陷 → 打开对应缺陷单 → 流转为「已关闭」。
   - 未通过 → 打开缺陷单 → 评论 @处理人（`data-ref-id`+`data-ref-name` 格式）写明「未修复 + 回归结果 + 证据」，
     并按需流转为「开发待处理」。
5. **主工单流转**：缺陷单全部关闭后，把主工单流转到目标状态（如「集成测试通过待验收」），路径见 `references/ones-ui.md`。
6. **汇报**：完成后向用户说明每个单子的处理结果与当前状态。

## 关键坑（最高频 3 条）

- 含中文的脚本必须写成 `.py` 文件（UTF-8）再执行，避免内联 heredoc 被 shell 转码乱码。
- 页面有多个 CKEditor：主工单描述 `editor1` **禁止操作**；只操作提缺陷弹窗 `editor2`（`[role=dialog]` 内含「选择关联关系」的那个）。
- 提交成功不能只看 toast：必须断言**弹窗关闭 + 关联内容数量 +1 + 标题出现**；同标题重复要告警去重。

> 其余 9 条（弹窗定位、字段同名、证据错配、上传确认弹窗、下拉 teleport、@ 提及格式、
> 状态流转、附件核验口径等）见 `references/ones-ui.md` 的「易踩坑清单」。

## 资源

- 脚本：`check_env.py`（自检）、`ones_bootstrap.py`（一键引导）、`ones_edge_server.py` / `edge_session_setup.py`
  （常驻浏览器/登录态）、`ones_submit_defects.py`（批量提缺陷 CLI）、`ones_project_setup.py`（新项目接入）、
  `ones_backfill_evidence.py`（附件+描述内嵌回填）、`ones_config.py`（配置）、`ones_helpers.py`（CDP + ONES 接口/弹窗封装）。
- 配置：`config/settings.yaml`（环境/浏览器）、`config/field-mapping.yaml`（字段映射与证据目录）。
- 文档：`references/ones-ui.md`（选择器速查、字段映射、编辑器/上传、状态流转、易踩坑清单）。
