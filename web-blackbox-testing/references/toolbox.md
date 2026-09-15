# 测试工具箱（scripts/）速查

> 由 `web-blackbox-testing/SKILL.md` 抽出，按需查阅。

- `scripts/recon_page.py`：统一页面侦察器，一次输出 URL/标题/登录态/筛选控件/按钮/表格列头/可见弹窗字段，替代碎片化侦察。
- `scripts/recon-generic/`：通用页面侦察工具（`--url` 参数化，Element UI 页面可复用）：
  - `recon_page.py --url <URL>`：按钮/表头/行/弹窗；默认行数上限 50（`--limit N` 可调，<=0 不截断），
    `--find <文本>` 只输出命中项（不 dump 全量、省 token），`--json` 输出完整结构（含 counts）；
  - `recon_dialog.py --url <URL> --button 新增`：弹窗表单字段结构（label + 控件类型）；
  - `recon_dropdown.py --url <URL> --button 新增`：下拉可见选项；
  - `recon_subtables.py --url <URL>`：点击主表行 dump 子表。
- `scripts/bbt_helpers.py`：
  - **无视觉/盲操作辅助（2026-09-07 新增）**：`click_visible_text(page, text)`（**role → text → JS 三级降级**点可见精确文本，返回体新增 `via` 标明命中层级，自动避开隐藏弹窗标题；默认 JS 精确点击（快），需要严格可操作性检查时传 `native=True`）、
    `open_split_add_dropdown(page)`（真实 hover 展开「新增▾」类下拉并点首项，如子表「导入 Excel」）、
    `dump_visible_dialogs(page)`（只读可见弹窗文本，替代整页 innerText）。
  - `find_page(ctx, url_contains, title_contains)` / `connect(cdp_url, url_contains=..., title_contains=...)`：连常驻浏览器并优先复用已有页面；
  - `attach_error_watchers(page)` / `collect_toasts()` / `error_report()`：console、HTTP≥400、页面提示三路错误监听；
  - `wait_visible` / `wait_text` / `wait_button` / `wait_toast(page, keyword)` / `wait_until`：条件等待（元素/文本/按钮/提示），替代固定 sleep；
  - `retry(fn, attempts=2)` / `close_dialog(page)`：防无限重试、弹窗收尾清理；
  - `recon_page_structure(page, max_rows=50, max_buttons=60, ...)` / `recon_once(page, url, **kw)`：
    一次性侦察返回页面结构（列表项限量，新增 `counts` 告知实际总数，便于判断是否被截断），供固化；
  - `table_columns()` / `read_table_rows()`：按列头读表格；
  - `snap(page, name, out_dir, feature)`：语义化截图命名；
  - `record_baseline()` / `assert_new_target()`：数据基线记录与核对。
  - **防超时/作用域（2026-09-14 新增）**：`configure_page_timeouts(page)` 分层默认超时；`active_pane(page)` 锁定可见页签；`dialog_by_title(page,"新增")` 精确定位弹窗；`safe_click(...)` 短超时结构化点击；`wait_result_or_closed(...)` 同时等待结果或弹窗关闭；`select_dropdown_option(...)` 锁定 popper 搜索选择；`capture_failure_context(...)` 一次捕获截图+活动区/浮层/反馈 JSON；`assert_control_type(...)` 断言真实控件类型；`select_cascader_values(...)` 级联选叶并提交；`wait_dropdown_closed(...)` 确认选择浮层已关闭。
  - **防误报/隔离（2026-09-03 新增）**：`read_feedback(page)`（toast+内联错误+可见dialog）、`active_dialog/read_dialog`（作用域读弹窗）、`judge_action(page,action,...)`（多信号判定，`processed=False` 且 reason=silent 才视为无反馈）、`detect_cascade/select_cascade`（**先侦测两级父→子、匹配才走**级联）、`click_or_observe`（先判 disabled，禁用作状态观察）、`reset_to(page,url,页签)`（用例隔离回已知态）。详细用法见 references/playwright-strategy.md。
