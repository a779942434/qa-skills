---
name: web-blackbox-testing
description: >-
  用于在没有源代码、只能访问网站链接和需求文档时，快速开展网站黑盒测试、冒烟测试、
  核心流程验证、缺陷复现、回归验证和中文留档。
  用户提供网站地址、测试账号、菜单名称、需求说明、接口请求、Excel/截图证据，
  或要求"帮我测一下""黑盒测试""精简测试流程""用 Playwright 验证页面功能"时使用。
  测试产出的缺陷清单（bug-reports/YYYY-MM-DD_功能名_缺陷清单.md）
  可直接交给 ones-create-linked-defect 技能录入 ONES 并跟踪回归流转。
---

# Web 黑盒测试

> 本技能自带公共实现（`scripts/qa_skill_common/`），**可独立安装**，无需同级 `qa_skill_common`；公共实现由仓库根 `vendor-common.sh` 统一生成。
>
> **按需加载**：只读本文件即可开工；仅当触发对应场景时再读 `references/<x>.md`（工具箱 / 测试范围 / Playwright 策略 / IPC / 导入导出 / 主数据 / 报告），不要一次全读。

## 首次使用（3 步）

> **平台**：Windows / macOS / Linux 均可；浏览器统一用**本机系统 Chrome/Edge/Chromium**（自动探测，可用 `MES_BROWSER_PATH` 指定），**禁止下载浏览器**。

1. **自检**：`python scripts/check_env.py` —— 有 FAIL 先按「修复指引」补齐（缺浏览器 / 缺依赖 / 站点不通都会明确指出）。
2. **配环境**：按 [环境与前置配置总表](scripts/qa_skill_common/references/environment.md) 设置 `MES_URL` / `MES_ACCOUNT` / `MES_PASSWORD`（IPC、数据库、ONES 变量按需）。
   ```bash
   export MES_URL="http://<你的测试站点>" MES_ACCOUNT="admin" MES_PASSWORD="<密码>"
   ```
3. **开跑**：把站点 URL + 账号 + 需求文档发我即可；标准功能测会先出用例再执行。

> 依赖只装 Python 包：`pip install playwright pyyaml`（**不要** `playwright install`）。

## 高频坑速查（三条最贵的）

1. **新站点先适配再动手**：先跑组件指纹探针（`recon_page.py --probe`，一次给出组件库判定与未知前缀）与登录形态；不同就换选择器/登录，不套旧站点。入口优先用**全局搜索按功能名直达**，不走菜单逐级点。
2. **盲点按钮/隐藏弹窗是高频误点源**：点击用 `bbt_helpers.click_visible_text`；「新增▾」类下拉用 `open_split_add_dropdown`；读弹窗用 `dump_visible_dialogs`。
3. **页面改版先看差异再动手**：固化过的页面改版后先跑 `recon_page.py --url <URL> --diff <指纹名>` 看「消失 / 变化 / 新增」，只改受影响的部分；选择器失效时 `click_visible_text(page, text, heal="<指纹名>")` 可自愈，不必重新全量侦察。

> 执行形态（一次会话一个总入口脚本）、等待基线、无视觉判定等已归入下方「必守清单 B」与「执行形态与等待基线」，此处不重复。

目标：在授权测试环境中，用最少步骤验证最大业务风险，并把结论用中文留档。默认优先快测，不追求一次覆盖所有细枝末节。

## 必守清单（分级：红线 / 默认做法 / 停顿边界）

> 与前版「违反任一即失败」相比，这里分三档：只有 **A 红线**违反才算本轮执行失败；
> **B 默认做法**可在合理范围内自行决定；**C 停顿边界**只在真正必要时才停下问用户。

### A. 红线（违反任一 = 本轮执行失败）

1. **只做标准用户操作**（点击 / 键入 / 下拉）。**禁止** JS 注入改值、改 DOM/属性绕过校验、对 disabled 输入框强填、改遮挡元素层级；标准操作不可行时记为「待确认/缺陷/环境观察」，**不许硬绕**。
2. **禁止下载浏览器**：只用本机系统 Chrome/Edge/Chromium（`MES_BROWSER_PATH` 可指定）；**不执行** `playwright install`。
3. **不脑补**：需求/接口/字段没有的一律不编造；必填字段来源不明就标「待确认/需造数」。
4. **不泄露凭据**：账号、密码、Token、Cookie、个人敏感信息不写入报告、截图文件名或知识库。
5. **不碰历史数据**：只操作本轮创建或用户明确授权的数据；未确认环境性质时按生产环境保守处理。
6. **判定缺陷前必须多信号**：凡结论是「无提示 / 无法操作 / 未生效」，必须确认四源（新接口 + toast + 内联错误 + 数据变化）全为负（`judge_action` 的 `reason="silent"`）；只看单层信号（仅内联错误 / 仅 toast / 仅无响应）不得下结论。

