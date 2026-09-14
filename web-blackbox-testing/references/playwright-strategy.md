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

## 防超时与作用域硬化（2026-09-14 增补）

本次实测出现大量 `Locator.click/inner_text Timeout 30000ms`，根因不是页面慢，而是脚本命中了隐藏页签、旧弹窗、teleport 浮层或已关闭的 dialog。后续脚本必须遵守：

1. **页签作用域**：多页签页面先用 `active_pane(page)`，所有字段、表格、按钮操作都限定在该 Locator 内；禁止全局 `.el-form-item.first`。隐藏 tab 中同名字段常见 `width=0`，点击会等满默认超时。
2. **弹窗作用域**：新增/编辑/导入弹窗用 `dialog_by_title(page, "<标题>")`；不要混用 `.el-dialog:visible`、`.el-overlay-dialog` 和全局按钮。Element Plus 的 select/cascader/date popper 会 teleport，下拉选项只在对应 popper 内查找。
3. **结果状态等待**：保存/导入等操作不要假设弹窗一定关闭。用 `wait_result_or_closed(page, dialog, ["导入完成","失败","已存在"])`，同时处理“结果文本出现”和“弹窗关闭”两种分支。操作后禁止继续读取已 detach 的旧 dialog locator。
4. **接口返回作为业务完成信号**：打开页面或触发操作前先挂 `ApiWatcher` / `wait_for_response_after_action`，以 DevTools Network 同样的方式读取接口 URL、方法、状态码和耗时；接口返回即继续，不能用固定 5 秒猜业务完成。固定超时只用于“元素可点击性/异常上限”，不代表成功。
5. **选择组件严格校验**：下拉用 `select_dropdown_option`，搜索不到目标时不要自动选首项；级联多选用 `select_cascader_values` 选叶并点浮层“确定”，随后断言 tag/value 已回填；控件形态用 `assert_control_type` 单独断言。
6. **失败快停与现场捕获**：定位/状态失败时调用一次 `capture_failure_context(page, out_dir, name, feature=...)`，记录 URL、activity、toast、内联错误、可见 dialog/popper 数量和截图，然后记「阻塞/环境观察」，不要反复重试同一错误 locator。
7. **严格定位优先**：能用标题、label、role 精确定位时不要用 `.first` 掩盖多匹配；多匹配应视为脚本问题，先限定作用域。

推荐动作链：

```python
configure_page_timeouts(page)
pane = active_pane(page)
safe_click(pane.get_by_role("button", name="新增"), timeout=5)
dlg = dialog_by_title(page, "新增")
sel = select_dropdown_option(page, pane.locator(".el-form-item", has_text="产品"), option_text="产品A")
result = wait_result_or_closed(page, dlg, ["成功", "失败", "已存在"])
```

## 分阶段恢复与单登录（2026-09-14 增补）

长任务不得因一次定位错误重新登录、从第一条用例重跑。总入口采用：

1. **持久会话**：MES 使用独立用户数据目录和 CDP 9222；ONES 继续使用 9334，互不干扰。已有会话优先复用。
2. **预检先行**：创建业务数据前先执行 `preflight`，检查直达 URL、活动页签、关键控件类型和按钮状态；关键预检失败直接阻塞当前阶段。
3. **阶段顺序**：`bootstrap → recon → data-setup → core-flow → exceptions → non-core → finalize`；阶段间用 `depends_on` 声明依赖，数据依赖用 `provides_data` / `requires_data` 声明。
4. **检查点粒度**：每条用例结束写 `run_state.json`；业务单号、生成单据等写 `data_ledger.json`。二者不得包含密码、Cookie、Token。
5. **恢复前校验台账**：`--resume` 先运行已注册的 ledger validator；生产阶段提供的数据失效时强制重跑该阶段，依赖该数据的阶段标记阻塞，不编造结果。
6. **恢复策略**：`--resume` 跳过“通过”用例，只重跑失败、阻塞和未执行项；阶段依赖未通过时，后续阶段记为阻塞。
5. **失败分级**：`InfrastructureAbort`、Playwright Timeout、连接异常属于基础异常，保存现场后停止当前阶段；业务断言失败记录后继续。
6. **弹窗 micro-case 批处理**：同一弹窗内的多个字段/校验用例用 `CaseGroupSpec` 组织，只执行一次 `setup/teardown`；每个 micro-case 仍独立写检查点。每个 micro-case 前执行 `reset` 回到已知表单状态；业务失败继续，基础异常停止当前批次。
7. **会话收尾**：全部正常完成才关闭本轮启动的持久浏览器；用户中断或基础异常阻塞时保留会话，供 `--resume` 继续。

## 脚本与执行约定

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
- 脚本内一次登录跑完；执行结束产出报告 / 缺陷清单。数据处理遵循必守 C（结束闸门）：保留造数为主，确需清理时才清理并留痕。

## 接口观测等待（核心约定，2026-08-21 增补）

