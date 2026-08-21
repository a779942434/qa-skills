# IPC 单机/产线界面与交接班参考

适用：3.0 测试环境（如 `dog.ob.shuyilink.com`），需求需要在工控机（IPC）界面里操作
「单机界面」或「产线界面」。**入口不要用首页搜索框**，按功能管理菜单进入。

## 开工前向用户索取的信息

开始 IPC 相关测试前，主动向用户确认并在报告头记录：

- **工控机解锁密码（系统密码）**：用于 `/ipc/setting` 解锁；未提供时默认使用 `123456`，
  并在报告头记录实际使用的解锁密码。
- **工控机站点**：单机界面 / 产线界面分别对应不同站点；用户未给出时，
  可从「请选择站点」下拉中随机选一个匹配类型的测试站点，并在报告头注明实际所选站点。
- **刷卡卡号**：换班、上班、下班等刷卡操作使用；用户未给出时默认按 `1`。
  卡号不是固定值，实际以用户提供的为准。

## 标准进入步骤

1. 登录首页 `/home`。
2. 左侧功能管理菜单里，点击精确文本 `业务流程`
   （`li.el-menu-item` 含文本 `业务流程`）。
3. 右侧功能卡片区点击精确文本卡片 `单机界面` 或 `产线界面`
   （卡片容器 `div.cursor-pointer`；必须精确匹配，避免误点 `测试单机界面`）。
4. 系统会打开 IPC 应用。首次或未配置时落到 `/ipc/setting`
   （系统设置 / 解锁页）。目标路由：单机 `/ipc/single`，产线 `/ipc/line`。

## 首次进入 / 换站点时

5. 输入系统密码（由当轮测试需求提供，不写死进 skill），点「解锁」，等待“解锁成功”提示。
6. 点「请选择站点」下拉，精确选择需求指定的站点；
   **不要用前缀匹配**，避免把 `...站点1` 选成 `...站点13`。
7. 点「保存配置」。
8. 弹出「站点配置成功，需要刷新系统后生效」后点「确认」；
   该“确认”可能不是标准 `button`，用文本定位并按需 `force` 点击。
9. 页面进入 IPC 首页 `/ipc`。可用功能卡片随所选站点不同而不同：
   - 单机站点通常出现「单机界面」；
   - 产线站点通常出现「产线界面 / 多设备界面 / 单机界面」。
10. 在 IPC 首页点击精确文本 `单机界面` 或 `产线界面`
    （卡片 `div.w-[105px]...`），分别进入：
    - 单机：`/ipc/single`
    - 产线：`/ipc/line`

## 自动化选择器与关键坑

- IPC 是微前端 / iframe，页面可能同时存在两个相同 URL 的 frame；
  先找到包含目标文本或按钮的 frame，再在该 frame 内操作，不要默认只操作主 frame。
- 解锁按钮：`button:has-text("解锁")`；密码框：`input[type=password][placeholder="请输入密码"]`。
- 站点下拉触发：文本 `请选择站点`；选项：`get_by_text("<站点名>", exact=True)` 或可见 `li` 精确文本。
- 保存：`button:has-text("保存配置")`；确认：文本 `确认`。
- IPC 首页入口：精确文本 `单机界面` / `产线界面` 的
  `div.w-[105px].my-[10px]...` 卡片。
- 若直接访问 `/ipc/single` 或 `/ipc/line` 被重定向到 `/ipc/setting` 或 `/ipc`，
  说明尚未解锁 / 未选站 / 未保存配置，先补第 5–8 步。

## 落地页结构（用于生成测试用例与核对断言）

- 单机界面 `/ipc/single`：设备/工单信息、上下料批次明细、待处理异常，
  以及操作按钮（开机、采集产量、采集报废、标准节拍、实时节拍、料池投料、
  工艺报警、变化点管理、开班点检、计划切换、打标异常、交接班、刀具更换、
  扫码换模、重新上挂、人员呼叫、质检取样）。
