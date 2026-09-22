# Playwright 使用策略

> 定位：本文件是「机制/实现细节」的唯一权威；底线与判定原则在 `SKILL.md` 必守清单，此处不复述。
> 组件指纹探针 / 结构指纹 / 改版对比 / 自愈定位的完整定式见 [advanced-ui.md](advanced-ui.md)。

## 多信号判定（防误报核心）

踩坑：必填校验提示常以顶部 toast 弹出而非表单内联错误，只读 `.el-form-item__error` 会把「校验已生效」误判为「静默无提示」（生成方式必填拦截误报）。级联同理——父节点只展开、叶节点才选中，只点父节点会误判「无法回填」。

读全信号层用 `bbt_helpers.read_feedback(page)`（toast + 内联错误 + 可见 dialog），或 `api_wait.confirm_action`。四类信号源：

1. 新业务接口响应（`ApiWatcher.wait_new` / `judge_action` 的 `new_responses`）
2. 顶部 toast（`.el-message` / `.el-notification` / `.el-message-box`）
3. 表单内联校验错误（`.el-form-item__error`）
4. 数据状态变化（操作前后 `data_diff`）

| 场景 | 判定 |
| --- | --- |
| 有新响应 且 无校验类提示 | processed=True, ok=True, reason=success |
| 有校验类提示（toast/内联，如「必须/请选择/大于0/不超过」） | processed=True, ok=False, reason=blocked——记「已处理·被拦截」，**不是失败** |
| 无新响应、无任何提示、数据未变 | processed=False, reason=silent——才需人工核（真·无反馈） |
| 有 HTTP ≥ 400 新响应 | ok=False, reason=http_error |

用 `judge_action(page, action, api_watcher=None, data_diff=None)` 取这四个信号。点击前先判禁用：`click_or_observe(page, 按钮文本)` 在 disabled 时返回 `(disabled, ...)` 记状态观察，避免 click 超时中断整段。

## 防误报的前置条件：输出限长不砍判据

结构输出统一走 `qa_skill_common/output.py` 的 `emit()`：**判定字段（toast / 内联错误 / HTTP 状态 / data_diff）永不截断**，只截元素列表、文本 dump 等观察字段并给出 `counts` / `full_path`。
失败现场用 `capture_failure_context(page, out_dir, name, feature=...)`，**打印它的 `summary`**（判据完整、观察限长），不要 dump 整个 `context`；需要细节时再读它写出的 JSON。

## 防超时与作用域硬化

实测大量 `Locator.click/inner_text Timeout 30000ms` 的根因不是页面慢，而是脚本命中了隐藏页签、旧弹窗、teleport 浮层或已关闭的 dialog。

1. **分层超时**：连接后先 `configure_page_timeouts(page)`（动作 5s、导航 15s；导入/下载单独给 45s），禁止回落默认 30s。
2. **页签作用域**：多页签用 `active_pane(page)`、`visible_form_item(page, label, scope)`，禁止全局 `.first` 命中隐藏 tab。
3. **弹窗作用域**：用 `dialog_by_title(page, "<标题>")`，不要混用 `.el-dialog:visible` / `.el-overlay-dialog` 与全局按钮；Element Plus 的 select/cascader/date popper 会 teleport，选项只在对应 popper 内找。
4. **结果状态等待**：保存/导入不要假设弹窗一定关闭，用 `wait_result_or_closed(page, dialog, ["导入完成","失败","已存在"])` 同时处理「结果文本出现」与「弹窗关闭」；禁止继续读已 detach 的旧 dialog locator。
5. **响应参数匹配作完成信号**：`ApiWatcher.wait_action()` / `wait_for_response_after_action()` 按 URL + method + request JSON/body 匹配，避免抓到 reset 或上一次查询；`timeout` 仅作异常上限。
6. **选择组件严格校验**：下拉用 `select_dropdown_option`，搜不到目标时**不要自动选首项**；级联多选用 `select_cascader_values` 选叶并点浮层「确定」，随后断言 tag/value 已回填；控件形态用 `assert_control_type` 单独断言。
7. **严格定位与收尾**：能用标题/label/role 精确定位就不用 `.first`；关闭现场统一 `close_surface_stack(page)`（先关下拉/级联/日期，再关结果弹窗）。

