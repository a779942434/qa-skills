# ONES 界面操作细节与字段映射

> 定位：ONES 的**选择器 / 字段 / 交互机制唯一权威**。工作流与纪律在 `SKILL.md`，此处不复述。

## 选择器速查（集中维护，改这里一处）

| 目标 | 选择器 / 操作 |
| --- | --- |
| 新建关联工作项弹窗 | `[role=dialog]` 且 innerText 含「选择关联关系」 |
| 弹窗定位（稳定版） | 含「选择关联关系」且 `width>0`；见 `defect_dialog_index()`（工单抽屉也是 dialog，不能用 `offsetParent`） |
| 标题输入框 | `#summary`（默认带模板值 `【XX功能】-…`，需替换） |
| 工作项类型下拉 | innerText 为「请选择类型」的 `.ones-select`；点其 `input.ones-select-selection-search-input`，输入「缺陷」后点 `.ones-select-dropdown` 内 option |
| 表单字段定位 | 限定弹窗子树内按**叶子文本**精确匹配；「产品负责人」「负责人」在工单抽屉与弹窗同名，全文档搜会选错；见 `set_select_option()` |
| 下拉通用交互 | 聚焦搜索框 → 键入关键词 → 轮询 body 级 `.ones-select-dropdown [class*=option]` → 点击；uuid 从虚拟列表 `List` fiber 的 `memoizedProps.data[].value` 取（`capture_field_options_fiber()`） |
| 弹窗描述编辑器 | `[role=dialog] .cke_wysiwyg_div[contenteditable=true]`（即 `CKEDITOR.instances.editor2`）；主工单详情 `editor1` 是主描述，**禁止操作**；缺陷详情 `editor1` 才是缺陷描述 |
| 评论输入框 / 发送 | 弹窗底部 `.message-input-border`（点击后初始化 CKEditor）；发送按钮 `.message-input button` 文本「发送」 |
| 文件上传 | 「文件」区按钮文本「上传文件」；隐藏 `input.upload-input` 可直接 `set_input_files` |
| 上传确认弹窗 | 可见 dialog 含「上传文件」且**不含**「选择关联关系」；见 `upload_evidence()` |
| 提交成功断言 | 弹窗关闭 + 关联数 +1 + 标题出现；见 `submit_defect()` / `dedup_check()` |
| 缺陷单状态 | `.ones-select.field-input-12`；菜单项已预渲染（`.ones-menu-item`），点状态框触发渲染后对目标项 `el.click()` |
| 主工单状态卡片 | `.ones-dropdown-trigger`（**没有状态下拉字段**），用真实鼠标点击打开流转菜单 |

## 全局常量表（不随项目变，勿每次重新发现）

| 项 | 值 / 获取方式 |
| --- | --- |
| 严重程度 option uuid | 致命 `Dgk6PHkS`／严重 `QYe31Dn9`／一般 `XxwMNPQp`／提示 `A3HEmFsu`／建议 `RDtgWTEi`／保留 `MnAwAecn`（`ones_helpers.SEVERITY`） |
| 提交默认严重程度 | 一般（`DEFAULT_SEVERITY`）；黑盒报告的 P0~P4 仅内部自用 |
| 当前登录账号 | `localStorage.user_id` / `user_name`（`get_current_user()`），负责人/验证人用它 |
| 缺陷类型 scope | `POST .../items/graphql?t=issue-type-scopes` 查 `issueTypeScopes`，按 `project.uuid + issueType.uuid` 直接得到；无需历史缺陷 |
| 工作项类型「缺陷」 | type uuid `6FUpniBf`（`issue_type_uuid`，区别于 `issue_type_scope_uuid`） |

## 缺陷字段 UUID 映射表（跨项目基本稳定，换项目只改 `config/field-mapping.yaml` 取值）