### B. 默认做法（可自行决定，不必逐一确认）

1. **复用固化脚本**：登录/导航用 `qa_skill_common`（`login_for_page`/`goto`），侦察用 `recon-generic/recon_page.py`，造数用 `bbt_osd_setup.py`，提缺陷用 `ones_submit_defects.py`；确有缺口才扩展，不另写平行替代脚本。**等待用 `api_wait.ApiWatcher`（不用 `wait_for_timeout` > 500ms）；判定操作结果用 `judge_action` 四源交叉；多级交互（级联/树）先 `detect_cascade` 再点。**
2. **一次会话跑完**：一次登录 + 一个总入口长脚本串行跑完全部用例，不按用例反复起浏览器/登录。
3. **等待优先级**：接口/响应基线等待 > 条件等待 > 固定 sleep（仅 ≤500ms 渲染余量/首次侦察兜底）。
4. **侦察纪律**：同一页面侦察 ≤2 次，结果固化进 references 后直接引用；不 dump 整页文本。固化必须含**直达 URL**（到达目标页后的 `location.href`）——用例入口一律 `goto(直达URL)`，不重走菜单/搜索逐级点；**goto 后被重定向说明前置没做**（如未解锁、未选站），先补前置再直达。会反复测的页面，固化时**同步 `--save-fingerprint <功能名>` 存机器指纹**，改版后用 `--diff <功能名>` 看差异，不必重新侦察。
5. **失败分级**：接口 5xx/超时 = 环境观察，跳过不重试；页面明确报错 = 业务失败，重试 ≤1 次后进缺陷清单。**校验被拦截（有 toast/内联错误）= 已处理业务拦截，记「通过/已拦截」≠ 失败**。
6. **环境勘察先行**：开工先确认浏览器可用、站点连通、账号可登录（可先跑 `python scripts/check_env.py`）。

### C. 停顿边界（只在这些情况才停下问用户）

| 情形 | 处理 |
| --- | --- |
| 需要动本机状态（起常驻浏览器、复制 Edge 登录态、写桌面） | 执行前**一次**授权；授权后本次任务内不再逐步确认 |
| 要提缺陷但没有工单 URL | 仍停（提缺陷属外部写入，需工单 URL） |
| **只做黑盒测试、没有工单 URL** | **不停**：正常跑完，产出缺陷清单，末尾提示「未提缺陷（缺工单 URL）」 |
| 新站点组件库/登录与固化不同 | **先试最小适配**（同一函数传参 / 环境变量 / 换选择器），成功即继续；只有登录形态无法推断时才停 |
| 选择器命中失败 | 自行侦察 ≤2 次后调整，不必问 |
| 标准操作不可行（disabled、遮挡等） | 不停不硬绕：记录「待确认/环境观察」，继续后续用例 |

### D. 自动继续边界（无需确认即可自行继续）

换页面 / 换用例、调整选择器、按最小适配改传参、失败重试 ≤1 次、追加用例、补截图、生成报告与缺陷清单 —— **都不需要**停下来问。

> **结束闸门**：测试环境保留造数为预期，仅当确需清理时才清理并留痕；记录本轮产生数据（单据编号/扣减量）。
> `record_baseline/assert_new_target` 仅用于防误动历史数据。证据截图归档到 `<产物根>/bug-reports/<功能>/`（产物根见 [environment.md](scripts/qa_skill_common/references/environment.md)），缺陷清单「证据」只写纯文件名；报告/缺陷/用例归档到 `<产物根>/knowledge-base/`。

## 新站点适配侦察定式

适用：目标站点组件库/登录与固化站点不同（自研组件、非 Keycloak、iframe 等）。
定式（组件指纹 → 全局搜索直达 → 一次会话内侦察固化 → 交互先探后点）见 [references/advanced-ui.md](references/advanced-ui.md) 的「新站点适配侦察定式」。

## 边界 / 前置 / 默认原则

