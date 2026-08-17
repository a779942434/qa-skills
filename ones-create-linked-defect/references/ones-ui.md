# ONES 界面操作细节与字段映射

## 登录态（复用本机 Edge）

- 一键准备：`python scripts/edge_session_setup.py`（幂等；`--force` 强制重新复制）。
  自动把本机 Edge 的 `Local State`、`Default\Preferences`、`Default\Secure Preferences`、
  `Default\Network\Cookies`(+journal)、`Default\Network\Network Persistent State`
  复制到会话目录（默认 `~/.codex/tmp/edge-ones-session`，可在 `config/settings.yaml` 的
  `edge.session_dir` 修改）。
- 启动浏览器：`python scripts/ones_edge_server.py [工单URL]`，脚本会先确保会话目录，
  再用本机 Edge 本体启动（v20 Cookie 只能由 Edge 本体解密），CDP 端口默认 9334
  （`config/settings.yaml` 的 `cdp_port`）。
- 首次若跳 `accounts.feishu.cn` 登录页：以**实际弹出的授权账号/组织**为准（不要预设姓名或公司），点击"授权"回跳；不要重复扫码。
- 相关 Cookie 域名：`.feishu.cn`（session/session_list/sl_session）、`.ones.shuyilink.com`（ones-lt/ones-uid/ct）。

## 选择器速查（集中维护，SKILL.md 不再重复）

| 目标 | 选择器 / 操作 |
| --- | --- |
| 新建关联工作项弹窗 | `[role=dialog]` 且 innerText 含"选择关联关系" |
| 新建缺陷弹窗定位（稳定版） | 用「含`选择关联关系` + rect 可见」判定，勿用 `offsetParent`；见 `defect_dialog_index()` |
| 标题输入框 | `#summary`（默认有模板值 `【XX功能】-...`，需替换） |
| 工作项类型下拉 | innerText 为"请选择类型"的 `.ones-select`；点其 `input.ones-select-selection-search-input`，输入"缺陷"，点 `.ones-select-dropdown` 内含"缺陷"的 option |
| 表单字段定位（稳定版） | 限定弹窗子树内、叶子文本精确匹配，防同名 label 选错；见 `set_select_option()` |
| 下拉通用交互 | 聚焦搜索框 → 键入关键词 → 轮询 body 级下拉 option → JS click；见 `set_select_option()` |
| 弹窗描述编辑器 | `[role=dialog] .cke_wysiwyg_div[contenteditable=true]`（即 `CKEDITOR.instances.editor2`）；页面里 `editor1` 是主工单描述，禁止操作 |
| 评论输入框 / 发送按钮 | 弹窗底部 `.message-input-border`（点击后初始化 CKEditor）；发送按钮 `.message-input button` 文本"发送" |
| 文件上传 | 弹窗"文件"区按钮文本"上传文件"，隐藏 `input.upload-input`（`set_input_files` 直接可用） |
| 上传确认弹窗（稳定版） | 可见 dialog 含`上传文件`且**不含`选择关联关系`**；见 `upload_evidence()` |
| 提交成功断言 | 弹窗关闭 + 关联数 +1 + 标题查重；见 `submit_defect()` / `dedup_check()` |
| 缺陷单状态 | `.ones-select.field-input-12`；菜单项已预渲染，点状态框后 `el.click()` 目标项 |
| 主工单状态卡片 | `.ones-dropdown-trigger`（没有状态下拉字段，用真实鼠标点击打开流转菜单） |

### 缺陷字段 UUID 映射表（实测，跨项目基本稳定，换项目只改 config/field-mapping.yaml 的取值）

| 字段 UUID | 含义 | 取值示例（奥联） |
| --- | --- | --- |
| `field001` | 标题 | 【排产结果】… |
| `field002` | 描述 | 缺陷清单内容 |
| `5nUKjALP` | 来源项目 | 奥联电子-1期\|KH0091-01（`AzLXVpia`） |
| `Wq56Wyjw` | 产品负责人 | 张晴晴（`3cAXW7MC`） |
| `Jtnem8qs` | 来源客户 | KH0091奥联电子（`8qRUnWa2`） |
| `R3UqL3Vm` | 系统环境 | t-aolian-奥联集成环境（uuid 需 `capture_field_options()` 捕获后缓存） |
| `W9qkyVXr` | 功能模块（新） | 计划管理（`2s221obZ`） |
| `field012` | 优先级 | P2（`JYC3tQnb`） |
| `field004` | 负责人 | 当前 ONES 登录账号（`get_current_user()`，localStorage `user_id`） |
| `Sg5vqjRr` | 验证人 | 当前 ONES 登录账号（`get_current_user()`） |
| `95jUV2Mb` | 处理人 | 安杰（后端 `1vmJxxsw`）/ 王斌（前端 `JGwXEzXq`） |
| `field038` | 严重程度 | 默认「一般」；黑盒报告的 P0~P4 仅自用，不据此定级 |
| `DPNDusA2` | 测试责任人 | 廖柏全 |
| `NnkkhDGK` | 缺陷分类 | 按需 |

