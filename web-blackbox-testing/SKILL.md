---
name: web-blackbox-testing
description: >-
  无源码场景下的网站黑盒测试、冒烟、核心流程验证、缺陷复现、回归验证与中文留档。
  用户提供网站地址、测试账号、需求说明、接口请求或截图证据，或要求
  "帮我测一下""黑盒测试""回归验证""用 Playwright 验证页面功能"时使用。
  产出缺陷清单（bug-reports/YYYY-MM-DD_功能名_缺陷清单.md）可直接交给
  ones-create-linked-defect 技能录入 ONES 并跟踪流转。
---

# Web 黑盒测试

> 本技能自带公共实现（`scripts/qa_skill_common/`），**可独立安装**，无需同级 `qa_skill_common`。
> **只读本文件即可开工**；触发对应场景时再读 `references/<x>.md`（见文末「场景索引」），不要一次全读。

## 任务启动契约（默认生效，提示词不必重复）

- **启动闸门**：仅「长任务首次」需要——先输出 ≤10 行执行计划（环境勘察 → 读需求 → 出用例 → 单会话分批次执行 → 报告/缺陷/清理），等确认再进第 3 步。**短任务 / 回归 / 补测不停**。
- **默认输出**：结论、缺陷编号+严重程度、文件绝对路径、数据清理结果、下一步建议；不贴长正文。
- **默认去重**：与 ONES 工单已关联缺陷去重，只提新增。
- **纯黑盒且无工单 URL**：不停，跑完出清单，末尾提示「未提缺陷（缺工单 URL）」；提示词只需给站点/账号、需求、深度、范围、工单 URL。

## 首次使用（3 步）

1. **自检**：`python scripts/check_env.py`（缺浏览器/依赖/站点不通会明确指出）。
2. **配环境**：`export MES_URL=... MES_ACCOUNT=... MES_PASSWORD=...`（总表见 `scripts/qa_skill_common/references/environment.md`）。
3. **开跑**：`python scripts/qa_case.py exec --steps <steps.json> --run-dir <run-dir> --label <ID>`。

> 平台不限；浏览器用本机 Chrome/Edge/Chromium（`MES_BROWSER_PATH` 可指定），依赖只装 `pip install playwright pyyaml`。
>
> **沙箱内浏览器/网络本就不可用**（DNS 失败 / `Operation not permitted` / 「playwright 与本机浏览器均不可用」）——
> **已知前提，不要先在沙箱里试一遍再升级**：浏览器与访问被测站点的命令直接用非沙箱权限（require_escalated）。

## 必守清单（红线 / 默认做法 / 停顿边界）

### A. 红线（违反任一 = 本轮执行失败）

1. **只做标准用户操作**（点击/键入/下拉）：禁止 JS 注入改值、改 DOM/属性绕过校验、对 disabled 强填、改遮挡层级；不可行记「待确认/环境观察」，不许硬绕。
2. **禁止下载浏览器**：只用本机系统 Chrome/Edge/Chromium；不执行 `playwright install`。
3. **仅 Python 后台专用运行**：只允许 Python Playwright 无头长脚本；禁止 Playwright MCP 与 `browser_*`。必须用专用独立 profile，不得连日常 Chrome/Edge、现有标签页或 ONES CDP 9334；同一时间只允许一个任务持有。仅用户明确要求可见窗口时才前台。
4. **不脑补**：需求/接口/字段没有的一律不编造；必填来源不明标「待确认/需造数」。
5. **不泄露凭据**：账号、密码、Token、Cookie、个人敏感信息不写入报告、截图文件名或知识库。
6. **不碰历史数据**：只操作本轮创建或用户明确授权的数据；未确认环境性质时按生产环境保守处理。
7. **判定缺陷前必须多信号**：结论是「无提示/无法操作/未生效」时，必须确认四源（新接口 + toast + 内联错误 + 数据变化）**全为负**（`judge_action` 的 `reason="silent"`）；只看单层信号不得下结论。
8. **输出限长不得砍判据**：禁止裸 dump，结构输出走 `qa_skill_common/output.py` 的 `emit()`。**判定信号（toast / 内联错误 / HTTP 状态 / data_diff）永不截断**，只截元素列表、文本 dump 等观察字段——截断它们会把「有 toast 的拦截」误判成「静默无反馈」（BUG-009 的真实误报路径）。

### B. 默认做法（可自行决定，不必逐一确认）