- **不用本技能**：有源码需代码级定位、未授权系统、白盒/性能/安全渗透 → 说明并转对应流程。
- **默认原则**：中文输出；不写密码/Token/Cookie/敏感信息；只碰本轮数据；未确认环境按生产保守；优先真实浏览器验证。
- **开工前准备**：确认环境性质与账号权限 → 拿 URL/需求/数据范围（缺失先要）→ 数据勘察（不足标「数据受限未覆盖」）→ 需求未明确项前置确认 → 沙箱受限改用非沙箱权限 → 一次登录 + 侦察固化。

细则见 [references/constraints.md](references/constraints.md)。

## 执行形态与等待基线

**一个任务 = 一个常驻会话 + 一个总入口长脚本，一次登录串行跑完**；
**等待优先级：接口/响应基线等待 > 条件等待 > 固定 sleep（仅 ≤500ms 渲染余量/首次侦察兜底）**。
细节（总入口模板 `scripts/run_all_template.py`、`api_wait.ApiWatcher`、无视觉断言纪律）见 [references/playwright-strategy.md](references/playwright-strategy.md)。

## 快速分层

收到测试任务后先选择测试深度。**只要用户提供了完整 PRD/需求文档/流程图，或明确说「按需求测 / 标准测试 / 标准功能测」，一律按「标准功能测」（若涉及复杂导入导出/金额库存/权限/上线前回归则为「深度专项测」）处理，并必须调用 $generate-manufacturing-test-cases 技能生成用例表，不得自行手写用例。**「快速核心流」仅当用户**明确**要求快速冒烟/嫌慢/只想先判断能不能用、且未提供完整需求时才允许使用；不得因省事或赶时间自行降级到快速核心流。

| 模式 | 适用场景 | 执行范围 | 交付物 |
| --- | --- | --- | --- |
| 快速核心流（仅用户明确要求快速冒烟且未给完整需求时） | 用户明确要求快速冒烟/嫌慢/只想先判断能不能用 | 1 条主链路 + 关键校验 + 明显缺陷 | 简版报告 + 缺陷清单 |
| 标准功能测 | 用户要求"按需求测一下" | 核心流、异常、筛选、状态、导入导出基础验证 | 测试用例与结果 + 缺陷清单 + 总结 |
| 深度专项测 | 上线前、复杂导入导出、金额库存、权限、兼容 | 边界值、组合筛选、数据一致性、回归和专项 | 完整计划、用例、证据、报告 |

## 测试用例生成（标准功能测 / 深度专项）

需要完整用例表时，统一调用 `$generate-manufacturing-test-cases` 生成，**不自行手写**。执行顺序：

1. 把需求输入**完整**交给该技能（PRD / 流程图 / 补充规则 / 字段清单），指定颗粒度（标准功能测试版 / 开发自测版）。
2. 拿到八列用例表（用例ID / 需求点 / 优先级 / 测试模块 / 测试点 / 前置条件 / 操作步骤 / 预期结果）。
3. 先核对每条前置条件能否造数；按 P0 → P1 → P2 顺序执行；造不出数据先向用户要。
4. 逐条执行（**所有脚本共用一次登录**），统一挂错误监听；失败用例截图并按缺陷格式转入缺陷清单。
5. 结果写回用例表（通过 / 失败 / 阻塞）+ 证据，归档到 `<产物根>/knowledge-base/test-cases/`。

覆盖范围补充点（筛选/表格/按钮/校验/文件等）见 [references/test-scope.md](references/test-scope.md)，按需读。

## 快速核心流流程

1. 读取需求；用户要求先出用例时，调用 `$generate-manufacturing-test-cases`
   生成「开发自测版」用例再执行；否则只提炼三类内容：
   核心业务链路、强校验规则、关键状态流转。
2. 打开网站并登录，只记录环境、账号角色、菜单、浏览器、时间窗口。
3. 创建一条专用测试数据，命名带测试标识，便于筛选和清理。
4. 跑一条端到端主链路，例如：新增主表 → 新增子表 → 审核 → 明细/导出可见 → 取消审核 → 删除清理。
5. 对每个必填、数值、日期、状态按钮只抽取最高风险用例验证，不做全排列。
6. 失败时截图和记录步骤；通过项只记录结果，不重复截图。所有用例默认挂错误监听（console / HTTP≥400 / 页面提示），有错必报，防止"假通过"。
7. 测试结束的数据处理遵循必守 C（结束闸门）：保留造数为主，确需清理时才清理并留痕，并记录本轮产生数据。

