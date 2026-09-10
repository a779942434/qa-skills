# 环境与前置配置总表（web-blackbox-testing / ones-create-linked-defect 通用）

> 本文件是环境变量与配置文件的**唯一总表**。首次使用先跑自检：
>
> ```bash
> python scripts/check_env.py          # web-blackbox-testing（含浏览器/站点/账号）
> python scripts/check_env.py          # ones-create-linked-defect（含 Edge/登录态/CDP/清单目录）
> ```

## 一、前置清单（先确认这三样）

| 前置 | 说明 | 缺失时的修复 |
| --- | --- | --- |
| Python 依赖 | `playwright`、`pyyaml` | `pip install playwright pyyaml` |
| 系统浏览器 | Chrome / Edge（**禁止下载浏览器**） | 安装 Chrome/Edge；或用 `MES_BROWSER_PATH` 指定路径 |
| 被测站点账号 | 能登录目标 MES 的账号 | 见下方 `MES_ACCOUNT` / `MES_PASSWORD` |

> ⚠️ 只允许 `pip install playwright`（装 Python 包），**不要**执行 `playwright install`（会下载浏览器，技能明确禁止）。

## 二、环境变量总表

| 分组 | 变量 | 必填 | 默认 / 示例 | 用途 |
| --- | --- | --- | --- | --- |
| 被测站点 | `MES_URL` | 建议 | `http://<你的测试站点>` | 被测 MES 站点根地址；不设时部分命令可用 `--url` 推导 |
| 被测站点 | `MES_ACCOUNT` | 是 | `admin` | Keycloak 登录账号 |
| 被测站点 | `MES_PASSWORD` | 是 | —— | Keycloak 登录密码 |
| 被测站点 | `MES_BROWSER_PATH` | 否 | 自动探测系统 Chrome/Edge | 指定浏览器可执行文件 |
| IPC | `IPC_BASE_URL` | 否 | `http://<你的测试站点>` | IPC 单机/产线界面站点；不设时须显式传 `base_url` |
| 数据库 | `DB_PASSWORD_<数据源名>` | 否 | 名称转大写、非字母数字转 `_` | 单个数据源的密码（最高优先级） |
| 数据库 | `DATAGRIP_CREDENTIALS_FILE` | 否 | `~/.codex/credentials/databases.yaml` | 自定义凭据文件路径 |
| 数据库 | `DATAGRIP_PROJECTS_DIR` | 否 | `~/DataGripProjects` | DataGrip 项目级数据源扫描根 |
| ONES | `ONES_CDP_PORT` | 否 | `9334` | 常驻 Edge 的 CDP 调试端口 |
| ONES | `ONES_URL` | 否 | `https://ones.<你的域名>` | ONES 站点地址 |
| ONES | `ONES_EDGE_EXE` | 否 | 自动探测 | Edge 可执行文件 |
| ONES | `ONES_EDGE_SESSION` | 否 | `~/.codex/tmp/edge-ones-session` | 复制登录态后的会话目录 |
| ONES | `ONES_EDGE_USER_DATA` | 否 | 自动探测本机 Edge | 登录态来源目录 |
| ONES | `ONES_LOGS_DIR` | 否 | `<会话目录>/logs` | 常驻浏览器日志目录 |
| ONES | `ONES_BUG_REPORTS_DIR` | 否 | `<技能目录>/bug-reports` | 本地缺陷清单目录 |
| 通用 | `OUT_DIR` | 否 | 当前目录 | 测试脚本输出目录 |

> 环境变量优先级：**环境变量 > `config/settings.yaml` > 平台默认值**。

## 三、配置文件

| 文件 | 作用 | 是否入库 |
| --- | --- | --- |
| `config/settings.yaml` | ONES 环境/浏览器配置（路径留空自动探测） | 是（通用模板） |
| `config/field-mapping.yaml` | 缺陷字段映射（通用模板） | 是（不含客户数据） |
| `config/field-mapping.local.yaml` | 真实项目/人员/字段 uuid | 否（本机，已 gitignore） |
| `scripts/config/databases.yaml` | DataGrip 无密码模板 | 是（不含真实凭据） |
| `~/.codex/credentials/databases.yaml` | 本机数据库凭据 | 否（不在技能内） |

## 四、常见报错对照

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `playwright ... 与本机系统 Chrome/Edge 均不可用` | 无浏览器 / 沙箱限制 | 装 Chrome/Edge 或设 `MES_BROWSER_PATH`；沙箱内请用非沙箱权限 |
| `未配置被测站点：请设置环境变量 MES_URL` | 缺 `MES_URL` | `export MES_URL=...` 或命令传 `--url` |
| `未配置登录账号：请设置环境变量 MES_ACCOUNT 与 MES_PASSWORD` | 缺账号 | `export MES_ACCOUNT=... MES_PASSWORD=...` |
| `未配置 IPC 站点：请设置环境变量 IPC_BASE_URL` | 缺 IPC 站点 | `export IPC_BASE_URL=...` 或传 `base_url=...` |
| ONES 每次都跳登录 | 登录态未复制/已过期 | 跑 `python scripts/ones_bootstrap.py --apply`（首次加 `--visible` 完成 SSO） |

## 五、一次性配齐（示例）

```bash
export MES_URL="http://<你的测试站点>"
export MES_ACCOUNT="admin"
export MES_PASSWORD="<密码>"
export IPC_BASE_URL="$MES_URL"
python scripts/check_env.py
```