- 组件指纹 / 结构对比 / 自愈定位（2026-09-11 新增，实现见 `qa_skill_common/fingerprint.py`）：
  - `recon_page.py --url <URL> --probe`：组件指纹探针（class 前缀分布 + 组件库判定，只读）；
  - `recon_page.py --url <URL> --save-fingerprint <名字>` / `--diff <名字>`：结构指纹快照与改版对比
    （报出消失 / 变化 / 新增，替代人工重新侦察）；
  - `fingerprint.resolve(page, selector=/text=, fingerprint=<名字>)`：选择器失效时按元素特征相似度自愈；
    低置信不猜、返回候选（`ambiguous` / `low_confidence`）；
  - `click_visible_text(..., heal="<名字>")`：把自愈挂成第 4 级降级（三级都失败才走）。
  - 指纹存 `<workspace>/fingerprints/<名字>.json`（本机、不入 git、web 与 ones 两技能共享）。
- `scripts/api_wait.py`：DevTools Network 风格的接口观测等待（核心等待方式，替代固定 sleep）。
  - `ApiWatcher(page)`：挂 request/response 监听（覆盖所有 frame），记录方法、URL、状态码、耗时和请求序号；同一 URL 的重复调用也可识别；
  - `wait_for_response_after_action(page, action, url_contains=..., method=..., request_json=..., timeout=60)`：按 URL + method + 请求 JSON/body 精确匹配；接口返回立即继续，timeout 只作异常上限；
  - `wait_action(action, keyword=None, method=..., request_json=..., timeout=60)`：推荐入口；动作与接口响应绑定，接口返回即继续，timeout 仅异常上限；
  - `snapshot()` + `wait_new(...)`：仅保留给“响应已经发生、只读观察”的兼容场景；
  - `confirm_action(page, action, keyword=None)`：默认使用动作绑定接口等待，再收集 HTTP≥400、toast、内联错误；
  - 业务不同无需预知接口路径，靠基线对比动态识别；无新响应 = 操作未生效。
- `qa_skill_common/preflight.py`：通用预检（URL/标题/活动页签/控件类型/按钮状态）；配合 `PhaseSpec.preflight` 在造数前阻塞。
- `scripts/session_helpers.py`：一次会话常驻浏览器助手。新增 `start_persistent_session` / `connect_persistent_session` / `ensure_mes_session` / `stop_persistent_session`，默认使用仓库外用户数据目录和 CDP 9222。
- `scripts/run_all_template.py`：**分阶段可恢复总入口**——一个任务一个持久会话、一次登录；支持 `--resume`、`--phase <id>`、`--connect`。
  - 每用例写 `run_state.json`，测试数据写 `data_ledger.json`；基础异常快停、业务失败继续。
  - 底层运行器见根公共包 `qa_skill_common/phase_runner.py`；`CaseGroupSpec` 用于弹窗 micro-case 批处理，同一弹窗只开关一次，每个 micro-case 独立检查点；旧 `CASES` 写法仍可用。
- `scripts/qa_skill_common/import_helpers.py`：导入边界框架（混合文件、terminal 响应等待、失败文件下载/解析、部分成功校验）。
- `scripts/qa_skill_common/field_contracts.py`：字段契约注册表（页面标签、控件类型、接口字段、值格式、别名）。
- `scripts/qa_skill_common/data_factory.py`：测试批次 ID、唯一编号与数据配方前置校验。
- `scripts/report_gen.py`：报告/缺陷清单骨架生成（`gen_report` / `gen_bug`），执行脚本直接喂结果生成 markdown，AI 只补分析。
- `scripts/data_cleanup.py`：数据基线对比与清理留痕（`compare_state` / `write_cleanup_note`）。**按需使用**：测试环境保留造数为主，仅在确需清理时对比基线并记录已保留/已恢复（遵循必守 C（结束闸门））。
- `scripts/ipc_helpers.py`：IPC 单机/产线界面导航辅助。
  - `unlock_ipc(page, system_password, base_url)`：进入 `/ipc/setting` 并解锁；
  - `select_station_and_save(page, station)`：精确选站并保存配置；
  - `enter_ipc_feature(page, feature, base_url)`：在 `/ipc` 首页进入 `/ipc/single` 或 `/ipc/line`；
  - `setup_and_enter_ipc(...)`：组合上述三步。系统密码与站点由调用方传入，不写死；
  - `set_card_mock(page, card)` / `swipe_card(page, card)`：交接班刷卡测试模拟；
  - `open_handover_dialog(page)`：进入单机界面后打开交接班弹窗。