## 字段映射（具体取值见 config/field-mapping.yaml，换项目只改配置）

| 缺陷弹窗字段 | 取值来源 |
| --- | --- |
| 标题 | 缺陷清单缺陷标题，命名 `【功能名】-问题简述（状态）` |
| 描述 | 缺陷清单内容：环境/操作步骤/预期/实际/复现率/需求引用/严重程度 |
| 所属项目 | 自动：标准底座产品（DFS+SaaS） |
| 来源项目 | `field-mapping.source_project`：keyword 搜索 → name 选择 |
| 产品负责人 | 主工单产品负责人（搜索姓名） |
| 系统环境 | `field-mapping.system_env`：keyword 搜索 → name 选择 |
| 功能模块（新） | `field-mapping.function_modules`，按当前功能选 |
| 优先级 | `field-mapping.priority`（默认 P2，与主工单一致） |
| 负责人 / 验证人 | 当前 ONES 登录账号（`get_current_user()`） |
| 严重程度 | 默认「一般」，不读黑盒报告的 P0~P4 |
| 处理人 | 动态取自主工单：前端类→前端人员，其余→后端人员；`get_parent_handlers()` |

主工单字段可用接口核对：`get_task_info()`（ones_helpers）→
`GET /project/api/project/team/{team_uuid}/task/{task_uuid}/info`
（返回 owner=产品负责人、assign=负责人、desc/desc_rich=描述）。
用户搜索：`search_user()`（ones_helpers）→ `POST .../users/search` body `{"keyword":"姓名","limit":10}`，命中后取 uuid。

## API 直连提交缺陷（推荐，替代 UI 弹窗）

- 创建缺陷：`POST /project/api/project/team/{team}/tasks/add3`，
  body `{"tasks":[{"uuid":"<16位>","assign":"<创建者8位uuid>","summary":"标题",
  "parent_uuid":"","field_values":[{"field_uuid":"...","type":1,"value":"..."},...]}]}`。
- 关联主工单：`POST /project/api/project/team/{team}/task/{parent_uuid}/related_tasks`，
  body `{"task_uuids":["<新任务uuid>"],"task_link_type_uuid":"UUID0001",
  "link_desc_type":"link_out_desc"}`。
- 字段模板：从同工单已有缺陷 `POST .../tasks/info` 拿 `field_values` 复制，
  仅替换 `field001`(标题) 与 `field002`(描述)；严重程度默认「一般」，
  负责人/验证人默认当前登录账号（`build_defect_fields()` 已内置）。
- 处理人字段（缺陷表单）：`95jUV2Mb`；按规则取主工单前端/后端人员 uuid 后写入该字段。
- 全 API 构建：`ones_helpers.build_defect_fields()` 自动组装字段
  （主工单接口取来源项目/功能模块/产品负责人/优先级，同类型缺陷模板取系统环境等），
  仅需传入标题/描述/处理人；`create_linked_defect()` 创建+关联，秒级。
- 封装：`ones_helpers.get_parent_handlers()`（主工单前端/后端人员）、`build_defect_fields()`（字段构建）、`create_linked_defect()`（创建+关联）。

### 混合模式：字段选项 UUID 捕获（推荐，提速关键）

纯 API 直连最大的卡点是「系统环境」这类下拉字段需要**选项 UUID**，
而字段选项接口经常 404、UI 下拉 DOM 也不暴露 uuid。解法是**只探一次、之后全走 API**：

1. `ones_helpers.open_defect_form(page, team_uuid, task_uuid, title)` 打开新建缺陷弹窗（自动选"缺陷"类型）；
2. `ones_helpers.capture_field_options(page, "系统环境", "奥联", "t-aolian")` ——
   聚焦字段搜索框、键入关键词，从接口响应提取 `{text, uuid}`；
   **接口响应拿不到时改用 `ones_helpers.capture_field_options_fiber(page, "系统环境", "ousida")`**
   （从下拉虚拟列表 `List` fiber 的 `memoizedProps.data[].value` 取 uuid，显示名取可见 option 文本按序对齐）。
3. 把 uuid 写入 `config/field-mapping.yaml` 的 `option_uuids` 缓存（按项目）；
4. 之后创建全部走 `build_defect_fields()` + `create_linked_defect()`，每条秒级，不再碰弹窗。

同一项目同字段只需捕获一次；换客户项目只改配置。

**UI 提取方法（实测可用）**：DOM 的 option 属性不暴露 uuid，选项数据在虚拟列表
`List` fiber 的 `memoizedProps.data[]` 里（`data[].value`=选项 uuid、显示名在可见 option 文本）。
做法：`page.locator(".ones-form-item", has=page.locator("label:has-text('系统环境')"))`
定位字段 → 点其 `.ones-select` 打开下拉 → 读可见 option 文本（去重保序）+ List `data[].value` 对齐。
已封装为 `ones_helpers.capture_field_options_fiber()`。
已验证：奥联「系统环境」`t-aolian-奥联集成环境` = `SeMgos4c`（已写入 field-mapping）。

