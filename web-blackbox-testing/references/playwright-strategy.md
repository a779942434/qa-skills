# Playwright 使用策略

> 本文件定位（去重原则，2026-09-03）：本 reference 是「机制/实现细节」的**唯一权威**；判定与底线类原则一律在 SKILL.md 的「必守清单」，本文件不复述，只给怎么用 / 场景钩子 / 示例。新增规则（组件库防误读、级联侦测先行）唯一权威即本文件，SKILL 仅一行指针，避免两处全文复述。

## 组件库防误读与多信号判定（2026-09-03 增补）

踩坑：必填校验提示常以顶部 toast（.el-message）弹出而非表单内联错误；只读 .el-form-item__error 会把「校验已生效」误判为「静默无提示」（生成方式必填拦截误报）。级联类交互同理，「父节点只展开、叶节点才选中」，只点父节点会误判「无法回填」。

读全信号层：优先用 bbt_helpers.read_feedback(page)（toast + 内联错误 + 可见 dialog 一起读），或用 api_wait.confirm_action（返回已含 toasts 与 form_errors）。信号源四类：

1. 新业务接口响应（ApiWatcher.wait_new / judge_action 的 new_responses）
2. 顶部 toast（.el-message / .el-notification / .el-message-box）
3. 表单内联校验错误（.el-form-item__error）
4. 数据状态变化（操作前后 data_diff）

判定标准（防误报核心）：

| 场景 | 判定 |
| --- | --- |
| 有新响应 且 无校验类提示 | processed=True, ok=True, reason=success |
| 有校验类提示（toast/内联，如「必须/请选择/大于0/不超过」） | processed=True, ok=False, reason=blocked——记「已处理·被拦截」，不是失败 |
| 无新响应、无任何提示、数据未变 | processed=False, reason=silent——才需人工核（真·无反馈） |
| 有 HTTP>＝400 新响应 | ok=False, reason=http_error |

用 bbt_helpers.judge_action(page, action, api_watcher=None, data_diff=None) 拿到这四个信号；api_wait.confirm_action 同样返回 reason/processed。不要把「有提示的拦截」写成缺陷。

点击前先判禁用：用 bbt_helpers.click_or_observe(page, 按钮文本)——按钮 disabled 时返回 (disabled, ...) 记状态观察，避免对 disabled 按钮 click 超时中断整段（勾选态被清、按钮回落 disabled 的场景）。

## 级联与树选择（侦测先行）（2026-09-03 增补）

el-cascader 两级结构（如 来源地：事业部 → 车间）需要「先展开父节点 → 点叶节点」两步；且必须在知道结构确为两级父→子时才走这一步，否则跳过。用 bbt_helpers.detect_cascade(page, trigger_sel) 先侦测：

- 示例：diag = detect_cascade(page, "input[placeholder*='来源地'] 或其他触发选择器")
- diag 结构：{kind:'el-cascader-2level'|'single-list'|'unknown', hasParentChild:bool, parents:[...], leaves:[...]}
- 若 diag.get("hasParentChild") 为真：ok, val = select_cascade(page, trigger_sel, leaf_part="车间1", diag=diag)；返回 (ok, value) 已回填 / (fail, reason)
- 若为假（非两级级联 / 不是级联）：跳过，不盲点（记结构观察或待人工）

要点：

- select_cascade 内部会先调 detect_cascade（或复用传入 diag），hasParentChild=False 时返回 (skip, reason) 不执行任何点击。
- 选择成功后必须断言输入框回填非空（(ok, value)），否则记 fail（回填空 = 需人工复核）。
- 若页面下拉不是 el-cascader 两级而是一次性列表/其它组件，直接走「标准用户操作」，不要套用级联步骤。


## 执行环境与沙箱（网络受限）

- 目标站点访问默认非沙箱：沙箱 DNS 受限（`Could not resolve host` / `Operation not permitted`）时，浏览器自动化与网络命令直接用 require_escalated，不先沙箱试错再升级。
- 浏览器定式：被测 MES 站点统一用独立 Chromium + Keycloak 登录（`bbt_osd_common.login_ousida`）；ONES 常驻 Edge（CDP 9334）只用于 ONES 操作，不混用、不反复试启动方式。
- 登录/导航零重复：新页面直接 `scripts/recon-generic/recon_page.py --url <URL>`（内置登录+导航+侦察）；页面结构固化到 references 后直接引用，不再逐个脚本重写。
- 开工顺序：读需求 → 读 skill/reference → 起浏览器登录一次 → 侦察固化 → 数据勘察 → 跑用例 → 记录产生数据（清理遵循必守 #8，测试环境保留造数为主）。

1. 浏览器自动化统一用本机 Python Playwright 脚本（UTF-8，写成 `.py` 文件执行）
   或浏览器控制技能；先完成登录、菜单定位和页面结构侦察（`recon_page.py`），
   再对稳定流程固化脚本。
   **同一被测页面不重复多开**：连接常驻浏览器时先 `find_page(ctx, url_contains=...)`
   检查目标页面是否已存在，存在就复用同一个页面继续测试；
   只有确实需要干净上下文时才新建页面。
   测试收尾清理本轮产生的多余标签页，避免常驻浏览器标签页越积越多导致 CDP 连接超时。
