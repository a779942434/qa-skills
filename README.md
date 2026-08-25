# QA Skills（Codex 技能集）

面向生产制造 / MES 系统的测试全流程 Codex 技能集合，串成一条
「测试用例生成 → 黑盒测试 → 缺陷录入流转」的完整链路。

## 技能列表

| 目录 | 技能 | 作用 |
| --- | --- | --- |
| `generate-manufacturing-test-cases/` | 制造类测试用例生成 | 基于 PRD / 流程图 / 补充规则生成结构化功能测试用例 |
| `web-blackbox-testing/` | Web 黑盒测试 | 无源码场景下黑盒测试 / 冒烟 / 回归验证，产出缺陷清单 |
| `ones-create-linked-defect/` | ONES 缺陷全流程 | 把缺陷清单录入 ONES、回归后关闭 / 评论 @处理人、流转主工单 |
| `qa_skill_common/` | 跨技能公共实现 | 集中维护浏览器辅助、MES 登录/造数与通用页面侦察，供后两个技能复用 |

## 完整链路

```
制造类测试用例生成 → Web 黑盒测试 → 缺陷清单 → ONES 提缺陷 → 回归 → 关闭/评论 → 主工单流转
```

## 安装

Codex 按目录下的 `SKILL.md` 识别技能，把各技能目录复制到技能目录即可：

```bash
cp -R generate-manufacturing-test-cases ~/.codex/skills/
cp -R qa_skill_common ~/.codex/skills/
cp -R web-blackbox-testing ~/.codex/skills/
cp -R ones-create-linked-defect ~/.codex/skills/
```

## 同步到 Codex 技能库（必做）

Codex 实际加载 `~/.codex/skills/` 下的独立副本，与仓库**不同步**。改完仓库后执行一次即可让 Codex 用上新版本：

```bash
./sync-skills.sh            # 正式同步
./sync-skills.sh --dry-run  # 只预览不执行
./sync-skills.sh --purge    # 同步并删除目标侧「仓库没有」的文件（白名单除外）
./sync-skills.sh --dry-run --purge  # 先预览将删除的文件
```

- 同步目录：`web-blackbox-testing/`、`qa_skill_common/`、`ones-create-linked-defect/`、`generate-manufacturing-test-cases/`
- 保留目标侧本地文件（如 `scripts/config/databases.yaml`），不会误删；目标目录可用 `CODEX_SKILLS_DIR` 覆盖
- 需要沙箱外权限（写入 `~/.codex/skills`）

## 知识库归档

测试产出按日期归档到 `knowledge-base/`：
- `knowledge-base/test-reports/`：测试报告
- `knowledge-base/bug-reports/`：缺陷清单 + 证据截图
- `knowledge-base/notes/`：可复用经验（页面路径、业务规则、稳定交互、接口等待用法；不含账号密码/Token）

## 注意事项

- `ones-create-linked-defect/config/field-mapping.yaml` 是通用模板（不含客户数据）；真实的项目、人员、字段 uuid 等配置放在本机 `config/field-mapping.local.yaml`（已 gitignore，不随仓库分发）。
- `--purge` 会删除目标侧仓库没有的文件，但保留本地运行时文件（`databases.yaml`、`bug-reports/`、`test-reports/`、`field-mapping.local.yaml` 等），使用前建议先 `--dry-run --purge` 预览。
- 数据库凭据、浏览器登录会话等敏感信息不在本仓库内（放在本机 `~/.codex/` 下），请勿提交。
