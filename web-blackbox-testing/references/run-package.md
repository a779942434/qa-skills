# 标准运行包（standard/deep 必读）

一个需求 = 一个运行包，聊天记录只做临时上下文。

```bash
python scripts/qa_case.py init --run-dir <run-dir> --feature <功能> --mode standard --requirement <需求号>
python scripts/qa_case.py oracle --run-dir <run-dir> --requirement R-01 --mode ui --expected "<可判定预期>" --source "<需求出处>" --quote "<原文>"
python scripts/qa_case.py decision --run-dir <run-dir> --requirement R-01 --status confirmed --resolution "<产品口径>"
python scripts/qa_case.py audit --run-dir <run-dir> --strict
python scripts/qa_case.py gaps --run-dir <run-dir> --strict
python scripts/qa_case.py report --run-dir <run-dir>
```

`audit` 退出码：0=通过，1=质量缺口，2=结构损坏。
`gaps --strict` 退出码：0=ready，1=仍有阻塞缺口；它回答“还有什么没测/没通过/证据过期”，不等同于 audit 的结构门禁。
`init --from-cases` 可导入完整 `coverage.json` sidecar（requirements/cases/invariants/exclusions/decisions），也可继续导入纯 cases 数组。

## 文件职责

| 文件 | 作用 |
|---|---|
| `manifest.json` | 运行范围、模式、环境快照、工具采纳、状态 |
| `contract.json` | 需求条款、原文引用、状态、判定依据（oracle）、数据依赖、产品决策 |
| `coverage.json` | 需求点→风险→用例→不变量；排除项必须写理由 |
| `evidence/index.json` | UI/API/DB/下游/replay 证据、关联用例/缺陷、哈希、需求版本/环境快照/数据批次绑定 |
| `defects.json` | 唯一缺陷主账：分类、置信度、复现、证据ID、ONES状态 |
| `run_state.json` / `data_ledger.json` | 用例检查点、数据台账和清理状态 |
| `judgements.jsonl` | `qa_action` 判定埋点，adoption 的客观依据 |
| `conclusions.json` | 业务结论；报告从这里重新渲染，不手写正文 |

## 判定纪律

- `implementation_defect` 才能进入 ONES；`requirement_risk`、`environment_blocked`、`test_artifact` 分别进入决策、阻塞、脚本问题台账。
- 每条 `R-xx` 必须有 `oracle.mode` + `oracle.expected` 才能自动判缺陷；口径未定时用 `decision` 记录 `open/pending`，确认后写 `confirmed/approved/resolved`。
- P0/P1 缺陷至少两个证据通道，或显式声明 `allow_single_channel=true` 的确定性 API/SQL 复现。
- 正式缺陷必须有需求引用、证据ID、2/2 或确定性接口复现。
- 证据自动绑定当前需求版本、环境快照和数据批次；需求/环境/批次变化后，旧证据会被 `gaps` 标为 `stale`，不能继续当作通过依据。
- 旧运行目录缺少新文件时按 legacy 只读兼容；不要为了审计回填伪造数据。

## gaps 分类

- `empty_scope`：空合同或空用例集，直接视为未就绪；
- `missing_oracle`：需求没有可执行判定依据；
- `missing_oracle_evidence`：oracle 要求的证据通道未满足；
- `pending_decision`：待产品/业务确认，决策仍 open/pending，或决策/豁免已过期；
- `not_run` / `uncovered`：未执行或明确未覆盖；
- `blocked_env` / `blocked_data` / `blocked_other`：环境、数据或其他阻塞；
- `failed_cases`：失败待修复/复验；
- `missing_evidence`：执行过但缺证据；
- `stale_evidence` / `unbound_evidence`：证据已过期，或未绑定版本/环境；
- `waived`：有明确原因和来源的豁免，不阻断 ready。

