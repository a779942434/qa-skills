# ONES 技能脚本边界

本目录只放**可复用入口**和它们依赖的库。排查问题时临时写的脚本，任务结束后要么泛化成
入口，要么删除；不要留成 `close_2086xx.py`、`debug_xxx.py` 这类一次性文件。

## 入口

| 脚本 | 用途 |
| --- | --- |
| `check_env.py` | 环境自检（CDP、浏览器、登录态） |
| `ones_bootstrap.py` | 首次准备常驻浏览器 |
| `ones_edge_server.py` / `edge_session_setup.py` | 启动/监管常驻 Edge 与登录态 |
| `ones_project_setup.py` | 新项目字段/选项发现，写入 profile |
| `ones_submit_defects.py` | 缺陷清单批量提交（Phase A / Phase B / 校验） |
| `ones_backfill_evidence.py` | 已有缺陷单的附件与描述图回填 |
| `qa_case.py` | 单用例 / 批次回归闭环 |

`ones_helpers.py`、`ones_submission.py`、`ones_config.py`、`qa_case.py` 同时作为库被入口导入；
`qa_skill_common/` 是仓库公共实现的副本，由根目录 `vendor-common.sh` 生成，**不要手改**。

## 写新入口的门槛

1. 至少被 `SKILL.md`、`references/` 或测试引用；否则 `tools/check_skill_integrity.py` 会判失败。
2. 不写死客户名、真实姓名、ONES team/task UUID、本机绝对路径；这些放
   `config/field-mapping.local.yaml`（已 gitignore）或命令行参数。
3. 新逻辑优先加进现有入口的参数/函数；确实需要独立入口时，在 `SKILL.md` 的资源段登记。
4. 改动后跑：

```bash
python3 -m unittest discover -s ones-create-linked-defect/scripts/tests -v
python3 tools/check_skill_integrity.py
python3 tools/check_install.py
```
