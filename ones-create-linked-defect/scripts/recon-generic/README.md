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

登录：默认 admin / sygl123456（t-ousida Keycloak），在 `bbt_osd_common.py` 里改。

## 通用要点（已在 common 固化）

- 树展开：先点父节点再点目标系列。
- 点击主表行 → 出现子表（主子表通用交互）。
- 子表新增/按钮通常是第 2 个「新增」。
- 弹窗字段用 form-item 索引定位（label 可能带序号，如「产品名称2」）。