| 字段 UUID | 含义 | 取值 |
| --- | --- | --- |
| `field001` / `field002` | 标题 / 描述 | 缺陷清单内容 |
| `5nUKjALP` / `Jtnem8qs` | 来源项目 / 来源客户 | profile 中的选项 uuid |
| `Wq56Wyjw` | 产品负责人 | 主工单产品负责人 |
| `R3UqL3Vm` | 系统环境 | 需 `capture_field_options_fiber()` 捕获后缓存 |
| `W9qkyVXr` | 功能模块（新） | profile 按当前功能选 |
| `field012` | 优先级 | 默认 P2（`JYC3tQnb`），与主工单一致 |
| `field004` / `Sg5vqjRr` | 负责人 / 验证人 | 当前 ONES 登录账号（`get_current_user()`） |
| `95jUV2Mb` | 处理人 | 前端类→前端人员，其余→后端人员（`get_parent_handlers()`） |
| `field038` | 严重程度 | 默认「一般」 |
| `DPNDusA2` / `NnkkhDGK` | 测试责任人 / 缺陷分类 | 按需 |

字段核对 `get_task_info()`；用户搜索 `search_user()`（`POST .../users/search`，取 uuid）。

## API 直连提交缺陷（主路径，替代 UI 弹窗）

- **创建**：`POST .../tasks/add3`，body `{"tasks":[{"uuid":"<16位>","assign":"<创建者8位uuid>","summary":"标题","parent_uuid":"","field_values":[{"field_uuid":"...","type":1,"value":"..."}]}]}`。
- **关联主工单**：`POST .../task/{parent_uuid}/related_tasks`，body `{"task_uuids":["<新task_uuid>"],"task_link_type_uuid":"UUID0001","link_desc_type":"link_out_desc"}`。
- **字段来源**：主工单共有字段 + profile 中的缺陷特有字段；`sample-defect` 仅为显式兜底，
  **不允许默认拿历史缺陷复制后直接提交**。`build_defect_fields()` 已内置严重程度默认与负责人/验证人默认。
- **字段构建**：`get_issue_type_scope/fields()` 解析 scope 与字段；`build_defect_fields()` 组装并校验必填。
- **附件直传**：`upload_task_attachment_api()` 调 `POST .../res/attachments/upload`，取 `resource_uuid/token/upload_url` 后 multipart 上传；无需打开详情页。
- **两阶段（2026-11-13 固化）**：Phase A 只建单/关联/附件并落账本，先返回单号；Phase B 再补描述图。
  `ones_submit_defects.py --mode fast` 为默认；`--mode full` 一次跑完；`--repair-images --ledger <账本>`
  单独补图；`--verify-only` 只读校验。Phase B 失败只记 `failed`，不阻塞 Phase A 单号。
- **描述内嵌截图（API 化）**：附件成功后 `ensure_task_attachment()` 取 `resource_uuid`，再调
  `GET .../res/attachment/{resource_uuid}?op=imageMogr2%2Fauto-orient` 取带 token 的 `url`，把该 URL
  写进 `<img src>` 后保存。**不要用 CKEditor 图片按钮**（会生成 `data:image/gif` 占位）。
  成功判据：占位数 0 + 浏览器 `naturalWidth>0` + 期望文件名齐全；只数 `<img>` 节点会误判。
- **账本幂等**：默认 `<缺陷清单目录>/ones-submission-ledger.json`，按 `bug_key + task_uuid` 恢复；
  已有 `task_uuid` 只补关联/附件/图片，禁止重复建单。默认 `--mode fast` 返回时图片状态为 `inline_pending`，
  可稍后 `--repair-images`。

## 描述编辑器（CKEditor）

- **按页面认编辑器**：主工单详情 `editor1` 是主描述，禁止操作；缺陷详情只有 `editor1` 是缺陷描述。
  补图统一用 `append_task_description_images_api()`：新开任务页 + `assert_task_context()` + `editor1.setData`。
- 不要复用当前标签页、不要只改 URL hash（SPA 不切换任务）；每个任务 `open_task_detail_page()` 后操作，用完关闭。
- ONES 特殊点：保存后 `field016` 可能仍保留 `data:image/gif` 占位 src，查看态靠 `data-uuid`/`data-ref-id` 解析真实图片。
  **验证以查看态 `.richtext-editor-viewer img` 数量 + `complete && naturalWidth > 0` + 占位数 0 为准**，
  不要只看保存后 HTML 的 src 或 `<img>` 节点数。
