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
## Playwright MCP 真窗口模式（Chrome 扩展，2026-09-04 增补）

> 定位：与「Python Playwright 脚本」并列的第二种连接方式，只解决「复用真窗口已登录态」这一场景；
> 判定/纪律类原则仍以 SKILL.md 必守清单为准，此处只写安装、配置与使用钩子。

适用场景：被测系统在**日常 Chrome 默认 profile 里已登录**（如已登录的测试站点），希望 AI 直接操控真实窗口、
复用登录态做黑盒，最贴近真实用户操作。

- 本体：微软官方 `@playwright/mcp`，Codex 侧配置已写入 `~/.codex/config.toml`：

  ```toml
  [mcp_servers.playwright]
  type = "stdio"
  command = "npx"
  args = ["-y", "@playwright/mcp@latest", "--extension"]
  ```

- 扩展：Chrome Web Store 装 **Playwright MCP Bridge**
  `https://chromewebstore.google.com/detail/playwright-mcp-bridge/mmlmfjhmonkocbjadbfplnigmagldckm`
  （装在哪个 Chrome profile，就能连那个 profile 里已登录的标签页）。
- 免弹窗：点扩展图标打开状态页 → 复制 `PLAYWRIGHT_MCP_EXTENSION_TOKEN` → 写入 config 同节 env：

  ```toml
  [mcp_servers.playwright.env]
  PLAYWRIGHT_MCP_EXTENSION_TOKEN = "<用户提供的 token>"
  ```

  Token 随 profile 走；不配置则每次连接需在扩展弹窗点 approve。
- 生效条件：改完 config 需**重启 Codex**（新 MCP server 才会加载）；扩展未装时 `--extension` 启动后工具不可用。
- 使用纪律：与 Python Playwright 一致——一次会话一个持有者、复用标签页、不混用 ONES 常驻 Edge；
  首个标签页由用户在扩展弹窗里选定（选被测页签），随后按必守清单走标准用户操作，禁止 JS 强制改值/绕过 UI。
- 与脚本的关系：MCP 真窗口适合「探索/人工登录态复用」，批量回归仍可走 Python 长脚本；两者择一，不双写同一用例。
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
