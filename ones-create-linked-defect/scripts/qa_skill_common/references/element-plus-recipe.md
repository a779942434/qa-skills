# Element Plus 交互配方（表单 / 下拉 / 表格）

> 来源：2026-09-10 真实跑一个字段级需求（列表/筛选/新增/编辑/导入核验）时反复踩的坑。
> 每条都固化成 `qa_skill_common/bbt_helpers.py` 里的函数，**不要再手写平行逻辑**。

## 一、七个高频坑（会重复踩）

| # | 坑 | 表现 | 正确做法 |
| --- | --- | --- | --- |
| 1 | 选中**隐藏**输入框 | `locator.fill` 超时，日志提示 `element is not visible` | 只取可见元素；或用 `form_item(page, label)` 精确定位 |
| 2 | JS `element.click()` 打不开下拉 | 下拉不出现、选项为空 | 必须用 Playwright **真实点击**：`open_select(page, item)` |
| 3 | 表格首个 `th` 是**复选框**（空表头） | 按表头名取列时**差一列**，读到隔壁列的值 | 用 `table_col(page, "加工面")`（内部按含空 th 的完整索引算） |
| 4 | 靠 DOM 猜「多选」 | 空的多选没有 `.el-tag` → **假 FAIL** | **行为判定**：`select_is_multiple(page, item, ["A","B"])`（选两个看是否都保留） |
| 5 | 读下拉选中值用 `input.value` | 读到空字符串 | `select_value(item)`（读 `.el-select__selected-item`） |
| 6 | 用 `Escape` 收下拉 | **把整个弹窗关了**，后续断言全废 | 不要按 Escape；下拉通常自动收起，需要时点空白处 |
| 7 | 全局搜索用 `fill` | 不触发过滤、无结果 | 逐字 `type`：`goto_feature(page, "<功能名>")` |

## 二、常用配方

### 1. 按功能名直达页面（不用逐级点菜单）
```python
from bbt_osd_common import login_for_page, goto_feature
login_for_page(page, "http://<host>/")
url = goto_feature(page, "<功能名>")   # 返回落地 URL，失败返回 None；站点取 MES_URL
```

### 2. 按标签定位表单项（避免同名字段串台）
```python
from bbt_helpers import form_item
fit = form_item(page, "加工面")                 # 筛选区
dit = form_item(page, "加工面", scope="[role=dialog]")   # 弹窗内
```

### 3. 下拉：选项 / 选择 / 读值 / 单选多选判定
```python
from bbt_helpers import open_select, select_options, select_option, select_value, select_is_multiple

open_select(page, dit)
opts = select_options(page)            # ['单面','TOP面','BOT面']
select_option(page, dit, "TOP面")
val = select_value(dit)                # 'TOP面'
is_multi = select_is_multiple(page, fit, ["BOT面", "TOP面"])   # True=多选
```

### 4. 表格按表头名取整列
```python
from bbt_helpers import table_col
values = table_col(page, "加工面")      # ['BOT面','TOP面','单面',...]
```

### 5. 分体按钮「新增▾」下拉（如「导入 Excel」）
```python
from bbt_helpers import open_dropdown_menu, click_dropdown_item
items = open_dropdown_menu(page, near_text="新增")   # ['导入 Excel']
click_dropdown_item(page, "导入")
```

## 三、字段级需求核验的断言口径（**行为证据优先**）

判定一个字段是否符合需求，优先用可观察行为，不要用 DOM 结构猜测：

| 需求点 | 推荐断言 |
| --- | --- |
| 字段存在 | 表头/表单项 label 命中 |
| 必填 | **空表单提交** → 该项出现 `.el-form-item__error`（如「必填项」），且弹窗不关闭 |
| 单选 | 连续选 2 个值 → 只保留最后 1 个 |
| 多选 | 连续选 2 个值 → 两个都保留（含折叠「+N」） |
| 选项取值 | 下拉选项集合 == 需求枚举 |
| 不选默认全部 | 不选 → 查询结果含多个不同取值 |
| 可编辑 | 编辑弹窗含该字段且可下拉 |

> 若某条需求需求原文未写明（如唯一性约束），标「需求未明确-需产品确认」，**不要自行判定为缺陷**。

## 四、会话与等待（提速，2026-09-10）

共享 helper 已把固定 sleep 换成条件等待，**不要再自己 `wait_for_timeout(5000)` 之类的长等待**：

| helper | 作用 |
| --- | --- |
| `wait_app_ready(page)` | 等首屏就绪（内容元素出现 + loading 遮罩消失），替代 goto 后的固定 7s |
| `wait_any(page, selector, timeout)` | 等任一选择器命中（逗号=OR） |
| `wait_gone(page, selector, timeout)` | 等元素消失（如 `.el-loading-mask`） |
| `ensure_login(page, target_url)` | 已登录则跳过登录（不重复走登录流程） |
| `goto_feature(page, name)` | 按功能名直达；**命中缓存时直接跳转**（重复访问同一功能 ~2s） |
| `session(base_url=...)`（`session_helpers`） | 一次会话上下文：起/连浏览器 + 登录 + 收尾，脚本不用重复样板 |

用法：
```python
from session_helpers import session
from bbt_osd_common import goto_feature
with session(base_url="http://<host>") as page:
    url = goto_feature(page, "<功能名>")
```

> 实测（某真实 MES 测试站点，单次会话固定开销）：**44.3s → 12.1s**；重复访问同一功能 **20.9s → ~3s**。
