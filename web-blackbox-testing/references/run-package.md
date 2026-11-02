# 标准运行包（standard/deep 必读）

一个需求 = 一个运行包，聊天记录只做临时上下文。

```bash
python scripts/qa_case.py init --run-dir <run-dir> --feature <功能> --mode standard --requirement <需求号>
python scripts/qa_case.py audit --run-dir <run-dir> --strict
python scripts/qa_case.py report --run-dir <run-dir>
```

`audit` 退出码：0=通过，1=质量缺口，2=结构损坏。

## 文件职责

| 文件 | 作用 |
|---|---|
| `manifest.json` | 运行范围、模式、环境快照、工具采纳、状态 |
| `contract.json` | 需求条款、原文引用、状态、产品决策 |
| `coverage.json` | 需求点→风险→用例→不变量；排除项必须写理由 |
| `evidence/index.json` | UI/API/DB/下游/replay 证据、关联用例/缺陷、哈希 |
| `defects.json` | 唯一缺陷主账：分类、置信度、复现、证据ID、ONES状态 |
| `run_state.json` / `data_ledger.json` | 用例检查点、数据台账和清理状态 |
| `judgements.jsonl` | `qa_action` 判定埋点，adoption 的客观依据 |
| `conclusions.json` | 业务结论；报告从这里重新渲染，不手写正文 |

## 判定纪律

- `implementation_defect` 才能进入 ONES；`requirement_risk`、`environment_blocked`、`test_artifact` 分别进入决策、阻塞、脚本问题台账。
- P0/P1 缺陷至少两个证据通道，或显式声明 `allow_single_channel=true` 的确定性 API/SQL 复现。
- 正式缺陷必须有需求引用、证据ID、2/2 或确定性接口复现。
- 旧运行目录缺少新文件时按 legacy 只读兼容；不要为了审计回填伪造数据。

