---
name: ones-create-linked-defect
version: 2.0.0
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

## 概述

在 ONES 项目管理中，把本地 `bug-reports/` 缺陷清单的缺陷登记为工单的关联缺陷工作项，
并在回归后按结果处理：通过的关闭、未通过的评论 @处理人，最后把主工单流转到目标状态。
全程复用本机 Edge 的飞书/ONES 登录态，浏览器常驻可见；
涉及提交/状态变更的操作完成后给用户汇报。

本技能支持 Windows 与 macOS：浏览器路径、会话目录等由 `scripts/ones_config.py`
按平台自动探测，可用 `config/settings.yaml` 或环境变量覆盖；
客户项目/人员/优先级等字段统一维护在 `config/field-mapping.yaml`
（换项目只改配置，不动本文件与 references）。

**上游衔接**：本地缺陷清单通常由 `web-blackbox-testing` 技能产出（黑盒测试 / 回归验证），
清单命名 `bug-reports/YYYY-MM-DD_功能名_缺陷清单.md`，
字段含 环境/操作步骤/预期/实际/复现率/严重程度/需求引用。
本技能负责把清单录入 ONES，并按清单文末"回归验证"段的结果执行关闭或评论 @处理人。
两技能构成完整流程：黑盒测试 → 缺陷清单 → ONES 提缺陷 → 回归 → 关闭/评论 → 主工单流转。

## 前置

1. 运行 `python scripts/check_env.py` 自检环境：应无 FAIL（WARN 按提示处理）。
2. 常驻浏览器已登录 ONES（CDP 默认 9334）。未启动时执行
   `python scripts/ones_edge_server.py [工单URL]`——默认**后台静默启动**（headless，不弹窗），
   脚本会自动准备登录态（复制本机 Edge 登录态，v20 Cookie 只能由 Edge 本体解密）并启动浏览器。
   首次登录/飞书授权需可见窗口时加 `--visible` 参数，点击"授权"完成 SSO，后续即可静默运行。
3. 本地缺陷清单在 `bug-reports/YYYY-MM-DD_功能名_缺陷清单.md`
   （目录可在 `config/settings.yaml` 的 `bug_reports_dir` 调整；
   若由 `web-blackbox-testing` 技能产出，文件名与字段天然兼容），按工单标题中的功能名匹配；
   注意看文末"回归验证"段确定每个 BUG 是 通过/未通过/产品口径不算缺陷。
4. 证据文件（截图、导入 Excel）在对应功能的测试输出目录，目录索引见 `config/field-mapping.yaml` 的 `evidence_dirs`。

## 新项目接入（一次性）

换新客户项目时，先做一次字段/选项发现，写入 `config/field-mapping.yaml` 的 profile；之后日常提缺陷只跑 CLI 即可，不再反向工程。

1. 打开一次新建缺陷弹窗（`open_defect_form`），用 `capture_field_options_fiber()` 捕获「系统环境 R3UqL3Vm」的选项 uuid。
2. 用 `get_task_required_fields()` 从主工单取：来源项目、来源客户、功能模块、产品负责人、优先级、前端/后端人员 uuid。
3. 缺陷工作项类型 `issue_type_scope_uuid`：从同团队任一历史缺陷 `tasks/info` 读（如 `M33Rzztq`），写入 profile 的 `issue_type_scope_uuid`。
4. 严重程度是全局固定选项，提交默认「一般」；负责人/验证人 = 当前登录账号，运行期自动读取，均无需配置。
5. 把以上写入 `config/field-mapping.yaml` 的新 profile（参考 `ousida` 段）。

全局常量（严重程度 uuid、当前用户读取方式、scope 发现方法）见 `references/ones-ui.md`「全局常量表」。

## 工作流

1. **连接浏览器**：`scripts/ones_helpers.py` 的 `connect()` 连 CDP（默认 9334）并**复用已有 ONES 页面**；若跳转飞书授权页，点击"授权"完成 SSO。不要重复打开多个 ONES 工单页/弹窗，避免常驻浏览器标签页越积越多。
2. **打开工单**：访问用户给的工单 URL（任务 UUID 在 URL 尾部），读取标题与 ID（如 #200710 排产数据回传），据此定位本地缺陷清单文档。读字段只用 `get_task_required_fields()` 提取后续建缺陷的必填字段，**不要打印/搬运完整 `field_values` 或描述富文本**。
3. **新建关联缺陷**（若清单里有未登记的缺陷）：
   - **优先 API 直连提交（混合模式）**：
     1. 若字段选项 uuid 未缓存，先用 `open_defect_form()` + `capture_field_options_fiber()`
        探一次「系统环境」等下拉选项的 `{text, uuid}`，
        写入 `config/field-mapping.yaml` 的 `option_uuids`（同一项目只需一次）；
     2. 之后全部走 `build_defect_fields()`（主工单取来源项目/功能模块/产品负责人/优先级，
        同类型缺陷模板取系统环境等；处理人按 UI 前端→前端人员、其余→后端人员规则）
        + `create_linked_defect()` 创建并关联，或直接用 `ones_submit_defects.py --profile <项目> --bug-report <清单> --work-order <工单URL>` 批量提交。
   - UI 弹窗仅作兜底（弹窗/字段交互细节见 `references/ones-ui.md`；稳定版交互统一用 `ones_helpers.set_select_option / set_desc / upload_evidence / submit_defect`）：
   - 工单详情弹窗 → 页签"关联内容" → 按钮"新建关联工作项"。
   - 工作项类型下拉（占位"请选择类型"）→ 搜索"缺陷" → 点选项。
   - 必填字段与主工单一致（交互细节见 `references/ones-ui.md`，
     具体取值见 `config/field-mapping.yaml`）：
     来源项目、系统环境、功能模块（新）、产品负责人、负责人/验证人、处理人、优先级。
     **严重程度默认「一般」；负责人(field004)、验证人(Sg5vqjRr) 固定为当前 ONES 登录账号**
     （黑盒测试报告里的 P0~P4 严重程度只给测试人员自用，不作为 ONES 缺陷定级依据）。
   - 描述：CKEditor 清空模板 → 输入缺陷内容 → 粘贴证据截图。
   - 导入类缺陷上传复现 Excel：文件区 `input.upload-input` set_input_files → **点"上传文件"确认弹窗的"确定"**。
   - 提交前给用户确认，再点"确定"；提交后断言弹窗关闭 + 关联内容数量 +1，
     并用 `list_related_tasks()` + `dedup_check()` 查重，发现同标题重复立即提示处理。
