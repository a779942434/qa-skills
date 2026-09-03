# qa_skill_common

本目录是 `web-blackbox-testing` 与 `ones-create-linked-defect` 的**唯一公共实现源**。它集中维护 MES 测试所需的登录、导航、页面侦察、错误监听、数据基线与造数逻辑，避免同一逻辑在两个技能目录中复制后发生漂移。

## 目录职责

| 路径 | 内容 |
| --- | --- |
| `bbt_helpers.py` | 浏览器连接、错误监听、条件等待、表格读取、截图、数据基线与页面结构侦察 |
| `bbt_osd_common.py` | MES 登录、导航、表单/表格辅助与幂等造数函数 |
| `bbt_osd_setup.py` | 产品、工艺路线、工序与 BOM 的一次性造数入口 |
| `recon_generic/` | 页面、弹窗、下拉与主子表的四个参数化侦察命令 |

## 环境配置（站点/账号不再写死）

`bbt_osd_common` 不再把目标环境写死为 t-ousida，全部改为环境变量配置（留空即未配置，调用时会报明确提示）：

| 环境变量 | 含义 | 示例 |
| --- | --- | --- |
| `MES_URL` | 被测 MES 站点根地址 | `http://t-dafu.ob.shuyilink.com` |
| `MES_ACCOUNT` | Keycloak 登录账号 | `admin` |
| `MES_PASSWORD` | Keycloak 登录密码 | 依环境而定 |

说明：
- `login_ousida(page, base_url=...)` 可传参指定站点；`recon-generic/*.py` 会自动按 `--url` 所在站点登录，未配置 `MES_URL` 也能用。
- `login_for_page(page, target_url)`：优先 `MES_URL`，否则取目标页面根地址登录。
- 兼容入口 `login_ousida` 名称保留，行为已环境无关化。

## 兼容约定

各技能原有的 `scripts/bbt_helpers.py`、`scripts/bbt_osd_common.py`、`scripts/bbt_osd_setup.py` 和 `scripts/recon-generic/*.py` 均保留为**兼容入口**。既有命令和导入语句无需修改，例如：

```bash
python web-blackbox-testing/scripts/recon-generic/recon_page.py --url <页面URL>
python ones-create-linked-defect/scripts/bbt_osd_setup.py
```

新功能和修复应只提交到本目录；除非需要增加或调整兼容入口，不应在两个技能目录中重复修改实现代码。

## 安装

共享包必须与两个技能目录保持同一父目录。建议直接复制整个仓库，或在按目录安装时一并复制 `qa_skill_common/`：

```bash
cp -R qa_skill_common ~/.codex/skills/
cp -R web-blackbox-testing ~/.codex/skills/
cp -R ones-create-linked-defect ~/.codex/skills/
```
