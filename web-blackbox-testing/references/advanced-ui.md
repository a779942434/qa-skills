# 进阶 UI 场景（按需查）

> 由 `references/playwright-strategy.md` 拆出：只在遇到对应场景时读，不必每次加载。

## 级联与树选择（侦测先行）（2026-09-03 增补）

el-cascader 两级结构（如 来源地：事业部 → 车间）需要「先展开父节点 → 点叶节点」两步；且必须在知道结构确为两级父→子时才走这一步，否则跳过。用 bbt_helpers.detect_cascade(page, trigger_sel) 先侦测：

- 示例：diag = detect_cascade(page, "input[placeholder*='来源地'] 或其他触发选择器")
- diag 结构：{kind:'el-cascader-2level'|'single-list'|'unknown', hasParentChild:bool, parents:[...], leaves:[...]}
- 若 diag.get("hasParentChild") 为真：ok, val = select_cascade(page, trigger_sel, leaf_part="车间1", diag=diag)；返回 (ok, value) 已回填 / (fail, reason)
- 若为假（非两级级联 / 不是级联）：跳过，不盲点（记结构观察或待人工）

要点：

- select_cascade 内部会先调 detect_cascade（或复用传入 diag），hasParentChild=False 时返回 (skip, reason) 不执行任何点击。
- 选择成功后必须断言输入框回填非空（(ok, value)），否则记 fail（回填空 = 需人工复核）。
- 若页面下拉不是 el-cascader 两级而是一次性列表/其它组件，直接走「标准用户操作」，不要套用级联步骤。
## Playwright MCP 无头隔离模式（默认）

> MES 黑盒测试默认使用无头、隔离浏览器；不连接用户日常 Chrome profile、现有标签页或 ONES CDP `9334`。
> 需要可见窗口时，只有用户明确要求“人工接管”才可临时切换，任务结束后恢复无头配置。

Codex 侧 `~/.codex/config.toml` 应配置为：

```toml
[mcp_servers.playwright]
type = "stdio"
command = "npx"
args = [
  "-y",
  "@playwright/mcp@latest",
  "--headless",
  "--isolated",
  "--browser",
  "chrome",
  "--viewport-size",
  "1680x950",
]
```

要点：

- `--headless`：后台静默运行，不显示浏览器窗口。
- `--isolated`：每次创建新的临时 profile，不读取和修改用户日常登录态。
- `--browser chrome`：使用本机系统 Chrome，不下载 Playwright 浏览器。
- 禁止 `--extension` 和 `PLAYWRIGHT_MCP_EXTENSION_TOKEN`；它们会连接用户真实 Chrome。
- 修改配置后必须重启 Codex，旧 MCP 进程不会自动加载新参数。
- 一次会话只有一个持有者；不要把 MES MCP 页面与 ONES 常驻 Edge 混用。
## 新站点适配侦察定式（2026-09-07 增补）

> 适用：目标站点/组件库与固化站点（示例 Element UI 站点）不同（如自研 sy-*/div-table 组件、
> 登录非 Keycloak、内容在 iframe/弹层）。此时固定选择器（.el-table__row 等）与固化登录不适用，
> 按下面定式一次摸清，避免“侦察→试操作→失败→再侦察”循环：

1. **先做组件指纹探针（只读，已代码化）**：`python scripts/recon-generic/recon_page.py --url <URL> --probe`
   —— dump 高频 class 前缀 + iframe 数，并直接给出组件库判定（`element-plus` / `mixed` / `custom` / `unknown`）
   与未知高频前缀；不同即停用旧选择器，不自作假设套用。
2. **入口用“全局搜索按功能名直达”**：优先用站点首页搜索框逐字输入功能名（部分搜索框对 fill 不触发过滤，
   需 click→清空→逐字 type→点下拉项），得到「模块>分类>功能名」路径与直达 URL 后记录，不走菜单逐级点击。
3. **一次会话内完成侦察并固化**：登录一次 → 组件指纹 + 入口 + TAB/主子表/弹窗结构（按钮/表头/弹窗祖先链）写入
   references/<站点>-<功能>.md，之后所有用例脚本直接引用；结构侦察在同一会话内进行，页面不再重复 dump。
   **同时存一份机器可读指纹**：`--save-fingerprint <名字>`；该页面改版后用 `--diff <名字>` 直接看
   哪些元素「消失 / 变化 / 新增」，不必重新人工侦察 —— 只有确有变化时才回来更新 reference。
4. **适配期例外**：全新组件库的首次适配允许侦察 >2 次，但每次必须把发现写进该页面 reference 并在下一次直接引用，
   禁止反复打印整页文本/全部按钮；适配完成后按原「侦察≤2次」纪律执行。
5. **交互组件先探后点**：弹窗/下拉/分体按钮（如「新增▾」）先读祖先链判断触发方式（click vs hover），
   再决定用 Playwright 或 JS 可见点击（见 bbt_helpers 无视觉辅助），不盲点隐藏元素。
