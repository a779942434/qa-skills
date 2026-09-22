# QA Skills（Codex 技能集）

面向生产制造 / MES 系统的测试全流程 Codex 技能集合，串成一条
「测试用例生成 → 黑盒测试 → 缺陷录入流转」的完整链路。

## 技能列表

| 目录 | 技能 | 作用 |
| --- | --- | --- |
| `generate-manufacturing-test-cases/` | 制造类测试用例生成 | 基于 PRD / 流程图 / 补充规则生成结构化功能测试用例 |
| `web-blackbox-testing/` | Web 黑盒测试 | 无源码场景下黑盒测试 / 冒烟 / 回归验证，产出缺陷清单 |
| `ones-create-linked-defect/` | ONES 缺陷全流程 | 把缺陷清单录入 ONES、回归后关闭 / 评论 @处理人、流转主工单 |
| `qa_skill_common/` | 跨技能公共实现（开发源） | 唯一来源；由 `vendor-common.sh` 内置到各技能，不单独分发 |
| `generate-arun-api-scripts/` | ARun 接口脚本生成 | 从 OpenAPI/Swagger + 业务流程生成可粘贴到 ARun 的接口脚本 JSON |

## 完整链路

```
制造类测试用例生成 → Web 黑盒测试 → 缺陷清单 → ONES 提缺陷 → 回归 → 关闭/评论 → 主工单流转
```

## 安装

每个技能**自带所需实现，可独立安装**：Codex 按目录下的 `SKILL.md` 识别技能，把技能目录复制到技能目录即可，**无需另行安装公共包**：

```bash
cp -R web-blackbox-testing ~/.codex/skills/
cp -R ones-create-linked-defect ~/.codex/skills/
cp -R generate-manufacturing-test-cases ~/.codex/skills/
cp -R generate-arun-api-scripts ~/.codex/skills/
```

- `web-blackbox-testing`、`ones-create-linked-defect` 内已内置公共实现包（`scripts/qa_skill_common/`），**单独装其中一个也能跑**。
- 仓库根的 `qa_skill_common/` 是**开发源**，不随技能分发；改动后由 `./vendor-common.sh` 生成到各技能（见下）。

## 同步到 Codex 技能库（必做）

Codex 实际加载 `~/.codex/skills/` 下的独立副本，与仓库**不同步**。改完仓库后执行一次即可让 Codex 用上新版本：

```bash
./sync-skills.sh            # 正式同步
./sync-skills.sh --dry-run  # 只预览不执行
./sync-skills.sh --purge    # 同步并删除目标侧「仓库没有」的文件（白名单除外）
./sync-skills.sh --dry-run --purge  # 先预览将删除的文件
```

- 同步目录：`web-blackbox-testing/`、`ones-create-linked-defect/`、`generate-manufacturing-test-cases/`、`generate-arun-api-scripts/`（各技能已自带公共包）
- 保留目标侧本地文件（如 `scripts/config/databases.yaml`），不会误删；目标目录可用 `CODEX_SKILLS_DIR` 覆盖
- 需要沙箱外权限（写入 `~/.codex/skills`）

## 提速底座与闸门（2026-09-22）

实测会话成本 ≈ `轮次 × 平均 context`：大富会话 347 轮 / 84.47M 输入（缓存 99.7%），
其中 **65% 的轮次花在脚本往返、85% 的 context 增长来自工具输出**。为此加了三条底座：

- **单用例/批次闭环**：`python scripts/qa_case.py exec|run|status|report|pages`
  —— 一次调用跑一批、stdout 只回单行 JSON（≤4KB），完整现场落 `<run-dir>/cases/`。
- **输出限长契约**：`qa_skill_common/output.py` 的 `emit()`。**判定字段永不截断**
  （截断会把「有 toast 的拦截」误判成「静默无反馈」，历史上真出过这个误报）；
  观察字段按上限截断并给出 `counts` / `full_path`。
- **站点注册表**：`<产物根>/sites/<host>.json`，跨会话复用直达 URL / 等待接口 / 选择器 / 坑。
  两级可信度（`verified` 才允许直接 goto）+ 一致性校验（标题或组件库判定不一致即降级重侦察）。

**闸门**（防止瘦身之后又长回去）：

```bash
python3 tools/measure_context.py             # 字符代理口径（各场景必读量 + 预算对比）
python3 tools/measure_context.py --check     # 超预算即非零退出
python3 tools/measure_context.py --sessions  # 真实遥测：轮次/输入/缓存/输出/等效全价输入
python3 tools/check_skill_docs.py            # 断言红线条数 + 每条动作动词 + 结构锚点
```

`sync-skills.sh` 前置会跑上下文预算与文档闸门；`vendor-common.sh --check` 会追加
`qa_skill_common` 离线单测。基线数据与验收目标见 `tools/baseline.md`。

## 公共实现包（qa_skill_common）

`web-blackbox-testing` 与 `ones-create-linked-defect` 共用同一套浏览器/登录/侦察实现。为避免两份代码漂移，仓库只在根目录 `qa_skill_common/` 维护**唯一来源**，再由脚本内置到各技能：

```bash
./vendor-common.sh          # 生成/更新各技能内的 scripts/qa_skill_common/
./vendor-common.sh --check  # 校验副本是否与源头一致（提交前 / CI）
```

- `sync-skills.sh` 会在正式同步前自动执行一次 `vendor-common.sh`，所以日常改技能代码无需手动调用。
- 只有当你**新增/修改了 `qa_skill_common/` 里的公共实现**时，才需要关注这一步；改完运行 `./vendor-common.sh` 再提交即可。
- 各技能内的 `scripts/qa_skill_common/` 是**生成产物，请勿手改**。

## 知识库归档

测试产出按日期归档到 `knowledge-base/`：
- `knowledge-base/test-reports/`：测试报告
- `knowledge-base/bug-reports/`：缺陷清单 + 证据截图
- `knowledge-base/notes/`：可复用经验（页面路径、业务规则、稳定交互、接口等待用法；不含账号密码/Token）

## 注意事项

- `ones-create-linked-defect/config/field-mapping.yaml` 是通用模板（不含客户数据）；真实的项目、人员、字段 uuid 等配置放在本机 `config/field-mapping.local.yaml`（已 gitignore，不随仓库分发）。
- `--purge` 会删除目标侧仓库没有的文件，但保留本地运行时文件（`databases.yaml`、`bug-reports/`、`test-reports/`、`field-mapping.local.yaml` 等），使用前建议先 `--dry-run --purge` 预览。
- 数据库凭据、浏览器登录会话等敏感信息不在本仓库内（放在本机 `~/.codex/` 下），请勿提交。