2. 减少等待：用 `bbt_helpers.wait_visible()` 条件等待（元素可见/表格行变化），
   不使用长时间固定 sleep；仅首次侦察允许固定等待。
3. 表格断言用 `bbt_helpers.table_columns() / read_table_rows()` 按列头取列，
   不要硬编码 `td` 索引（列顺序变化会导致误判）。
4. 截图用 `bbt_helpers.snap()` 语义化命名（`功能_用例_步骤_时间.png`）；
   只在首页状态、关键通过节点、缺陷现场、导出预览保留证据；
   缺陷现场截图必须保留，供 ONES 提缺陷使用。
5. 对慢页面先缩小筛选范围，使用测试单号、近七天、单个供应商/产品定位。
6. 遇到偶现失败，最多复现 2 次（用 `bbt_helpers.retry()` 包裹）；仍不稳定则标为偶发现象或环境观察，不再重试。
7. 校验类用例一次只开一个弹窗、一个用例收尾干净（Escape/取消）后再开下一个，
   避免弹窗与下拉残留互相遮挡。

## 防循环与重试上限（关键约定）

以下约定用于避免 AI 在实际执行中陷入“侦察 → 试操作 → 失败 → 再侦察”的反复循环：

1. **同一操作连续失败最多复现 2 次**。仍不稳定就标记「环境观察 / 偶发现象」并换下一步，不无限重试、不反复 dump 同一页面。
2. **遇到全新页面 / 未知结构，先做一次完整侦察并固化**：把页面 URL、入口、必填字段、选择器（如 form-item 索引、表头关键字）写进对应 references 或知识库，后续直接引用；不要在循环里反复打印整页文本/全部按钮/全部行。
3. **时序问题优先条件等待**：用 `wait_visible / wait_text / wait_button / wait_until`，不用固定 sleep；条件等待超时算一次失败，按重试上限处理。
4. **弹窗 / 下拉一次只开一个、收尾干净**（Escape / 取消）再开下一个，避免残留互相遮挡导致反复失败。
5. **不稳定的操作统一用 `bbt_helpers.retry(fn, attempts=2)` 包裹**，返回 `(ok, result_or_error)` 交给上层判断，避免在脚本里写裸循环。

## 执行组织（每功能一个脚本，一次登录）

- **所有测试脚本共用一次登录**：复用同一浏览器会话/页面（登录/导航固化在 `bbt_osd_common.login_ousida`），不要每个脚本新起浏览器 + 重新登录。
- 一般模式：一个功能 = 一个执行脚本，登录一次，按「筛选 → 新增 → 校验 → 编辑 → 复制 → 删除 → 导入 → 清理」的大致顺序跑完该功能用例。
- **注意：这只是大致流程，不是固定配方。** 每个环境、每个功能的页面结构 / 数据 / 前置条件都可能不同，用例顺序和造数步骤要按实际侦察结果调整，不要机械照搬固定顺序。
- 简单主数据默认合并同类校验（必填 / 长度 / 唯一性在同一个新增弹窗里一次验完），不拆成过多独立用例。
- 脚本内一次登录跑完；执行结束产出报告 / 缺陷清单。数据处理遵循必守 #8：保留造数为主，确需清理时才清理并留痕。

## 接口观测等待（核心约定，2026-08-21 增补）

> 原则见 SKILL「Playwright 使用策略」与参照 api_wait；本段给四步实现与判定细节。

页面数据 = 接口返回后渲染。**不要在操作后固定 sleep 或立即读 DOM 下结论**，
要观测页面实际发出的接口，等"操作触发的业务接口返回"后再断言页面数据。
业务不同接口路径不同，不要预先固化具体接口；用"基线对比"动态识别新请求。

通用四步（工具见 `scripts/api_wait.py`）：

```python
from api_wait import ApiWatcher

watcher = ApiWatcher(page)      # 覆盖所有 frame 的 response 监听
base = watcher.snapshot()       # 1. 操作前记录响应基线

click_action(...)               # 2. 触发操作（切页签/提交/刷卡/刷新）

new = watcher.wait_new(base, timeout=15)   # 3. 等基线之后出现新响应
if not new:
    # 超时：操作可能未触发请求（按钮没点中/请求被缓存），按失败处理，不硬读页面
    raise/标记
page.wait_for_timeout(500)      # 4. 少量渲染余量后再读 DOM
assert_page_state(...)
```