推荐动作链：

```python
configure_page_timeouts(page)
pane = active_pane(page)
safe_click(pane.get_by_role("button", name="新增"), timeout=5)
dlg = dialog_by_title(page, "新增")
sel = select_dropdown_option(page, pane.locator(".el-form-item", has_text="产品"), option_text="产品A")
result = wait_result_or_closed(page, dlg, ["成功", "失败", "已存在"])
```

## 接口观测等待

**动作与响应绑定**：用 `ApiWatcher.wait_action` / `wait_for_response_after_action`，在点击/切换/提交**前**建立响应等待。

- **接口返回即完成**：2 秒返回就 2 秒继续；接口慢则继续等；`timeout` 仅保护异常挂死。
- **状态码参与判定**：记录 URL、method、status、耗时；HTTP ≥ 400 直接作为错误信号。
- **同一 URL 的重复调用按响应序号识别**，不按 URL 集合去重。
- **不把静态资源算业务接口**：默认只等 `xhr/fetch`，按需用 `url_contains` 缩小范围。
- `snapshot() + wait_new()` 仅用于「操作已发生、事后只读观察」的兼容场景。

**等待优先级**：动作绑定接口返回 > 条件等待（`wait_visible/wait_text/wait_button/wait_until`）> 固定 `wait_for_timeout`（仅 ≤500ms 渲染余量、首次侦察、无信号兜底）。一次会话内共用监听器，不重复挂载；同一用例不既用接口等待又叠一堆 sleep。

## 无视觉（后台无头）模式

截图仅作证据归档，判定一律走可见 DOM/文本/接口信号：

- 点击用 `click_visible_text`（**role → text → JS** 三级降级，结果 `via` 标明命中层级；只取 `offsetParent` 非空元素，避免命中隐藏的 `el-dialog__title`）。
- 分体按钮（新增▾）用 `open_split_add_dropdown`（真实 hover 才触发 el-popover）。
- 弹窗内容用 `dump_visible_dialogs` 按作用域读取，不整页 `innerText` 大海捞针；**输出走 `emit()` 限长**。
- 关键交互（弹窗 0 条、异常 toast、下拉项）仍截图，供人工抽核防误报。

## 失败分级与重试上限

- **环境失败**：接口 502/超时/网络错误/页面空白 → 标「环境观察」，立即跳过，**不重试**（重试只放大无效消耗）。
- **业务失败**：页面出现明确报错提示（如「切换成功」未出现、按钮无响应且无新接口）→ 才算失败，重试 ≤1 次；仍失败按缺陷记录。
- **基础异常**：`InfrastructureAbort`、Playwright Timeout、连接异常 → 保存现场后停止当前阶段（不继续后续用例）。
- **同一操作连续失败最多复现 2 次**；仍不稳定标「偶发现象/环境观察」并换下一步，不无限重试、不反复 dump 同一页面。
- 不稳定操作用 `retry(fn, attempts=2)` 包裹，返回 `(ok, result_or_error)` 交上层判断，脚本里不写裸循环。
- 判定依据优先用 `api_wait.confirm_action` 的返回（新接口 + 错误 + toast），不靠肉眼猜。

## 会话与检查点（单登录 + 恢复）

**一个测试任务 = 一个长脚本 + 一个浏览器会话**：`launch_session` → 登录/导航一次 → 跑完全部用例 → `close_session`。

