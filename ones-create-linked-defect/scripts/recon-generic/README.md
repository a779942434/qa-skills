# 通用页面侦察工具（Element UI / 数益 MES）

从已测页面（订单周期定义表、产品信息定义、工艺路线定义等）抽出的通用侦察脚本。
前端组件大部分通用，以下脚本用 `--url` 参数化，任意同框架页面都能复用。

依赖：`../bbt_osd_common.py`（登录/导航/下拉/表格公共辅助）。

## 用法

```bash
python recon_page.py --url <页面URL>                          # 页面整体：按钮/表头/行/弹窗
python recon_dialog.py --url <页面URL> --button 新增           # 打开按钮后 dump 弹窗字段结构
python recon_dropdown.py --url <页面URL> --button 新增         # dump 弹窗第一个下拉的可见选项
python recon_subtables.py --url <页面URL> --max-rows 5        # 点击每行主表行，dump 出现的子表
```

登录与环境：不再写死 t-ousida。登录会自动按 `--url` 所在站点走 Keycloak；账号密码可用环境变量覆盖：
- `MES_URL`：被测站点根地址（未设置时自动取 `--url` 的根地址）
- `MES_ACCOUNT` / `MES_PASSWORD`：登录账号/密码（未设置会报明确提示）
（兼容入口 `login_ousida` 名称保留，行为已环境无关化。）
- 浏览器启动：优先 playwright 自带 chromium；缺失时自动回退本机系统 Chrome/Edge（可用 `MES_BROWSER_PATH` 指定可执行文件）。

## 通用要点（已在 common 固化）

- 树展开：先点父节点再点目标系列。
- 点击主表行 → 出现子表（主子表通用交互）。
- 子表新增/按钮通常是第 2 个「新增」。
- 弹窗字段用 form-item 索引定位（label 可能带序号，如「产品名称2」）。
