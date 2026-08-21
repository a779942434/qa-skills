# qa_skill_common

本目录是 `web-blackbox-testing` 与 `ones-create-linked-defect` 的**唯一公共实现源**。它集中维护 MES 测试所需的登录、导航、页面侦察、错误监听、数据基线与造数逻辑，避免同一逻辑在两个技能目录中复制后发生漂移。

## 目录职责

| 路径 | 内容 |
| --- | --- |
| `bbt_helpers.py` | 浏览器连接、错误监听、条件等待、表格读取、截图、数据基线与页面结构侦察 |
| `bbt_osd_common.py` | MES 登录、导航、表单/表格辅助与幂等造数函数 |
| `bbt_osd_setup.py` | 产品、工艺路线、工序与 BOM 的一次性造数入口 |
| `recon_generic/` | 页面、弹窗、下拉与主子表的四个参数化侦察命令 |

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
