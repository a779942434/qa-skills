# ONES 界面操作细节与字段映射

> 定位：ONES 的**选择器 / 字段 / 交互机制唯一权威**。工作流与纪律在 `SKILL.md`，此处不复述。

## 选择器速查（集中维护，改这里一处）

| 目标 | 选择器 / 操作 |
| --- | --- |
| 新建关联工作项弹窗 | `[role=dialog]` 且 innerText 含「选择关联关系」 |
| 弹窗定位（稳定版） | 「含`选择关联关系` + `getBoundingClientRect().width>0`」判定；见 `defect_dialog_index()`（工单抽屉也是 `[role=dialog]`，故不能用 `offsetParent`） |
| 标题输入框 | `#summary`（默认带模板值 `【XX功能】-…`，需替换） |
| 工作项类型下拉 | innerText 为「请选择类型」的 `.ones-select`；点其 `input.ones-select-selection-search-input`，输入「缺陷」后点 `.ones-select-dropdown` 内 option |
| 表单字段定位 | 限定弹窗子树内按**叶子文本**精确匹配；「产品负责人」「负责人」在工单抽屉与弹窗同名，全文档搜会选错；见 `set_select_option()` |
| 下拉通用交互 | 聚焦搜索框 → 键入关键词 → 轮询 body 级 `.ones-select-dropdown [class*=option]` → 点击；uuid 从虚拟列表 `List` fiber 的 `memoizedProps.data[].value` 取（`capture_field_options_fiber()`） |
| 弹窗描述编辑器 | `[role=dialog] .cke_wysiwyg_div[contenteditable=true]`（即 `CKEDITOR.instances.editor2`）；`editor1` 是主工单描述，**禁止操作** |
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

主工单字段核对：`get_task_info()` → `GET /project/api/project/team/{team}/task/{task}/info`（返回 owner / assign / desc）。
用户搜索：`search_user()` → `POST .../users/search`，body `{"keyword":"姓名","limit":10}`，命中取 uuid。

## API 直连提交缺陷（主路径，替代 UI 弹窗）

- **创建**：`POST .../tasks/add3`，body `{"tasks":[{"uuid":"<16位>","assign":"<创建者8位uuid>","summary":"标题","parent_uuid":"","field_values":[{"field_uuid":"...","type":1,"value":"..."}]}]}`。
- **关联主工单**：`POST .../task/{parent_uuid}/related_tasks`，body `{"task_uuids":["<新task_uuid>"],"task_link_type_uuid":"UUID0001","link_desc_type":"link_out_desc"}`。
- **字段来源**：主工单共有字段 + profile 中的缺陷特有字段；`sample-defect` 仅为显式兜底，
  **不允许默认拿历史缺陷复制后直接提交**。`build_defect_fields()` 已内置严重程度默认与负责人/验证人默认。
- **全 API 构建**：`get_issue_type_scope()` + `get_issue_type_fields()` 解析 scope 与字段定义；
  `build_defect_fields()` 用主工单 + profile/`--system-env` 组装并在提交前校验必填；仅需传标题/描述/处理人；
  `create_linked_defect()` 创建+关联，秒级。
- **附件直传**：`upload_task_attachment_api()` 用 `ref_id=<新建 task_uuid>` 调 `POST .../res/attachments/upload`
  取 `resource_uuid/token/upload_url`，再以 multipart `token + file` 上传；无需打开详情页。
- **描述内嵌截图**：附件成功后调 `append_task_description_images(page, team, task_uuid, image_files)`
  ——走真实 CKEditor 图像按钮上传并保存，随后重读 `field016/desc_rich` 校验图片节点数；按节点数幂等。
  `ones_submit_defects.py` 默认自动执行，`--no-inline-evidence` 显式关闭。
- **批量顺序**：逐条执行「创建 → 关联 → 直传并核验该条附件 → 内嵌图片并回读」，任一步失败即带 uuid 停止。
- UI 与 API 的关系：页面「新增关联工作项」最终也是创建 + 关联，只是多一层弹窗渲染/字段联动；直连少一层等待，故为首选。

## 描述编辑器（CKEditor）

- 缺陷详情补嵌图片时**不要点描述中心**（常命中已有图片并打开预览），应点首个非图片正文段落；若已打开预览先 Escape。
- ONES 特殊点：保存后 `field016` 可能仍保留 `data:image/gif` 占位 src，查看态靠 `data-uuid`/`data-ref-id` 解析真实图片。
  **验证以查看态 `.richtext-editor-viewer img` 数量 + `complete && naturalWidth > 0` 为准**，不要只看保存后 HTML 的 src。