1. **持久会话**：MES 用独立 user-data 目录 + CDP 9222，ONES 用 9334，互不干扰；禁止与日常 Edge 共用 profile。启动前查 `/json/version` + `/json/list`（假死端口不算可用）；`session.json` 只回收标记为 managed 的旧 PID，无元数据时绝不误杀未知浏览器。`ensure_mes_session` 在 CDP 断开时自动重启并复用同一 profile。
2. **页面持有**：一个会话只有一个持有者；连接常驻浏览器先 `find_page(ctx, url_contains=...)` 复用页面，不重复多开；收尾清理多余标签页，避免堆积导致 CDP 超时。
3. **预检先行**：创建业务数据前先跑 `preflight`（直达 URL、活动页签、关键控件类型、按钮状态），关键预检失败直接阻塞当前阶段。
4. **阶段顺序**：`bootstrap → recon → data-setup → core-flow → exceptions → non-core → finalize`；依赖用 `depends_on`，数据依赖用 `provides_data` / `requires_data` 声明。
5. **检查点粒度**：每条用例结束写 `run_state.json`，业务单号/生成单据写 `data_ledger.json`（不含凭据）。恢复前先跑 ledger validator：数据失效则强制重跑该阶段，依赖它的阶段标阻塞。
6. **恢复策略**：`--resume` 跳过「通过」用例，只重跑失败/阻塞/未执行项；阶段依赖未通过则后续阶段记阻塞。
7. **弹窗 micro-case 批处理**：同一弹窗内的多个字段/校验用例用 `CaseGroupSpec` 组织，只跑一次 `setup/teardown`；每个 micro-case 前 `reset` 回已知表单状态并独立写检查点。业务失败继续，基础异常停止批次。
8. **收尾**：全部正常完成才关闭本轮启动的持久浏览器；用户中断或基础异常时**保留会话**供 `--resume` 继续。

## 脚本与执行组织

- 只允许本机 Python Playwright 无头脚本（UTF-8，写成 `.py` 再执行）；**所有脚本共用一次登录**，不每个脚本新起浏览器重登。
- 先完成登录、菜单定位与结构侦察（`recon-generic/recon_page.py`）再固化脚本。一般一个功能 = 一个执行脚本，按「筛选 → 新增 → 校验 → 编辑 → 复制 → 删除 → 导入 → 清理」大致顺序，但**不是固定配方**——按实际侦察结果调整。
- 表格断言用 `table_columns()` / `read_table_rows()` 按列头取列，不硬编码 `td` 索引（列顺序变化会误判）。
- 截图用 `snap()` 语义化命名（`功能_用例_步骤_时间.png`），只在首页状态、关键通过节点、缺陷现场、导出预览保留证据；缺陷现场截图必须保留供 ONES 使用。
- 慢页面先缩小筛选范围（测试单号、近七天、单个供应商/产品）；不进入「侦察 → 试操作 → 失败 → 再侦察」的循环。

## 侦察 → 固化 → 引用

- 同一页面结构侦察最多 2 次；第 2 次前必须把稳定交互方式（选择器、事件、遮挡处理）写进 references 或知识库。
- 会反复测的页面固化时同步 `--save-fingerprint <host>#<功能名>`；改版后用 `--diff <指纹名>` 看「消失/变化/新增」，不必重新全量侦察。
- 固化内容必须含**直达 URL**（到达目标页后的 `location.href`）；用 `goto(直达URL)` 进入，不重走菜单/搜索。
- 遇到新交互（自定义弹窗、刷卡层、iframe 多实例）立即补 references 再继续，禁止反复 dump 同一页面。

## 报告与数据留痕

- 用例执行结果喂 `report_gen.gen_report / gen_bug` 生成骨架；报告**只由结构化状态生成一次**（`qa_case.py report --run-dir <dir>`），修正走 `conclusions.json` 重渲染，**不手写 markdown 正文**。
- 测试改数据后记录本轮产生数据（单据编号/扣减量）；确需清理时用 `data_cleanup.compare_state` 对比基线并 `write_cleanup_note` 留痕。测试环境保留造数为主，不作强制清理。