1. **复用固化脚本**：登录/导航用 `qa_skill_common`（`login_for_page`/`goto`），侦察用 `recon-generic/recon_page.py`，造数用 `bbt_osd_setup.py`，提缺陷用 `ones_submit_defects.py`；确有缺口才扩展，不写平行替代。
2. **一次会话跑完**：一次登录 + 一个总入口长脚本串行跑完全部用例，不按用例反复起浏览器/登录。
3. **等待优先级**：接口/响应绑定等待 > 条件等待 > 固定 sleep（仅 ≤500ms 渲染余量/首次侦察兜底）。
4. **失败分级**：接口 5xx/超时 = 环境观察，跳过不重试；页面明确报错 = 业务失败，重试 ≤1 次后进缺陷清单。**校验被拦截（有 toast/内联错误）= 已处理业务拦截，记「通过/已拦截」≠ 失败**。
5. **侦察纪律**：同一页面侦察 ≤2 次；固化必须含**直达 URL**，入口一律 `goto(直达URL)` 不重走菜单；goto 后被重定向说明前置没做（未解锁/未选站），先补前置。

### C. 停顿边界（只在这些情况才停下问用户）

| 情形 | 处理 |
| --- | --- |
| 需要动本机状态（起常驻浏览器、复制 Edge 登录态、写桌面） | 执行前**一次**授权；授权后本次任务内不再逐步确认 |
| 要提缺陷但没有工单 URL | 仍停（提缺陷属外部写入） |
| **只做黑盒测试、没有工单 URL** | **不停**：正常跑完，产出缺陷清单，末尾提示「未提缺陷（缺工单 URL）」 |
| 新站点组件库/登录与固化不同 | **先试最小适配**（传参/环境变量/换选择器），成功即继续；只有登录形态无法推断时才停 |
| 选择器命中失败 | 自行侦察 ≤2 次后调整，不必问 |
| 标准操作不可行（disabled、遮挡等） | 不停不硬绕：记录「待确认/环境观察」，继续后续用例 |

### D. 自动继续边界（无需确认即可自行继续）

换页面/换用例、调整选择器、最小适配改传参、失败重试 ≤1 次、追加用例、补截图、生成报告与缺陷清单 —— **都不需要**停下来问。

> **结束闸门**：测试环境保留造数为预期，确需清理才清理并留痕；记录本轮产生数据。`record_baseline/assert_new_target` 仅用于防误动历史数据。证据截图归档 `<产物根>/bug-reports/<功能>/`，缺陷清单「证据」只写纯文件名；报告/缺陷/用例归档 `<产物根>/knowledge-base/`（产物根见 environment.md）。

## 执行形态（单会话 + 批次闭环 + 检查点恢复）

**一个任务 = 一个持久会话 + 一次登录 + 分批次执行 + 检查点恢复。**

```bash
python scripts/qa_case.py exec  --steps steps.json --run-dir <run-dir> --label C07  # 探索性动作序列
python scripts/qa_case.py run   --spec <run-dir>/run_all.py --resume              # 跑一批用例
python scripts/qa_case.py status --run-dir <run-dir>                              # 一行摘要
python scripts/qa_case.py report --run-dir <run-dir>                              # 由状态重渲染报告
python scripts/qa_case.py pages  --url <URL> --feature <功能名>                    # 查站点注册表
```

- 总入口脚本从 `scripts/run_all_template.py` 复制到 `<run-dir>/run_all.py` 后按任务改 CONFIG。
- **一次调用跑一批**，禁止一条用例一次调用；`run` 重跑带 `--resume`（`exec` 无 resume，重跑先确认幂等）。实测 65% 的轮次花在「写脚本→跑→读错→改→重跑」上，这是最大的一项提速。
- stdout 只回**单行 JSON 摘要（≤4KB）**；完整现场落 `<run-dir>/cases/<label>.json`，要细节再读该文件。
- 持久 MES Edge 用独立 profile + CDP 9222；启动前查 `/json/version` + `/json/list`；假死重启后 `--resume` 续跑。
- 分层超时：动作 5s / 导航 15s / 异步查询 15s / 导入下载 45s（禁止回落默认 30s）。业务完成用 `ApiWatcher.wait_action()` 按 URL+method+body 匹配；表单字段用 `visible_form_item()` 限定可见页签/弹窗；收尾用 `close_surface_stack()`。
- 失败只抓一次 `capture_failure_context` 并**打印其 `summary`**（判据完整、观察限长），禁止反复白等。细节见 [references/playwright-strategy.md](references/playwright-strategy.md)。