要点：
- **基线必须操作前取**（`snapshot()`），否则会把旧请求误当新结果（页签切换"读到旧数据/0 条"的根因就是没等新列表接口返回）。
- 不确定业务接口路径时**不传 keyword**，等任意新响应即可；能判断前缀时（如列表含 `/plan/`、提交含 `/switch/`）可传 `keyword` 缩小范围。
- 状态码默认只认 <400；个别接口 4xx 是业务预期（如重复提交）时用 `accept_status` 显式放行。
- IPC 弹窗/页签切换场景强烈建议使用：切页签 → 等新列表接口 → 再读卡片；打开弹窗 → 等新查询接口 → 再 dump 结构；刷卡提交 → 等提交接口 → 再断言 toast/状态。
- 接口等待代替固定 sleep 后，页签切换等待可从 8~10s 降到 1~3s；失败判定也更准（无新响应=操作未生效，而不是"页面没刷新"）。


## 失败分级（2026-08-21 增补）

> 底线见 SKILL 必守 #7 与「失败分级」；本段给分层判定细节。**补充：校验被拦截（有提示）≠失败，是已处理·业务拦截**（见上文「组件库防误读与多信号判定」）。

- **环境失败**：接口 502 / 超时 / 网络错误 / 页面空白 → 标记「环境观察」，立即跳过该步骤，**不重试**（重试只会放大无效消耗）。
- **业务失败**：页面出现明确报错提示（如「切换成功」未出现、按钮无响应且无新接口）→ 才算失败，重试最多 1 次；仍失败按缺陷记录。
- 判定依据优先用 `api_wait.confirm_action` 的返回（新接口 + 错误 + toast），不靠肉眼猜。

## 一次会话与页面持有（2026-08-21 增补）

> 原则见 SKILL 必守 #5；本段给会话/页面持有机制。

- 一个测试任务 = 一个长脚本 + 一个浏览器会话：启动（`session_helpers.launch_session`）→ 登录/导航一次 → 跑完全部用例 → `close_session` 清理。
- 一个会话**只有一个持有者**操作页面；若用 CDP 常驻，启动脚本打开页面后让出，操作脚本只连接不并发操作同一页面（多 playwright 客户端并发会导致事件/状态错乱）。
- 优先 `find_reuse_page` 复用已有页面，不重复多开标签页。

## 侦察→固化→引用纪律（2026-08-21 增补）

> 底线见 SKILL 必守 #4；本段给执行要求。

- 同一页面结构侦察最多 2 次；第 2 次前必须把稳定交互方式（选择器、事件、遮挡处理）写进 references。
- 遇到新交互（自定义弹窗、刷卡层、iframe 多实例）→ 立即补 references 再继续，禁止反复 dump 同一页面。

## 报告与数据留痕（2026-08-21 增补）

> 数据处理遵循 SKILL 必守 #8（测试环境保留造数，按需清理）；本段给报告/清理留痕做法。

- 用例执行结果直接喂 `report_gen.gen_report / gen_bug` 生成报告/缺陷清单骨架，避免手工整理消耗 token。
- 测试改数据后，记录本轮产生数据（单据编号 / 扣减量）；确需清理时用 `data_cleanup.compare_state` 对比基线并 `write_cleanup_note` 留痕「已保留 / 已恢复」。测试环境保留造数为主，不作强制清理。

## Playwright MCP 真窗口模式（Chrome 扩展，2026-09-04 增补）

> 定位：与「Python Playwright 脚本」并列的第二种连接方式，只解决「复用真窗口已登录态」这一场景；
> 判定/纪律类原则仍以 SKILL.md 必守清单为准，此处只写安装、配置与使用钩子。

适用场景：被测系统在**日常 Chrome 默认 profile 里已登录**（如 t-dafu / t-ousida），希望 AI 直接操控真实窗口、
复用登录态做黑盒，最贴近真实用户操作。

- 本体：微软官方 `@playwright/mcp`，Codex 侧配置已写入 `~/.codex/config.toml`：

  ```toml
  [mcp_servers.playwright]
  type = "stdio"
  command = "npx"
  args = ["-y", "@playwright/mcp@latest", "--extension"]
  ```

- 扩展：Chrome Web Store 装 **Playwright MCP Bridge**
  `https://chromewebstore.google.com/detail/playwright-mcp-bridge/mmlmfjhmonkocbjadbfplnigmagldckm`
  （装在哪个 Chrome profile，就能连那个 profile 里已登录的标签页）。
- 免弹窗：点扩展图标打开状态页 → 复制 `PLAYWRIGHT_MCP_EXTENSION_TOKEN` → 写入 config 同节 env：

  ```toml
  [mcp_servers.playwright.env]
  PLAYWRIGHT_MCP_EXTENSION_TOKEN = "<用户提供的 token>"
  ```

  Token 随 profile 走；不配置则每次连接需在扩展弹窗点 approve。
- 生效条件：改完 config 需**重启 Codex**（新 MCP server 才会加载）；扩展未装时 `--extension` 启动后工具不可用。
- 使用纪律：与 Python Playwright 一致——一次会话一个持有者、复用标签页、不混用 ONES 常驻 Edge；
  首个标签页由用户在扩展弹窗里选定（选被测页签），随后按必守清单走标准用户操作，禁止 JS 强制改值/绕过 UI。
- 与脚本的关系：MCP 真窗口适合「探索/人工登录态复用」，批量回归仍可走 Python 长脚本；两者择一，不双写同一用例。