- 删除多余图片：DOM `img.remove()`（连空容器）后执行 `CKEDITOR.instances.editor2.setData(getData())` 同步。
- 用 `execCommand('insertHTML')` 整体注入后发送按钮可能保持禁用：末尾输入一个空格再 Backspace 触发 onChange。

## 文件上传（导入 Excel / 证据）

- 弹窗「文件」区用隐藏 `input.upload-input` 直接 `set_input_files`（会 dispatch change）。
- **上传后会弹「上传文件」确认弹窗（含文件名/文件描述），必须点「确定」才真正挂到工作项**。
  判定：可见 `[role=dialog]` 且含「上传文件」且**不含**「选择关联关系」——否则会误点主弹窗「确定」造成提前提交/重复建单（实测踩过）。
  上传成功以 `resource-info-name` 出现为准。
- 提交后回详情「文件」页签补传时，用接口而非固定 sleep 判成功：`open_task_file_tab()` 等
  `GET .../task/{task_uuid}/attachments?since=0` 返回；点上传确认后 `wait_new_attachments()` 轮询，
  直到期望文件名以**新 attachment uuid** 出现。虚拟列表未渲染或控件晚出现都不会误判失败。

## 评论（@处理人 + 未修复说明）

- 评论框：弹窗底部 `.message-input-border`（点击后初始化 CKEditor，`.cke_wysiwyg_div[contenteditable=true]`）；发送按钮 `.message-input button`。
- **提及格式（关键）**：必须是
  `<span class="ones-at-user-block" data-ref-id="<8位用户UUID>" data-ref-name="<姓名>" contenteditable="false">@姓名</span>`
  ——只写 `data-name` 会渲染成「@」不带名字。用户 UUID 用 `search_user()`。
  先输入文本，再用 `document.execCommand('insertHTML')` 注入，末尾触发一次 onChange。
- 删除评论：悬停评论块 →「删除」→ 确认弹窗「删除」。
- 备用接口：`send_comment()` → `POST .../send_message`，body `{"uuid":"<随机>","content_type":1,"text":"<rich html>"}`。

## 状态流转

**缺陷单**：可流转状态用 `get_transitions()` → `GET .../transitions`（含 uuid/name/end_status_uuid）。
状态是 `.ones-select.field-input-12`，直接点击可能不展开，但**流转菜单项（`.ones-menu-item`）已预渲染在 DOM（隐藏）**——
点状态输入框触发渲染后直接对目标项 `el.click()` 即可，成功后弹窗内「当前状态/关闭时间」即时更新。常用：回归通过→已关闭；未修复→开发待处理。

**主工单**：顶部「当前状态」卡片（`.ones-dropdown-trigger`）**没有状态下拉字段**，用 Playwright 真实鼠标点击打开流转菜单
（`.ones-menu-item` 列表含重复副本，点任意可见副本）。部分流转会弹「执行步骤: <目标状态>」确认弹窗，**必须点「确定」**才生效。
实测路径（#200710）：特性测试中 → 特性测试通过（显示为「特性测试通过，待集成」）→ 集成测试通过待验收。
下一步可用流转以 `transitions` 接口为准，当前状态可用 `info` 的 status_uuid 核对。

## 截图证据目录（按功能区分，勿混用）

- 目录索引在 `config/field-mapping.yaml` 的 `evidence_dirs`（功能名 → 目录）；索引里是历史示例路径，
  实际以对应功能测试输出目录为准，找不到先按功能名搜索（人员资质/排产数据等目录不同，**勿混用**）。

## 易踩坑清单（其余 9 条）

1. 含中文的脚本写成 `.py` 文件（UTF-8）再执行，别用内联 heredoc。
2. 主工单描述 `editor1` 禁止操作；只动提缺陷弹窗的 `editor2`。
3. 补嵌图片点非图片段落，不点描述中心（会打开预览）。
4. 表单字段必须限定弹窗子树 + 叶子文本匹配（同名 label 会选错）。
5. 证据截图必须与所报功能匹配，贴错会被用户退回。
6. 下拉选项 teleport 到 body，必须在 body 级 popper 内轮询，别在弹窗内找。
7. 上传确认弹窗的判定必须排除主弹窗，否则提前提交/重复建单。
8. 评论 @ 必须带 `data-ref-id` + `data-ref-name`。
9. 状态流转项虽隐藏但已预渲染，点状态框后直接 `el.click()`。