- 产线界面 `/ipc/line`：产线/上班人员/生产订单汇总、上下料批次明细、
  待处理异常、多工位设备卡片、底部「产线交接班」「计划切换」。

## 交接班操作（单机界面）

> 本节以交接班为例，用于沉淀「如何定位元素、如何操作」；实际测试范围仍以当轮需求为准，不要照搬业务结论。

前置：已进入 `/ipc/single`，页面底部「交接班」入口点击后弹出交接班信息弹窗。

### 弹窗结构

- 班次选择区：`请选择班次` 标题，下方为 `.shift-item` 卡片；
  每个卡片含 `.name`（早班/晚班）、`.range`（时间段）、`.period-date`（班次日期）。
- 换班按钮：`.shift-btn`。
- 打卡信息表：表头为 序号 / 姓名 / 上班时间 / 下班时间 / 班次 / 操作；
  行内「上班」「下班」按钮按当前记录状态出现。
- 弹窗顶部还有一个 `button.start-work-btn`（文本「上班」），
  仅当当前班次下没有未完成打卡记录时可点击。

### 刷卡模拟（固定规则）

- 刷卡层直接读取键盘，页面不会出现卡号输入框。
- 卡号按用户提供的输入；用户未提供时默认输入 `1`。**不要按回车**。
- 若输入卡号后页面没有反应：按 `F12` → `Application` → `Storage` → `Local Storage`，
  找到当前站点，在左侧新增参数 `card_mock`，值为 `1`，再重新刷卡。
- 自动化等价操作：进入 IPC 页面后执行
  `page.evaluate("() => localStorage.setItem('card_mock','1')")`，
  或调用 `ipc_helpers.set_card_mock(page, "1")`。
- 若卡号匹配到多人，会出现「代刷 / 首字母筛选」人员选择弹窗；
  选中目标人员行（如 `tr` 含姓名）再点「确认」。

### 关键用例路径

以下示例按缺省卡号 `1` 编写；实际执行时替换为用户提供的卡号。

| 路径 | 操作 | 预期结果 |
| --- | --- | --- |
| 下班打卡 | 当前打卡行下班时间为 `--` 时，点行内「下班」→ 刷卡 `1` | 出现「下班成功」，该行下班时间被补齐 |
| 未下班拦截换班 | 当前班次存在下班时间为空的打卡记录，选目标班次点「换班」→ 刷卡 `1` | 出现「人员未下班完成,无法切换班次」和「提交错误报告」，班次不变 |
| 正常换班 | 当前班次打卡记录均已下班后，选目标班次点「换班」→ 刷卡 `1` | 出现「换班成功」，目标班次变为当前班次，打卡表刷新 |
| 上班打卡 | 当前班次打卡表为空时，点 `button.start-work-btn` → 刷卡 `1` → 如有人员选择则选人确认 | 打卡表新增记录：上班时间已填、下班时间 `--`、操作「下班」 |

上班打卡后可能弹出「送检提醒」，按需求关闭或处理，不影响交接班主流程。

## 产线计划切换弹窗（产线界面-AL / 计划切换，2026-08-21 固化）

入口：产线界面 `/ipc/line` 底部「产线计划切换」（注意不是「计划切换」入口，
AL 定制版还有设备级「计划切换」；本功能用「产线计划切换」）。
点击后打开自定义弹窗组件 `.production-line-plan-switch-dialog`（非 el-dialog）。

### 弹窗结构
- 页签：`.tab-item`（待用计划 / 当前计划 / 暂停计划），**默认激活「当前计划」**。
- 统计：`.total-count`（共计 N 条记录）、`.selected-count`（您已经选中了 N 条记录）。
- 列表：`.content-list > .content-item`（卡片式，非 el-table）；每卡片含
  `.checkbox-wrapper .el-checkbox` 与 `.item-content`（字段 label/value）。
  当前/暂停计划卡片字段含「工单编号」（位置靠后），待用计划卡片含「工单编号」。
