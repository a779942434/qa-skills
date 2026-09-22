# 会话成本基线（真实遥测）

> 数据源：本机 `~/.codex/sessions/**/rollout-*.jsonl` 的 `token_count` 事件。
> 复现：`python3 tools/measure_context.py --sessions --limit 10`
>
> 成本模型：会话成本 ≈ Σ(每轮重发 context) ≈ `N × avg_context`。
> **等效全价输入 = 缓存 × 0.1 + 未缓存**（缓存计价系数见 `tools/measure_context.py` 的 `CACHE_PRICE`）。

## 基线快照（2026-09-22 采集）

| 会话 | 轮次 | 输入 | 其中缓存 | 未缓存 | 输出 | 等效全价输入 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 委外发料明细(2)（跨 3 天，含改 skill） | 1,647 | 521.41M | 516.37M | 5.04M | 1.42M | 56.68M |
| 焊接看板（续会话 3 段） | 194 | 96.49M | 95.05M | 1.44M | 394k | 10.95M |
| **大富 3.0 分单计划（标准功能测，13 用例）** | **347** | **84.47M** | **84.24M（99.7%）** | **0.23M** | **214k** | **8.65M** |
| 产线定义+订单计划排产（用 MCP） | 377 | 74.46M | 73.92M | 0.54M | 138k | 7.93M |
| 焊接看板（首段） | 90 | 67.45M | 66.18M | 1.27M | 296k | 7.89M |
| 委外发料明细-零件委外 | 222 | 62.68M | 61.99M | 0.69M | 283k | 6.88M |

## 大富会话的成本拆解（主参考）

- context 曲线：**36.8k → 435.6k**，均值约 243k，近似线性
- 初始前缀贡献 ≈ 36.8k × 347 ≈ 12.8M（**占总输入 15%**）
- 会话中新增内容贡献 ≈ 71.7M（**占总输入 85%**）
- 工具输出累计 **2.09M 字符**，86 条 >2k 字符，14 张图
- 轮次构成：跑已有脚本 41.5% + 写跑内联脚本 23.6% + 读文件 11% + 搜索 6.1%
  → **约 65% 的轮次花在脚本往返**
- 输出含报错痕迹 14%（同期「委外零件」会话为 35%）
- 墙钟 2h20m / 347 轮 ≈ **24 秒/轮**——时间同样被轮次支配

## 结论：杠杆排序

| 排序 | 杠杆 | 承接的成本 | 手段 |
| --- | --- | --- | --- |
| 1 | 压脚本往返轮次 | 65% 的轮次 | `qa_case.py` 单用例/批次闭环 |
| 2 | 压每轮新增输出 | 85% 的 context 增长 | `qa_skill_common/output.py` 限长契约 |
| 3 | 跨会话复用 | 重复侦察/重复生成 | 站点注册表 + 用例/报告复用 |
| 4 | 文档瘦身 | ≤11%（再砍 30% ⇒ ≤3.5%） | SKILL/reference 去重压缩 |

## 同题验收目标

以「大富 3.0 分单计划（标准功能测）」为锚，同站点/同功能/同用例集复跑：

- 轮次 **≤ 60%**（347 → ≤208）
- 工具输出字符 **≤ 30%**（2.09M → ≤630k）
- 等效全价输入 **≤ 40%**（8.65M → ≤3.46M）
- **前置否决项**：红线用例集必须逐条复现原判定，不得出现新的「静默误判」

## 注意事项

- 遥测**不进 CI 阻断**：会话日志是本机私有路径、粒度不齐（一次任务可能跨多个 rollout）、且含用户等待时间。
- 跨会话直接比轮次不成立（用例数不同）；比较必须固定题目。
- 文档「≤3.5%」是**上限而非预期**：该数字假设文档只读一次，而委外(2) 会话中 `SKILL.md` 被引用 72 次，实际边际贡献更高。
- 若通道对缓存输入不打折，比例结论不变，但绝对成本放大一个数量级——届时「减少重复读取文档」会跃升为主要项。**换通道后请复测一次。**

## 已知缺口（2026-09-22 审查留档 → G1–G6 同日修复；G7 实测新发现并修复）

> 来源：对提交 `e5af606` 的逐文件对抗性审查。**P0-1（exec 输出撑爆 4KB 上限）与
> P0-2（http 判定信号恒为空）已在审查后修复中关闭**，不在此清单内。
> G1–G6 六项 P2 遗留已于同日修复；G7 是当日真机实测时新发现的同类缺陷，一并修复。
> 下面保留原始证据（现象/影响/判定依据）与修复方式，便于回溯当时为什么判定它是缺陷。

### G1 · `page_registry.hits` 双计数

- **现象**：`case_cli._land()` 成功路径调 `record_hit()`（+1），随后 `cmd_exec` 的
  `upsert_page()` 又 +1。实测 `upsert + record_hit + upsert` → `hits=3`，一次 exec 记 +2。