- 用 `execCommand('insertHTML')` 整体注入后发送按钮可能保持禁用：末尾输入一个空格再 Backspace 触发 onChange。

## 文件上传（导入 Excel / 证据）

- 弹窗「文件」区隐藏 `input.upload-input` 直接 `set_input_files`。
- **上传后弹「上传文件」确认框，必须点「确定」**；判定须含「上传文件」且不含「选择关联关系」，否则会误点主弹窗造成重复建单。成功以 `resource-info-name` 出现为准。
- 回详情补传用接口轮询 `GET .../attachments?since=0`，直到期望文件名以新 uuid 出现，不依赖固定 sleep。

## 评论（@处理人 + 未修复说明）

- 评论框：弹窗底部 `.message-input-border`（点击后初始化 CKEditor，`.cke_wysiwyg_div[contenteditable=true]`）；发送按钮 `.message-input button`。
- **提及格式（关键）**：必须是
  `<span class="ones-at-user-block" data-ref-id="<8位用户UUID>" data-ref-name="<姓名>" contenteditable="false">@姓名</span>`
  ——只写 `data-name` 会渲染成「@」不带名字。用户 UUID 用 `search_user()`。
  先输入文本，再用 `document.execCommand('insertHTML')` 注入，末尾触发一次 onChange。

## 状态流转

**缺陷单**：可流转状态用 `get_transitions()` → `GET .../transitions`（含 uuid/name/end_status_uuid）。
状态是 `.ones-select.field-input-12`，直接点击可能不展开，但**流转菜单项（`.ones-menu-item`）已预渲染在 DOM（隐藏）**——
点状态输入框触发渲染后直接对目标项 `el.click()` 即可，成功后弹窗内「当前状态/关闭时间」即时更新。常用：回归通过→已关闭；未修复→开发待处理。

**主工单**：顶部「当前状态」卡片（`.ones-dropdown-trigger`）无状态下拉字段，用真实鼠标点击打开流转菜单；
部分流转弹「执行步骤」确认，**必须点确定**。下一步以 `transitions` 为准，当前状态用 `info.status_uuid` 核对。

## 易踩坑清单（其余 9 条）

1. 含中文脚本写成 `.py`（UTF-8）再执行，别用内联 heredoc。
2. 主工单描述 `editor1` 禁止操作；提缺陷弹窗用 `editor2`；缺陷详情补图用 `editor1`（必须新开页+单号断言）。
4. 表单字段必须限定弹窗子树 + 叶子文本匹配（同名 label 会选错）。
5. 证据截图必须与所报功能匹配。
6. 下拉选项 teleport 到 body，去 body 级 popper 轮询。
7. 上传确认弹窗的判定必须排除主弹窗，否则提前提交/重复建单。
8. 评论 @ 必须带 `data-ref-id` + `data-ref-name`。
9. 状态流转项虽隐藏但已预渲染，点状态框后直接 `el.click()`。

### 任务详情路由（2026-10-16 固化）

- 必须带 `project/component/view` 上下文；简版 `#/team/<team>/task/<uuid>` 只渲染任务列表页。
- 段与项目绑定、不可写死：统一 `open_task_detail_page()`（新页 + 完整 URL + 单号断言），
  失败带 URL 报错；受影响入口 `append_task_description_images_api()`、`ones_backfill_evidence.py`。

### 描述净化（只应留在本地的信息不外发）

- `ones_submit_defects.py` 提交前默认调 `sanitize_text()`：过滤本地绝对路径（`/Users`、`/home`、`C:\`…）、
  `账号 xxx`、`密码/token xxx`、「（租户 xx，账号 yy）」环境标注；命中明细打印在提交日志。
- 扩展规则：`profile.redact.patterns: [[正则, 替换], ...]` 或 `--redact-pattern '正则==替换'`（可重复）；`--no-redact` 关闭。
- 客户名/实例 URL/本机路径只放 `config/field-mapping.local.yaml` 与本地产物，公共文件不放。