4. **回归后处理缺陷单**（清单"回归验证"为准）：
   - 回归通过 / 产品口径不算缺陷 → 关联内容里打开对应缺陷单 → 流转为"已关闭"。
   - 回归未通过 → 打开缺陷单 → 评论 @处理人（`data-ref-id`+`data-ref-name` 格式）写明"未修复 + 回归结果 + 证据"，并按需流转为"开发待处理"。
5. **主工单流转**：缺陷单全部关闭后，把主工单流转到目标状态（如"集成测试通过待验收"），路径见 `references/ones-ui.md`。
6. **汇报**：完成后向用户说明每个单子的处理结果与当前状态。

## 关键坑

- 含中文的脚本必须写成 `.py` 文件（UTF-8）再执行，避免内联 Python heredoc 被 shell 转码乱码。
- 页面存在多个 CKEditor：主工单描述（editor1，禁止操作）与提缺陷弹窗描述（editor2，只操作 `[role=dialog]` 内含"选择关联关系"的那个）。
- 新建缺陷弹窗定位：页面有多个 `[role=dialog]`（工单抽屉也是），
  弹窗 fixed 定位 `offsetParent=null`；统一用
  「含`选择关联关系` + `getBoundingClientRect().width>0`」判定
  （`ones_helpers.defect_dialog_index()`）。
- 表单字段定位必须限定在新建缺陷弹窗子树内按叶子文本匹配：「产品负责人」「负责人」在工单抽屉与弹窗里同名，全文档搜会选错字段。
- 证据截图必须与所报功能匹配（人员资质/排产数据等目录不同，贴错会被用户退回）。
- 下拉选项异步加载且 teleport 到 body：聚焦搜索输入框输入关键词后
  轮询 body 级 `.ones-select-dropdown [class*=option]` 再点击；
  选项 uuid 从虚拟列表 `List` fiber 的 `memoizedProps.data[].value` 拿
  （`capture_field_options_fiber()`），DOM 不直接暴露 uuid。
- 评论 @ 提及：富文本用 `<span class="ones-at-user-block" data-ref-id="<8位UUID>" data-ref-name="<姓名>">@姓名</span>`；只写 `data-name` 会渲染成"@"不带名字。
- 上传文件后必点"上传文件"确认弹窗的"确定"，否则不挂载；
  该确认弹窗判定为「可见 dialog 含`上传文件`且**不含`选择关联关系`**」，
  否则会误点主弹窗"确定"造成提前提交/重复建单（实测踩过）。
- 提交成功不能只看 toast：断言新建缺陷弹窗关闭 + 工单关联内容数量 +1 + 标题出现；同标题重复时告警去重。
- 缺陷单状态流转：菜单项可能隐藏但已在 DOM（`.ones-menu-item`），点状态输入框触发渲染后 `el.click()` 目标项即可；主工单状态流转见 references。
- 选择器统一维护在 `references/ones-ui.md` 的"选择器速查"，改动只改一处。

## 资源

- `scripts/check_env.py`：使用前自检（依赖、配置、Edge/登录态、CDP、清单目录）。
- `scripts/ones_edge_server.py`：启动常驻 Edge（自动准备登录态 + 端口检测 + 健康检查 + 日志）。
- `scripts/edge_session_setup.py`：复制本机 Edge 登录态（幂等，`--force` 强制）。
- `scripts/ones_helpers.py`：CDP 连接 + ONES 接口封装
  （search_user / get_task_required_fields / get_current_user / get_transitions /
   send_comment / build_defect_fields / create_linked_defect）
  + 新建缺陷弹窗稳定交互
  （open_defect_form / set_select_option / set_desc / upload_evidence /
   submit_defect / capture_field_options_fiber / list_related_tasks / dedup_check）。
- `scripts/ones_submit_defects.py`：一键批量提缺陷 CLI（读清单 + profile 字段缓存 + 默认严重程度一般 + 负责人/验证人=登录账号 + 证据上传）。
- `scripts/bbt_ones_backfill_evidence.py`：给已建缺陷补传/回填证据文件。
- `scripts/ones_config.py`：配置加载（YAML → 环境变量 → 平台默认）。
- `config/settings.yaml`：环境/浏览器配置；`config/field-mapping.yaml`：字段映射与证据目录索引。
- `references/ones-ui.md`：选择器速查、字段映射、编辑器/上传/粘贴、缺陷单与主工单状态流转细节。