- **影响**：`hits` 是 `render_for_prompt` 展示的字段，会高估页面复用次数；无功能影响。
- **判定依据**：`page_registry.py` 的 `upsert_page` 与 `record_hit` 都做 `hits += 1`。
- **已修**：`hits` 收敛为**单一写入者**——`upsert_page` 不再累加（新建为 0），
  `record_hit` 独占累加，语义定为「验证成功的复用命中次数」。三处把缺陷固化成契约的断言
  （`test_page_registry` ×2、`test_case_cli` ×1）同步纠正，并补「upsert 不涨 / record_hit 才涨」
  两条断言。行为验收：登记 → 命中 → 再登记后 `hits == 1`（原为 3）。

### G2 · `exec` 一次落两份文件

- **现象**：`<run-dir>/cases/<label>.json`（手写全量）与 `<label>.exec.json`
  （`emit` 截断时的 `full_path`）同时存在。
- **影响**：产物目录出现两份近重复文件，读的人可能困惑；不影响正确性。
- **判定依据**：`case_cli.cmd_exec` 显式写 `detail_path`，`_finish → _emit → O.emit` 又写一份。
- **已修**：`output.emit` 新增 `reuse_full=`；`cmd_exec` 把已落盘的 `<label>.json` 路径交给
  emit 复用——截断时不再另写 `<label>.exec.json`，且因 payload 已有 `detail_path` 指向同一文件，
  不再补 `full_path` 键。结果：同一现场只留**一份文件、一个路径键**；未传该参的 recon×4 与
  `bbt_helpers` 行为不变。

### G3 · `measure_context.run_sessions(only_qa=True)` 是死代码

- **现象**：`if only_qa and "qa-skills" not in path: pass` 分支不做任何事。
- **影响**：读代码的人会以为存在"只统计 QA 项目会话"的过滤逻辑，实际没有。
- **判定依据**：`tools/measure_context.py:182`。
- **已修**：`run_sessions` 改为按 rollout 头部 `session_meta.cwd` **真过滤**；cwd 未知的保守
  保留并单独计数（不静默丢数据），输出追加口径行，新增 `--all-sessions` 看全部。该模块原先无
  任何测试，同步补 `tests/test_measure_context.py`（三态判定 + 过滤 + 未知保留）。

### G4 · `qa_skill_common/README.md` 的 `report_gen` 行未更新

- **现象**：README 模块表补了 `output.py` / `page_registry.py` / `case_cli.py`，
  但 `report_gen.py` 那行没提新增的 `conclusions=` 入参。
- **影响**：模块索引与实现略有偏差；`report_gen.py` 与注册表状态机这类文件
  **不在 skills 的预算集合中**（`measure_context` 只覆盖 SKILL.md / references /
  指定必读集），所以预算闸门不会覆盖到这类"索引类文档"的更新遗漏。
- **判定依据**：原改写用的 `str.replace` 锚点未命中且**没有加断言**，于是静默跳过。
- **已修**：README 模块表补全 8 个缺失模块（`api_wait`/`bug_report_schema`/`data_cleanup`/
  `datagrip_datasources`/`env_check`/`fingerprint`/`paths`/`report_gen`）；`check_skill_docs.py`
  增加**双向断言**（漏登记新模块、登记不存在的模块都拦），负例已验证能拦住。
  即「改文档也要断言锚点命中」这一教训，已从经验升级为机械闸门。

### G5 · `ones-create-linked-defect/SKILL.md` 资源列表漏 `qa_case.py`

- **现象**：ones 技能已新增 `scripts/qa_case.py` 入口，但 SKILL 的「资源」清单未列出。
- **影响**：入口存在却无文档指引；不影响已有流程。
- **判定依据**：`grep -c qa_case ones-create-linked-defect/SKILL.md` → 0。
- **已修**：ones SKILL 工作流补一句回归复跑指引（`scripts/qa_case.py exec`/`run`），资源清单
  补 `qa_case.py`。增量 96 字符，含提缺陷组合 33260 / 预算 33500，仍在闸门内。

### G6 · `features.json` 键归一化口径不一致

- **现象**：`page_registry.host_of()` 会把 host 转小写，`goto_feature` 拼 key 时用
  `MES_URL.rstrip("/")` **不转小写**。key 形如 `"<base>|<功能名>"`。
- **影响**：当 `MES_URL` 含大写字母时，注册表写入的 key 与 `goto_feature` 读取的 key
  不一致 → 直达缓存不命中（退化为走搜索，仅慢，不会错）。
- **判定依据**：`page_registry.host_of` 与 `bbt_osd_common.goto_feature` 的 key 拼接。
- **已修**：新增 `page_registry.cache_key()` 作为 key 构造的**唯一入口**（`host_of` 优先、
  裸 host 退化为 lower+rstrip），注册表同步与 `goto_feature` 共用；`goto_feature` 的站点归属比较
  改为大小写不敏感。现有 `.cache/features.json` key 全为小写，**无需迁移**。
  行为验收：大写 host 写入 → 小写 key → `goto_feature` 命中。

### G7 · 未验证的落地会污染直达缓存（2026-09-22 真机实测新发现）