> 原则见 SKILL「Playwright 使用策略」与参照 api_wait；本段给四步实现与判定细节。

页面数据 = 接口返回后渲染。**不要在操作后固定 sleep 或立即读 DOM 下结论**，
要观测页面实际发出的接口，等"操作触发的业务接口返回"后再断言页面数据。
业务不同接口路径不同，不要预先固化具体接口；用"基线对比"动态识别新请求。

推荐模式（动作前绑定响应，接口返回即继续）：

```python
from api_wait import ApiWatcher

watcher = ApiWatcher(page)                 # 挂 request/response 网络监听
new = watcher.wait_action(
    lambda: page.get_by_role("button", name="查询").click(),
    url_contains="/plan/",                 # 可省略，按任意 xhr/fetch 响应
    timeout=60,                            # 仅异常上限，不表示等满 60 秒
)
if not new:
    # 接口未返回或超时：按失败/环境观察处理，不硬读页面
    raise/标记
page.wait_for_timeout(500)                 # 仅少量 DOM 渲染余量
assert_page_state(...)
```

要点：
- **动作与响应绑定**：用 `ApiWatcher.wait_action` 或 `wait_for_response_after_action`，在点击/切换/提交前建立响应等待。
- **接口返回即完成**：2 秒返回就 2 秒继续；接口慢则继续等；`timeout` 仅保护异常挂死。
- **状态码参与判定**：记录 URL、method、status、耗时；HTTP≥400 直接作为错误信号，不再只看是否有响应。
- **同一 URL 的重复调用可识别**：按响应序号识别，不按 URL 集合去重。
- **不把静态资源算业务接口**：默认只等 `xhr/fetch`，并按需用 `url_contains` 缩小范围。
- `snapshot()+wait_new()` 仅用于“操作已经发生、事后只读观察”的兼容场景；新业务等待全部使用动作绑定模式。

## 等待优先级与无视觉断言（2026-09-07 增补）

> 原则见 SKILL「执行形态与等待基线」；本段给判定顺序与无视觉场景的具体做法。

- 等待优先级：**动作绑定接口返回 > 条件等待 > 固定 sleep（兜底）**。
  1. `api_wait.ApiWatcher.wait_action(...)`：动作前绑定响应，接口返回即继续；
  2. 无接口可观测时用 `wait_visible / wait_text / wait_button / wait_until`；
  3. 固定 `wait_for_timeout` 只用于接口返回后的渲染余量（≤500ms）、首次侦察、无信号兜底。
  一次会话内共用监听器，不重复挂载；同一用例不既用接口等待又叠一堆 sleep。
- 无视觉（后台无头）模式：截图仅作证据归档，判定一律走可见 DOM/文本/接口信号；
  - 点击用 `bbt_helpers.click_visible_text`（按 **role → text → JS** 三级降级；结果里的 `via` 标明命中了哪一级，便于统计定位稳定性；语义定位后用 JS 精确点击（不遍历 DOM，实测 6ms 级；`native=True` 可改用 Playwright 原生点击，约 39ms 但带滚动/稳定性检查）；只取 offsetParent 非空元素，避免命中隐藏 el-dialog__title 等）；
  - 分体按钮（新增▾）用 `bbt_helpers.open_split_add_dropdown`（真实 hover 才能触发 el-popover）；
  - 弹窗内容用 `bbt_helpers.dump_visible_dialogs` 按作用域读取，不再整页 innerText 大海捞针；
  - 关键交互（弹窗 0 条、异常 toast、下拉项）仍截图，供用户/人工抽核防误报。


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
> 组件指纹探针（`--probe`）/ 结构指纹（`--save-fingerprint`）/ 改版对比（`--diff`）/ 自愈定位
> 的完整定式见 [advanced-ui.md](advanced-ui.md) 的「新站点适配侦察定式」。

- 会反复测的页面，固化时同步 `--save-fingerprint <功能名>`；改版后用 `--diff <功能名>` 看差异，不必重新全量侦察。
- 同一页面结构侦察最多 2 次；第 2 次前必须把稳定交互方式（选择器、事件、遮挡处理）写进 references。
- 遇到新交互（自定义弹窗、刷卡层、iframe 多实例）→ 立即补 references 再继续，禁止反复 dump 同一页面。

## 报告与数据留痕（2026-08-21 增补）

> 数据处理遵循 SKILL 必守 C（结束闸门）（测试环境保留造数，按需清理）；本段给报告/清理留痕做法。

- 用例执行结果直接喂 `report_gen.gen_report / gen_bug` 生成报告/缺陷清单骨架，避免手工整理消耗 token。
- 测试改数据后，记录本轮产生数据（单据编号 / 扣减量）；确需清理时用 `data_cleanup.compare_state` 对比基线并 `write_cleanup_note` 留痕「已保留 / 已恢复」。测试环境保留造数为主，不作强制清理。