- 操作按钮：`.action-button`（div，非 button 标签），未选中时带 `disabled` class。
  - 待用计划页签：刷新 / 切换历史 / 计划切换
  - 当前计划页签：刷新 / 切换历史 / 卸载计划 / 暂停计划
  - 暂停计划页签：刷新 / 暂停重启历史 / 重启计划 / 卸载计划

### 稳定交互方式（代理/headless 下实测）
- 页签切换：`el.dispatchEvent(new MouseEvent('click', {bubbles:true}))` 有效；
  Playwright 原生坐标 click 可能被常驻「异常上报(自动)」弹窗遮挡而超时。
- 卡片选中：优先点击卡片内 `.el-checkbox`（`card.querySelector('.el-checkbox').click()`）；
  直接点 `.content-item` 偶发不触发（selected 不更新）。
- 操作按钮：`.action-button` 上执行 `btn.click()`。
- 常驻遮挡：页面存在「异常上报(自动)」弹窗（测试造数产生），会拦截坐标点击；
  自动化前可先移除：`[...document.querySelectorAll('[class*=dialog]')].filter(e=>e.innerText.includes('异常上报')).forEach(e=>e.remove())`。
- 刷卡：点按钮后轮询页面文本出现「请在右下角刷您的工卡」再 `page.keyboard.type("1")`。

### 接口等待（替代固定 sleep）
切页签/打开弹窗/刷卡提交后，不要固定 wait 8~10s，用 `scripts/api_wait.py`：
操作前 `base = watcher.snapshot()`，操作后 `new = watcher.wait_new(base, timeout=15)`，
等新接口返回后再读 `.content-item` / `.total-count` / toast。


## 计划切换弹窗交互纪律（2026-08-21 重测增补）

实测发现：弹窗为 Vue 自定义组件，自动化交互存在以下坑，必须遵守：

1. **页签切换**：先用 active class 读当前激活页签，**目标页签已激活则不重复点击**（重复点击已激活页签会导致内容错乱，显示其它页签数据）；未激活时用
   `el.dispatchEvent(new MouseEvent('click', {bubbles:true}))` 切换。
2. **切换后必须等「目标数据特征」**：等 content-list 出现目标工单编号或预期卡片数（轮询 `card_texts()`），**禁止固定 sleep**；
   等不到说明接口未返回或状态错乱，按失败处理，不硬读。
3. **卡片选中用多方式重试**：优先 `card.querySelector('.el-checkbox').click()`，失败换 Playwright `force click` 卡片/checkbox；
   **每次尝试后验证 `.selected-count` 变为「1 条」才继续**，最多 3~6 次，仍失败即判失败。
4. **「刷新」按钮可能使内容不可控**：页签数据异常时优先「切走再切回」或改用接口只读核验，慎用刷新。
5. **操作成功判定以数据状态变化为准**：计划切换/暂停/重启/卸载成功后，目标页签的卡片集合应变化（如切换后原当前计划自动进入暂停页签）；
   toast（切换成功/暂停成功等）仅作辅助，不作为唯一判定。

代码骨架（健壮选中）：
```python
def select_card_robust(ipc, gd, attempts=6):
    for _ in range(attempts):
        info = card_texts(ipc)
        idx = next((i for i, c in enumerate(info["cards"]) if f"工单编号: | {gd}" in c), -1)
        if idx < 0:
            return False
        # 方法A checkbox JS click
        ipc.frames[0].locator(".production-line-plan-switch-dialog").first.evaluate(
            "(i)=>{const it=[...document.querySelectorAll('.production-line-plan-switch-dialog .content-item')];"
            "if(it[i]){const cb=it[i].querySelector('.el-checkbox');if(cb)cb.click();}}", idx)
        ipc.wait_for_timeout(1200)
        if "1 条" in card_texts(ipc)["selected"]:
            return True
        # 方法B/C: Playwright force click checkbox / 卡片（省略，思路同）
    return False
```