- **现象**：登录失败时 `page.url` 是 oauth 登录跳转页，`upsert_page` 仍无条件调
  `_feature_cache_sync`（只判 URL 非空、不看 verified）→ 写进 `.cache/features.json`；
  而 `goto_feature` 的命中判定是「URL 非 base 即算命中」，于是此后每次都跳到登录页
  **并被当成命中返回**。
- **影响**：一次失败会**永久**污染该功能的直达路径（后续每次都在错页面上跑）。
  存量佐证：本机 `.cache/features.json` 里 `dog` 站点的「委外发料明细」指向 `<host>/home`。
- **判定依据**：`page_registry.upsert_page` 的无条件同步 + `goto_feature` 的弱命中判定。
- **已修**：① `upsert_page` 只在 `verified=True` 时写缓存，未验证时主动 `forget_cache`；
  ② `goto_feature` 改用 `_is_real_landing` 判定（须同站点且非站点根/`/home`/登录授权页），
  命中脏缓存时清除并回退搜索（自愈）；③ 回归测试 `TestDirectCacheTrust`（4 例）。

### G8 · `reset_to` 固定 6s 等待（2026-09-22 真机实测新发现）

- **现象**：`reset_to(page, url, tab_text=None, wait_ms=6000)` 每次用固定 `wait_for_timeout(6000)`。
- **影响**：每条用例白等 6s——实测 3 条用例的截图间隔**精确 6.0s**，白等 18s／占 run 总时长 75%，
  使「批量跑」反而比「逐条 exec」更慢。且违反 SKILL 自身「禁止长固定 sleep」。
- **已修**：改条件等待 `wait_app_ready`（应用外壳出现 → loading 遮罩消失 → 网络短静默）；
  `wait_ms` 仅在显式传入时兜底且封顶 800ms。回归测试 `TestResetToNoFixedSleep`（2 例）。

## 实测对照（2026-09-22，大富 t-dafu，3 条只读用例）

| 组织方式 | 墙钟 | 模型工具调用 | stdout 字符 | token 增量（等效全价） |
| --- | ---: | ---: | ---: | ---: |
| `exec` 逐条 ×3 | 20.4s | 3 | ≈9,030 | +134,701 |
| `run` 批量 ×1（G8 修复前） | 23.9s | 1 | 648 | +47,213 |
| `run` 批量 ×1（G8 修复后） | **12.7s** | 1 | 648 | — |

- **批量化的 token 收益真实**：工具调用 3→1，context 重发次数下降 → 等效全价输入 -65%。
- **批量化单独不够**：必须先修 G8 的固定等待，否则批量比逐条更慢；修复后 23.9s → 12.7s（**-47%**）。
- **冷启动会掩盖复用收益**：`exec` 每轮冷启动 5–7s（登录相关请求约 2.5s），
  跨轮复用省下的毫秒级差异被吞掉——`exec` 的定位应是「探索性单步」，批量走 `run`。

> 测法：`QA_WORKSPACE=/tmp/... MES_URL=http://t-dafu.ob.shuyilink.com \
> python3 web-blackbox-testing/scripts/qa_case.py {exec|run} ...`，
> 用例只做「导航 + `page.title()` 断言 + 读表格」，token 取本会话 rollout 的 `token_count` 差分。

## 13 用例同题复跑（2026-09-22）

题目：大富「生产订单分单计划-月度工序计划」核心 14 条（TC-MPP-001~014 + 前置幂等清理 + 收尾清理）。
方式：`qa_case.py run` **单次批次调用**（持久会话 + 分阶段检查点），脚本见
`runs/2026-09-18_生产订单分单计划-月度工序计划/scripts/run_all_13cases.py`。

| 指标 | 旧基线（2026-09-18） | 本次复跑 | 变化 |
| --- | ---: | ---: | ---: |
| 模型工具调用／轮次 | 347 | **1** | -99.7% |
| 等效全价输入 | 8.65M | **32,346** | -99.6% |
| 墙钟 | 2h20m | **72.8s** | -99.1% |

- 结果：**14/14 通过**；QA 专测数据全部恢复未拆分，残留月度计划 0，历史数据未动。
- **口径提醒（重要）**：上表两侧**并非同等难度**——
  - 旧基线是**端到端从零探索**：需求理解 → 环境勘察 → 写 18 个一次性探针脚本 → 调试 → 造数 → 出报告。
  - 本次是**执行口径**：用例与操作方式由历史资产确定，只测「跑一遍」。
  - 本次写 spec 与调试的总成本（约 625k 等效全价，含 4 次调试跑）**未计入** 32,346。
- 按端到端口径（把写脚本与调试全算上）：约 625k vs 8.65M ≈ **-93%**，仍是数量级差异。

### 复跑暴露的三个真实坑（已固化进 spec）

1. **批量撤销会被「含未拆分分单」整体拦截**——收尾清理必须**逐条判断再撤销**，
   否则一条未拆分就把整批撤销挡住、留下残留（第一版 cleanup 实测踩中）。
2. 月度工序计划接口的日期字段是 `theoryStartTime` / `theoryFinishTime`，**不是** `startTime` / `endTime`。
3. **toast 需轮询抓取**（操作后立即抓常为空）；判定优先用数据变化，toast 仅作辅助
   （与 SKILL「多信号判定」一致）。