## 描述编辑器（CKEditor）

- 清空模板：点击编辑器 → Ctrl+A → Backspace → 输入内容。
- 粘贴证据截图：CDP `Browser.grantPermissions` 授予 `clipboardReadWrite` →
  `navigator.clipboard.write([new ClipboardItem({'image/png': file})])` →
  光标放编辑器末尾 → Ctrl+V。粘贴后等 6~8s 上传完成
  （未完成时是 15×15 占位 GIF，发送前确认 src 非 data:image/gif）。
- 删除多余图片：DOM `img.remove()`（连空容器）后执行 `CKEDITOR.instances.editor2.setData(getData())` 同步。
- 若用 `execCommand('insertHTML')` 整体注入内容，发送按钮可能保持禁用：末尾输入一个空格再 Backspace 触发 onChange 即可。

## 文件上传（导入 Excel / 证据文件）

- 弹窗"文件"区上传按钮文本"上传文件"；对应隐藏 `input.upload-input`，直接 `set_input_files(path)` 即可（会 dispatch change）。
- **上传后会弹出"上传文件"确认弹窗（含 文件名/文件描述 输入框），必须点"确定"才会真正挂到工作项**；
  判定条件：可见 `[role=dialog]` 且文本含`上传文件`且**不含`选择关联关系`**
  （否则会误点主弹窗"确定"，造成提前提交/重复建单，实测踩过）。
  上传成功以 `resource-info-name` 出现为准。
- 提交后必须回缺陷抽屉「文件」页签核对文件名出现，未挂载就补传（`ones_helpers.upload_evidence()` 已内置确认弹窗判定与核验）。

## 评论（@处理人 + 未修复说明）

- 评论框：弹窗底部 `.message-input-border`（点击后初始化 CKEditor，`.cke_wysiwyg_div[contenteditable=true]`）；发送按钮 `.message-input button` 文本"发送"。
- **提及格式（关键）**：富文本里必须是
  `<span class="ones-at-user-block" data-ref-id="<8位用户UUID>" data-ref-name="<姓名>" contenteditable="false">@姓名</span>`
  - 渲染组件用 `data-ref-id`+`data-ref-name` 显示；只写 `data-name` 会显示成"@"不带名字。
  - 用户 UUID：`search_user()`（ones_helpers）。
  - 通过 `document.execCommand('insertHTML')` 注入后发送；先输入文本再注入，末尾触发一次 onChange。
- 删除评论：悬停评论块 → "删除" → 确认弹窗"删除"。
- 评论接口（备用）：`send_comment()`（ones_helpers）→ `POST .../send_message` body `{"uuid":"<随机>","content_type":1,"text":"<rich html>"}`。

## 缺陷单状态流转

- 可流转状态接口：`get_transitions()`（ones_helpers）→ `GET .../transitions`（返回 `transitions[]`，含 uuid/name/end_status_uuid）。
- 缺陷单的"状态"是 `.ones-select.field-input-12`；直接点击可能不展开，
  但**流转菜单项（`.ones-menu-item`：已关闭/开发待处理/测试通过…）其实已预渲染在 DOM（隐藏）**——
  点状态输入框触发渲染后直接对目标项 `el.click()` 即可，
  成功后弹窗内"当前状态/缺陷-关闭时间"即时更新。
- 常用流转：回归通过 → 已关闭；未修复 → 开发待处理。

## 主工单（业务需求/任务）状态流转

- 需求/任务弹窗顶部有"当前状态"卡片（`.ones-dropdown-trigger`），**没有状态下拉字段**；
  用 Playwright 真实鼠标点击该卡片打开流转菜单
  （`.ones-menu-item` 列表，含重复副本，点任意可见副本即可）。
- 部分流转点击菜单项后会弹 **"执行步骤: <目标状态>"确认弹窗**（当前状态→目标状态，含 取消/确定），必须点"确定"才生效。
- 流转到"集成测试通过待验收"的路径（#200710 实测）：
  特性测试中 → 特性测试通过（流转后状态显示为"特性测试通过，待集成"）→ 集成测试通过待验收。
- 下一步可用流转以 `transitions` 接口为准；主工单当前状态可用 `info` 接口的 status_uuid 核对。

## 截图证据目录（按功能区分，勿混用）

- 目录索引维护在 `config/field-mapping.yaml` 的 `evidence_dirs`（功能名 → 目录）。
- 索引里是历史示例路径，实际以对应功能测试输出目录为准；找不到时先按功能名搜索（人员资质/排产数据等目录不同，勿混用）。
- 排产数据回传示例：
  `C:\Users\lenovo\.codex\visualizations\2026\08\05\019fcff3-0102-7cd3-94cf-df207be9e8cf\`
  （s1_initial、a3_after_import、q1_query_filter_done、BUG-03_修改导入目标不存在.xlsx 等）。
