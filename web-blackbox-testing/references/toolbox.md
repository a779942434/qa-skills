# 测试工具箱（scripts/）速查

> 由 `web-blackbox-testing/SKILL.md` 抽出，按需查阅。

- `scripts/recon_page.py`：统一页面侦察器，一次输出 URL/标题/登录态/筛选控件/按钮/表格列头/可见弹窗字段，替代碎片化侦察。
- `scripts/recon-generic/`：通用页面侦察工具（`--url` 参数化，Element UI 页面可复用）：
  - `recon_page.py --url <URL>`：按钮/表头/行/弹窗；
  - `recon_dialog.py --url <URL> --button 新增`：弹窗表单字段结构（label + 控件类型）；
  - `recon_dropdown.py --url <URL> --button 新增`：下拉可见选项；
  - `recon_subtables.py --url <URL>`：点击主表行 dump 子表。
- `scripts/bbt_helpers.py`：
  - **无视觉/盲操作辅助（2026-09-07 新增）**：`click_visible_text(page, text)`（JS 点可见精确文本，自动避开隐藏弹窗标题）、
    `open_split_add_dropdown(page)`（真实 hover 展开「新增▾」类下拉并点首项，如子表「导入 Excel」）、
    `dump_visible_dialogs(page)`（只读可见弹窗文本，替代整页 innerText）。
  - `find_page(ctx, url_contains, title_contains)` / `connect(cdp_url, url_contains=..., title_contains=...)`：连常驻浏览器并优先复用已有页面；
  - `attach_error_watchers(page)` / `collect_toasts()` / `error_report()`：console、HTTP≥400、页面提示三路错误监听；
  - `wait_visible` / `wait_text` / `wait_button` / `wait_toast(page, keyword)` / `wait_until`：条件等待（元素/文本/按钮/提示），替代固定 sleep；
  - `retry(fn, attempts=2)` / `close_dialog(page)`：防无限重试、弹窗收尾清理；
  - `recon_page_structure(page)` / `recon_once(page, url)`：一次性侦察返回页面结构，供固化；
  - `table_columns()` / `read_table_rows()`：按列头读表格；
  - `snap(page, name, out_dir, feature)`：语义化截图命名；
  - `record_baseline()` / `assert_new_target()`：数据基线记录与核对。
  - **防误报/隔离（2026-09-03 新增）**：`read_feedback(page)`（toast+内联错误+可见dialog）、`active_dialog/read_dialog`（作用域读弹窗）、`judge_action(page,action,...)`（多信号判定，`processed=False` 且 reason=silent 才视为无反馈）、`detect_cascade/select_cascade`（**先侦测两级父→子、匹配才走**级联）、`click_or_observe`（先判 disabled，禁用作状态观察）、`reset_to(page,url,页签)`（用例隔离回已知态）。详细用法见 references/playwright-strategy.md。
- `scripts/api_wait.py`：接口观测等待（核心等待方式，替代固定 sleep）。
  - `ApiWatcher(page)`：挂 response 监听（覆盖所有 frame）；
  - `snapshot()`：操作前取响应基线；`wait_new(base, keyword=None, timeout=15)`：等基线之后出现新响应（可用 URL 关键词缩小范围）；
  - `confirm_action(page, action, keyword=None)`：统一操作判定（执行操作→等新接口→收集 HTTP≥400 与 toast→返回 ok/errors），失败原因可直接进缺陷清单；
  - 业务不同无需预知接口路径，靠基线对比动态识别；无新响应 = 操作未生效。
- `scripts/session_helpers.py`：一次会话常驻浏览器助手。
- `scripts/run_all_template.py`：**总入口长脚本模板（B5/B6）**——一个任务一个后台会话一次登录跑完全部用例；
  复制改名为 run_all.py 后按任务改 CONFIG/CASES 即可，建议一次提权批准该总入口（prefix 如 `python3 <run>/run_all.py`）。
  - `launch_session(headless, cdp_port)`：启动新 Chromium（可暴露 CDP 端口）；`connect_session(cdp_url, url_contains)`：连接常驻浏览器并复用已有页面；
  - `close_session(...)`：收尾清理标签页；约定一个会话一个持有者。
- `scripts/report_gen.py`：报告/缺陷清单骨架生成（`gen_report` / `gen_bug`），执行脚本直接喂结果生成 markdown，AI 只补分析。
- `scripts/data_cleanup.py`：数据基线对比与清理留痕（`compare_state` / `write_cleanup_note`）。**按需使用**：测试环境保留造数为主，仅在确需清理时对比基线并记录已保留/已恢复（遵循必守 C（结束闸门））。
- `scripts/ipc_helpers.py`：IPC 单机/产线界面导航辅助。
  - `unlock_ipc(page, system_password, base_url)`：进入 `/ipc/setting` 并解锁；
  - `select_station_and_save(page, station)`：精确选站并保存配置；
  - `enter_ipc_feature(page, feature, base_url)`：在 `/ipc` 首页进入 `/ipc/single` 或 `/ipc/line`；
  - `setup_and_enter_ipc(...)`：组合上述三步。系统密码与站点由调用方传入，不写死；
  - `set_card_mock(page, card)` / `swipe_card(page, card)`：交接班刷卡测试模拟；
  - `open_handover_dialog(page)`：进入单机界面后打开交接班弹窗。