## 跨会话复用（注册表 + 两级可信度）

- 开工先 `qa_case.py pages --url <URL> --feature <功能名>`：**命中 `verified` 才允许直接 goto**。
- **两级可信度**：验证可达且落到目标页 → `verified:true`；仅观测到（如报错后的中间页）→ `verified:false`，只作线索，仍走 `goto_feature` 并按结果回写。
- **一致性校验**：命中 verified 并 goto 后校验「标题归一化一致」或「组件库判定一致且为已知库」；不一致自动标 `stale`、降级并回退重侦察。
- 反复测的页面侦察后 `--save-fingerprint <host>#<功能名>` 固化指纹，改版用 `--diff` 看差异。
- **用例复用**：同一功能在 `knowledge-base/test-cases/` 已有用例时默认**复用 + 差量更新**（先 diff 需求点 R-01…），不重新全量生成；回归/补测复用上一轮用例表。

## 快速分层

给了完整 PRD/需求文档/流程图，或用户说「按需求测 / 标准测试」，一律走**标准功能测**（涉导入导出/金额库存/权限/上线前回归则**深度专项测**），且**必须**调 `$generate-manufacturing-test-cases` 出用例表，不得自行手写。**快速核心流**仅在用户明确要求快速冒烟且未给完整需求时用。

| 模式 | 适用 | 执行范围 | 交付物 |
| --- | --- | --- | --- |
| 快速核心流 | 明确要求快速冒烟且无完整需求 | 1 条主链路 + 关键校验 + 明显缺陷 | 简版报告 + 缺陷清单 |
| 标准功能测 | 有需求文档 / 要求「按需求测」 | 核心流、异常、筛选、状态、导入导出基础 | 用例与结果 + 缺陷清单 + 总结 |
| 深度专项测 | 上线前 / 导入导出 / 金额库存 / 权限 / 兼容 | 边界值、组合筛选、数据一致性、回归专项 | 完整计划、用例、证据、报告 |

## 用例生成与执行

1. 把需求输入**完整**交给 `$generate-manufacturing-test-cases`，指定颗粒度，拿八列用例表。
2. 核对每条前置条件能否造数；按 P0 → P1 → P2 执行；造不出数据先向用户要。
3. 逐条执行（共用一次登录，统一走 `qa_case.py`）并挂错误监听；失败用例截图后按缺陷格式转入缺陷清单。
4. 结果写回用例表并归档 `<产物根>/knowledge-base/test-cases/`。

## 报告与缺陷（一次成型）

- 报告**只由结构化状态生成一次**：`qa_case.py report --run-dir <run-dir>`。结论变化时改 `<run-dir>/conclusions.json` 的 `结论` 数组再重渲染，**禁止手写 markdown 正文**（实测同一份报告被逐句重写 16 次）。
- 缺陷清单字段/标题/证据行必须符合[缺陷清单格式契约](scripts/qa_skill_common/references/bug-report.md)；模板与归档规则见 `references/reporting.md`。

## 场景索引（触发时才读对应 reference）

- 新站点 / 组件库不同 / 级联树 → `references/advanced-ui.md`
- 工控机 IPC、交接班、刷卡 → `references/ipc-ui.md`（脚本 `ipc_helpers.py`）
- 造前置主数据（产品 / 工艺路线 / 工序 / BOM）→ `references/master-data-setup.md`（脚本 `bbt_osd_setup.py`）
- 导入 / 导出校验 → `references/import-export.md`（须同时看导入窗口与 `simpleExcel/task/findOne` 返回，二者一致且刷新后确认）
- 修复后回归 → 复现 → 验证相邻影响面 → 页面/导出/接口三方一致 → 写回「回归验证」段 → 交 ones 技能流转
- 数据库/接口一致性核对 → `scripts/qa_skill_common/references/datagrip.md`（只读）
- 工具函数速查 → `references/toolbox.md`
- Element Plus 表单/下拉/表格配方（**做 UI 用例前先看**）→ `scripts/qa_skill_common/references/element-plus-recipe.md`
- 覆盖范围补充点 → `references/test-scope.md`
- 边界 / 前置 / 默认原则 → `references/constraints.md`

## 复用经验

测试后把稳定可复用的业务规则、SQL 口径、页面路径、字段映射或常见缺陷模式补进知识库；不写账号密码、Token、Cookie、真实用户数据。