**数据基线（防误动已有数据）**：测试开始前用 `bbt_helpers.record_baseline()`
记录当前表格行标识（如单号），新增/编辑/删除目标先 `assert_new_target()` 核对，只操作基线外数据。
（是否清理遵循必守 C（结束闸门）：测试环境保留造数，仅在确需清理时才删基线外数据。）

## IPC 单机/产线界面与交接班

涉及工控机（IPC）页面时**先读 [references/ipc-ui.md](references/ipc-ui.md)**（入口、解锁/选站、单机/产线、交接班、刷卡、选择器速查）。
辅助脚本 `scripts/ipc_helpers.py`（`setup_and_enter_ipc` / `set_card_mock` / `swipe_card` / `open_handover_dialog`）；入口走「功能管理 → 业务流程」，不用首页搜索框。

## 造前置主数据

测试 MES 功能（如订单周期定义表）需要先造主数据（产品 / 工艺路线 / 工序 / 产品 BOM）时，
先读 `references/master-data-setup.md`：三个页面的造数入口、必填字段与「点击主表行出现子表」交互。

## 导入 / 导出测试

涉及导入模板、上传校验、导出一致性时，先读 `references/import-export.md`。
要点：模板必填标记、页面导入窗口提示、导出字段/日期/精度一致性都要核对。
导入是否成功必须同时看页面导入窗口和 `linkim-pc/admin-console/simpleExcel/task/findOne`
的最新返回，二者要一致；导入成功后还需刷新页面数据，再确认是否正确新增 / 覆盖数据。

## 修复后回归

1. 按缺陷单复现：用原操作步骤确认问题在修复后是否消失。
2. 验证相邻影响面：同页面其它字段/按钮、上下游页面、导入导出的同一字段。
3. 数据一致性核对：页面 vs 导出 vs 接口结果一致（口径见"缺陷易漏点补充"）。
4. 更新结论并留档：通过/未通过/环境观察，附证据。
5. 衔接 ONES：回归结果写回 `bug-reports/YYYY-MM-DD_功能名_缺陷清单.md` 的"回归验证"段，
   由 ones-create-linked-defect 技能执行关闭（通过）或评论 @处理人（未修复）并流转主工单。

## Playwright 使用策略

**Element Plus 表单/下拉/表格交互配方**（7 个高频坑 + 直接可用的 helper：`form_item` / `open_select` / `select_option` / `select_value` / `select_is_multiple` / `table_col` / `open_dropdown_menu` / `goto_feature`）见 [scripts/qa_skill_common/references/element-plus-recipe.md](scripts/qa_skill_common/references/element-plus-recipe.md)（**做 UI 用例前先看**）。

详见 [references/playwright-strategy.md](references/playwright-strategy.md)（多信号判定、接口观测等待、失败分级、脚本与执行约定）；级联/树选择、Playwright MCP 真窗口、新站点适配定式见 [references/advanced-ui.md](references/advanced-ui.md)（按需）。三条最常用：

- 复用已有页面，不重复多开。
- **接口观测等待（必做）**：操作后先等业务接口返回再断言（`scripts/api_wait.py`），不直接读 DOM 下结论。
- 用例间隔离：`try/except` + `reset_to` 回到已知态，单条失败不中断整段。

## 测试工具箱 / 测试范围

- 工具速查（bbt_helpers / api_wait / report_gen…）：[references/toolbox.md](references/toolbox.md)
- 标准功能测范围 与 深度专项触发条件：[references/test-scope.md](references/test-scope.md)

## 数据库与接口辅助

需要数据查验、页面 vs 数据库 / 接口一致性核对时，先读 `scripts/qa_skill_common/references/datagrip.md`（随技能内置）。
只做用户授权范围内的只读查询；凭据按环境变量 → 本机凭据 → DataGrip 配置的顺序取。

## 缺陷记录、报告与归档

缺陷清单字段/标题/证据行必须符合[缺陷清单格式契约](scripts/qa_skill_common/references/bug-report.md)（生成侧已固化，改格式会被自检拦住）。

需要缺陷字段模板、严重程度口径、快速报告模板或归档规则时，
先读 `references/reporting.md`。

## 复用经验

测试结束后，如果发现稳定可复用的业务规则、SQL 口径、页面路径、字段映射或常见缺陷模式，
将其补充进项目知识库；但不要把账号密码、Token、Cookie、真实用户数据写入 skill 或知识库。
