# -*- coding: utf-8 -*-
"""连接常驻 ONES 浏览器（CDP，默认 9334）与 ONES 接口封装。

连接失败时给出可操作的提示（先启动 scripts/ones_edge_server.py）。
接口封装（页面请求自动携带登录 Cookie）：
    search_user(page, team_uuid, keyword)      -> POST users/search
    get_task_info(page, team_uuid, task_uuid)  -> GET task/{uuid}/info
    get_transitions(page, team_uuid, task_uuid)-> GET task/{uuid}/transitions
    send_comment(page, team_uuid, task_uuid, rich_html) -> POST send_message
"""
import json
import time as _time
import uuid as uuid_mod
from pathlib import Path

from playwright.sync_api import sync_playwright

from ones_config import resolve_settings


def _cdp_url():
    settings = resolve_settings()
    return f"http://127.0.0.1:{settings['cdp_port']}"


def _find_page(ctx, url_contains=None):
    """在常驻浏览器上下文里查找目标页面（默认定位 ONES 页面）。"""
    for p in ctx.pages:
        try:
            if url_contains and url_contains not in (p.url or ""):
                continue
            return p
        except Exception:
            continue
    return None


def connect(url_contains="ones.shuyilink.com"):
    """连接常驻浏览器并复用已有 ONES 页面，避免重复多开工单页/弹窗。

    执行完只用 disconnect(pw) 断开，不关闭浏览器窗口。
    """
    url = _cdp_url()
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(url, timeout=20000)
    except Exception as exc:
        raise SystemExit(
            f"连接 CDP {url} 失败：{exc}\n"
            "请先启动常驻浏览器：python scripts/ones_edge_server.py [工单URL]\n"
            "（若首次运行，脚本会自动准备本机 Edge 登录态）"
        ) from exc
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = _find_page(ctx, url_contains=url_contains)
    if page is None:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, browser, ctx, page


def disconnect(pw):
    try:
        pw.stop()
    except Exception:
        pass


# ---------- ONES API 封装 ----------

def _api(page, method, path, body=None):
    settings = resolve_settings()
    url = settings["ones_url"].rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    data = json.dumps(body, ensure_ascii=False) if body is not None else None
    try:
        resp = page.request.fetch(url, method=method, headers=headers, data=data)
    except Exception as exc:
        raise RuntimeError(f"ONES 接口请求失败 {method} {path}: {exc}") from exc
    if resp.status >= 400:
        raise RuntimeError(f"ONES 接口返回 {resp.status} {method} {path}: {resp.text()[:300]}")
    try:
        return resp.json()
    except Exception:
        return None


def search_user(page, team_uuid, keyword, limit=10):
    """按姓名搜索 ONES 用户，返回命中列表（含 uuid/name 等）。"""
    return _api(
        page,
        "POST",
        f"/project/api/project/team/{team_uuid}/users/search",
        {"keyword": keyword, "limit": limit},
    )


def get_task_info(page, team_uuid, task_uuid):
    """读取工单信息（owner=产品负责人、assign=负责人、desc/desc_rich=描述）。"""
    return _api(
        page,
        "GET",
        f"/project/api/project/team/{team_uuid}/task/{task_uuid}/info",
    )


# 后续建缺陷真正需要的父工单字段（其余字段如 field002 描述、field016 富文本一律不取，避免搬运大段内容）
PARENT_REQUIRED_FIELDS = {
    "5nUKjALP": "source_project",     # 来源项目
    "Jtnem8qs": "source_customer",    # 来源客户
    "W9qkyVXr": "function_module",    # 功能模块
    "Wq56Wyjw": "product_owner",      # 产品负责人
    "field012": "priority",           # 优先级
    "field004": "assignee",           # 负责人
    "PAefcDE8": "frontend",           # 前端人员
    "YBszpWb3": "backend",            # 后端人员
}


def get_task_required_fields(page, team_uuid, task_uuid):
    """只提取建缺陷需要的父工单字段，返回精简 dict，不搬运完整 field_values/描述。"""
    info = get_task_info(page, team_uuid, task_uuid) or {}
    fv = {f.get("field_uuid"): f.get("value") for f in info.get("field_values", [])}
    return {
        "number": info.get("number"),
        "summary": info.get("summary"),
        "owner": info.get("owner"),
        "assign": info.get("assign"),
        "status_uuid": info.get("status_uuid"),
        "issue_type_uuid": info.get("issue_type_uuid"),
        "issue_type_scope_uuid": info.get("issue_type_scope_uuid"),
        "fields": {name: fv.get(uuid) for uuid, name in PARENT_REQUIRED_FIELDS.items()},
    }


# 严重程度（ONES 全局固定选项；黑盒测试报告里的 S1~S4 只给测试人员自用，不进 ONES）
SEVERITY = {
    "致命": "Dgk6PHkS",
    "严重": "QYe31Dn9",
    "一般": "XxwMNPQp",
    "提示": "A3HEmFsu",
    "建议": "RDtgWTEi",
    "保留": "MnAwAecn",
}
DEFAULT_SEVERITY = "一般"


def get_current_user(page):
    """读取当前 ONES 登录账号（负责人/验证人用），返回 {uuid, name}。"""
    return page.evaluate(
        """() => ({uuid: localStorage.getItem('user_id') || '', name: localStorage.getItem('user_name') || ''})"""
    )


def get_transitions(page, team_uuid, task_uuid):
    """读取工单可流转状态列表（transitions[]，含 uuid/name/end_status_uuid）。"""
    return _api(
        page,
        "GET",
        f"/project/api/project/team/{team_uuid}/task/{task_uuid}/transitions",
    )


def send_comment(page, team_uuid, task_uuid, rich_html):
    """给工单发评论（备用接口；rich_html 为富文本，@提及用 ones-at-user-block）。"""
    return _api(
        page,
        "POST",
        f"/project/api/project/team/{team_uuid}/task/{task_uuid}/send_message",
        {"uuid": str(uuid_mod.uuid4()), "content_type": 1, "text": rich_html},
    )


def create_linked_defect(page, team_uuid, parent_task_uuid, summary, field_values, assign,
                         task_uuid=None, issue_type_scope_uuid=None):
    """在 ONES 创建缺陷并关联到主工单（API 直连，替代繁琐的 UI 弹窗操作）。

    参数:
        page: Playwright page（需携带 ONES 登录态）
        team_uuid: 团队 UUID（工单 URL 中 /team/{team_uuid}/）
        parent_task_uuid: 主工单任务 UUID
        summary: 缺陷标题
        field_values: 字段值数组（可从同工单已有缺陷 tasks/info 复制模板后
                      替换 field001=标题 / field002=描述；严重程度留 null 用默认值）
        assign: 负责人 UUID（如当前登录账号）
        task_uuid: 新任务 UUID（默认自动生成：assign 前缀 + 8 位随机）

    返回: (number, task_uuid)
    """
    base = f"/project/api/project/team/{team_uuid}"
    if not task_uuid:
        suffix = "".join(uuid_mod.uuid4().hex[:8])
        task_uuid = assign[:8] + suffix
    task_payload = {
        "uuid": task_uuid,
        "assign": assign,
        "summary": summary,
        "parent_uuid": "",
        "field_values": field_values,
    }
    if issue_type_scope_uuid:
        task_payload["issue_type_scope_uuid"] = issue_type_scope_uuid
    payload = {"tasks": [task_payload]}
    created = _api(page, "POST", f"{base}/tasks/add3", payload)
    task = (created or {}).get("tasks", [{}])[0]
    number = task.get("number")
    if not number:
        raise RuntimeError(f"创建缺陷失败: {created}")
    link = _api(page, "POST", f"{base}/task/{parent_task_uuid}/related_tasks", {
        "task_uuids": [task_uuid],
        "task_link_type_uuid": "UUID0001",
        "link_desc_type": "link_out_desc",
    })
    return number, task_uuid


def get_parent_handlers(page, team_uuid, task_uuid):
    """从主工单字段获取 (前端人员 uuid, 后端人员 uuid)。

    字段约定（当前 ONES 配置）：
        PAefcDE8 = 前端人员（如 王斌 JGwXEzXq）
        YBszpWb3 = 后端人员（如 安杰 1vmJxxsw）
    处理人规则：UI 前端类 bug 指向前端人员，其余类 bug 指向后端人员。
    """
    req = get_task_required_fields(page, team_uuid, task_uuid)
    return req["fields"].get("frontend"), req["fields"].get("backend")


# ---------- 新建缺陷弹窗 UI 自动化（稳定版，基于实测踩坑固化） ----------

def defect_dialog_index(page):
    """返回当前页面中“新建缺陷弹窗”（含‘选择关联关系’且可见）的下标，找不到返回 -1。

    注意：ONES 页面存在多个 [role=dialog]（工单抽屉也是 dialog），且弹窗为 fixed
    定位，offsetParent 为 null，因此用 getBoundingClientRect 判断可见性。
    """
    return page.evaluate(
        """() => {
            const ds = Array.from(document.querySelectorAll('[role=dialog]'));
            for (let i = 0; i < ds.length; i++) {
                const d = ds[i];
                const r = d.getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && (d.innerText || '').includes('选择关联关系')) return i;
            }
            return -1;
        }"""
    )


def find_defect_dialog(page):
    """返回新建缺陷弹窗 locator；未找到返回 None。"""
    idx = defect_dialog_index(page)
    if idx < 0:
        return None
    return page.locator("[role=dialog]").nth(idx)


def _defect_dialog_js():
    """定位新建缺陷弹窗的 JS 表达式（限定在弹窗子树内操作，避免同名 label 命中工单抽屉）。"""
    return (
        "Array.from(document.querySelectorAll('[role=dialog]'))"
        ".find(d => d.getBoundingClientRect().width > 0 "
        "&& (d.innerText||'').includes('选择关联关系'))"
    )


def set_select_option(page, label, keyword, expect, timeout=8):
    """在新建缺陷弹窗内按字段名选择下拉选项（稳定版）。

    流程：弹窗内按叶子文本精确匹配 label -> 聚焦搜索输入框 -> 真实键入关键词 ->
    轮询 body 级 teleport 的可见下拉选项（选项不在弹窗 DOM 内）-> JS 点击。
    返回是否选择成功。
    """
    ok = page.evaluate(
        """(label) => {
            const dlg = """ + _defect_dialog_js() + """;
            if (!dlg) return false;
            let target = null;
            const walk = (el) => {
                if (target) return;
                if (el.childElementCount === 0 && el.textContent && el.textContent.trim() === label) {
                    target = el; return;
                }
                for (const c of el.children) walk(c);
            };
            walk(dlg);
            if (!target) return false;
            let p = target.parentElement;
            for (let i = 0; i < 8 && p; i++) {
                const inp = p.querySelector('input.ones-select-selection-search-input');
                if (inp) { inp.focus(); return true; }
                p = p.parentElement;
            }
            return false;
        }""",
        label,
    )
    if not ok:
        return False
    page.keyboard.press("Meta+a")
    page.keyboard.press("Backspace")
    page.keyboard.type(keyword)
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        clicked = page.evaluate(
            """(expect) => {
                let found = null;
                document.querySelectorAll('.ones-select-dropdown').forEach(dd => {
                    let p = dd, vis = true;
                    while (p && p !== document.body) {
                        const st = getComputedStyle(p);
                        if (st.display === 'none') { vis = false; break; }
                        p = p.parentElement;
                    }
                    if (vis && dd.getBoundingClientRect().width > 0) {
                        dd.querySelectorAll('[class*=option]').forEach(o => {
                            const t = (o.innerText || '').trim();
                            if (t.includes(expect)) found = o;
                        });
                    }
                });
                if (found) { found.click(); return true; }
                return false;
            }""",
            expect,
        )
        if clicked:
            page.wait_for_timeout(800)
            return True
        _time.sleep(0.8)
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    return False


def set_desc(page, text):
    """向新建缺陷弹窗的描述编辑器（editor2）写入内容。

    注意：CKEDITOR.instances 里 editor1 是主工单描述，editor2 才是弹窗描述；
    必须用“选择关联关系”弹窗包含的实例，不能用 document.querySelector 取第一个 dialog。
    """
    name = page.evaluate(
        """(text) => {
            const dlg = """ + _defect_dialog_js() + """;
            if (!dlg) return null;
            for (const k in CKEDITOR.instances) {
                try {
                    const inst = CKEDITOR.instances[k];
                    if (dlg.contains(inst.element.$)) {
                        inst.setData('<p>' + text.replace(/\\n/g, '<br>') + '</p>');
                        return k;
                    }
                } catch (e) {}
            }
            return null;
        }""",
        text,
    )
    if name:
        try:
            page.evaluate("(name) => { const i = CKEDITOR.instances[name]; if (i) i.fire('change'); }", name)
        except Exception:
            pass
    return name


def upload_evidence(page, paths):
    """向新建缺陷弹窗上传证据文件并确认（稳定版）。

    坑：上传确认弹窗也是 [role=dialog]，不能用 Locator 比较排除主弹窗；
    判定条件为“可见 dialog 且文本含‘上传文件’且不含‘选择关联关系’”。
    """
    dlg = find_defect_dialog(page)
    if dlg is None:
        return False, "未找到缺陷弹窗"
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        return False, "缺少证据: " + ", ".join(str(p) for p in missing)
    up = dlg.locator("input.upload-input")
    if up.count() == 0:
        return False, "未找到上传控件 input.upload-input"
    up.set_input_files([str(p) for p in paths])
    page.wait_for_timeout(2500)
    for _ in range(6):
        clicked = page.evaluate(
            """() => {
                const ds = Array.from(document.querySelectorAll('[role=dialog]'));
                for (const d of ds) {
                    const r = d.getBoundingClientRect();
                    const t = (d.innerText || '');
                    if (r.width > 0 && r.height > 0 && t.includes('上传文件') && !t.includes('选择关联关系')) {
                        const btn = Array.from(d.querySelectorAll('button')).find(b => (b.innerText || '').trim() === '确定');
                        if (btn) { btn.click(); return true; }
                    }
                }
                return false;
            }"""
        )
        if clicked:
            page.wait_for_timeout(3000)
            return True, "已确认上传"
        page.wait_for_timeout(1000)
    return True, "未出现上传确认弹窗（继续）"


def submit_defect(page, wait=8):
    """点击新建缺陷弹窗“确定”并断言成功（弹窗关闭）。

    返回 (ok, 详情)。ok 仅代表弹窗已关闭；仍建议事后用关联内容数量/标题核对。
    """
    clicked = page.evaluate(
        """() => {
            const dlg = """ + _defect_dialog_js() + """;
            if (!dlg) return false;
            const btn = Array.from(dlg.querySelectorAll('button')).find(b => (b.innerText || '').trim() === '确定');
            if (!btn) return false;
            btn.click();
            return true;
        }"""
    )
    if not clicked:
        return False, "未找到确定按钮"
    deadline = _time.time() + wait
    while _time.time() < deadline:
        _time.sleep(1)
        if defect_dialog_index(page) < 0:
            return True, "弹窗已关闭"
    return False, "弹窗未关闭（可能校验未通过）"


def _js_click_text(page, text):
    """按叶子文本找到元素并点击其最近的可点击祖先（JS 点击，绕过遮挡/可见性限制）。"""
    return page.evaluate(
        """(text) => {
            let target = null;
            const walk = (el) => {
                if (target) return;
                if (el.childElementCount === 0 && el.textContent && el.textContent.trim() === text) {
                    target = el; return;
                }
                for (const c of el.children) walk(c);
            };
            walk(document.body);
            if (!target) return false;
            let p = target;
            while (p && p !== document.body && !p.onclick && !p.closest('[class*=tab]') && p.tagName !== 'BUTTON' && p.tagName !== 'A') {
                p = p.parentElement;
            }
            const clickTarget = (p && p !== document.body) ? p : target;
            clickTarget.click();
            return true;
        }""",
        text,
    )


def open_work_order_drawer(page, team_uuid, task_uuid, title):
    """打开 ONES 工单抽屉并切到「关联内容」页签。

    返回是否成功；成功后可调用 list_related_tasks() / open_defect_form()。
    """
    settings = resolve_settings()
    base = settings["ones_url"].rstrip("/")
    page.goto(f"{base}/project/#/team/{team_uuid}/task/{task_uuid}", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    page.locator("text=" + title).first.click(timeout=6000)
    page.wait_for_timeout(5000)
    return _js_click_text(page, "关联内容")


def open_defect_form(page, team_uuid, task_uuid, title):
    """从工单抽屉打开「新建关联工作项」弹窗并选择工作项类型=缺陷。

    返回新建缺陷弹窗 locator；失败返回 None。弹窗定位统一用 defect_dialog_index()。
    """
    if not open_work_order_drawer(page, team_uuid, task_uuid, title):
        return None
    page.wait_for_timeout(2500)
    _js_click_text(page, "新建关联工作项")
    page.wait_for_timeout(3500)
    dlg = find_defect_dialog(page)
    if dlg is None:
        return None
    selects = dlg.locator(".ones-select")
    type_sel = None
    for j in range(selects.count()):
        try:
            if "请选择类型" in selects.nth(j).inner_text():
                type_sel = selects.nth(j)
                break
        except Exception:
            pass
    if type_sel is None:
        return None
    type_sel.evaluate("(el) => { const s = el.querySelector('.ones-select-selector') || el; s.click(); }")
    page.wait_for_timeout(1200)
    inp = type_sel.locator("input.ones-select-selection-search-input").first
    inp.evaluate("(el) => el.focus()")
    page.keyboard.type("缺陷")
    page.wait_for_timeout(2500)
    page.evaluate(
        """() => {
            let found = null;
            document.querySelectorAll('.ones-select-dropdown').forEach(dd => {
                let p = dd, vis = true;
                while (p && p !== document.body) {
                    const st = getComputedStyle(p);
                    if (st.display === 'none') { vis = false; break; }
                    p = p.parentElement;
                }
                if (vis && dd.getBoundingClientRect().width > 0) {
                    dd.querySelectorAll('[class*=option]').forEach(o => {
                        if ((o.innerText || '').trim().includes('缺陷')) found = o;
                    });
                }
            });
            if (found) found.click();
        }"""
    )
    page.wait_for_timeout(5000)
    return find_defect_dialog(page)


def capture_field_options(page, label, keyword, expect=None, timeout=10):
    """在新建缺陷弹窗内捕获某下拉字段的选项（文本 + UUID）。

    原理：聚焦字段搜索框并键入关键词后，前端会请求字段选项接口，响应 JSON 中通常
    同时包含选项文本与 uuid。本函数监听所有 JSON 响应，返回去重后的
    [{"text": ..., "uuid": ...}]。DOM 中的选项不暴露 uuid，必须靠接口响应。

    用法（混合模式）：
        1. open_defect_form(...) 打开弹窗；
        2. capture_field_options(page, "系统环境", "奥联", "t-aolian") 拿到 uuid；
        3. 写入 config/field-mapping.yaml 缓存，之后全部走 create_linked_defect API。
    """
    hits = []

    def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return
            j = resp.json()
        except Exception:
            return
        text = json.dumps(j, ensure_ascii=False)
        if expect and expect not in text:
            return
        if keyword and keyword not in text:
            return

        def walk(obj):
            if isinstance(obj, dict):
                name = obj.get("name") or obj.get("text") or obj.get("label")
                value = obj.get("value")
                uid = obj.get("uuid") or obj.get("id") or obj.get("option_uuid") or (
                    value if isinstance(value, str) and len(value) == 8 else None
                )
                if name and uid:
                    hits.append({"text": str(name), "uuid": str(uid)})
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(j)

    page.on("response", on_response)
    # 聚焦字段输入框并键入
    focused = page.evaluate(
        """(label) => {
            const dlg = """ + _defect_dialog_js() + """;
            if (!dlg) return false;
            let target = null;
            const walk = (el) => {
                if (target) return;
                if (el.childElementCount === 0 && el.textContent && el.textContent.trim() === label) {
                    target = el; return;
                }
                for (const c of el.children) walk(c);
            };
            walk(dlg);
            if (!target) return false;
            let p = target.parentElement;
            for (let i = 0; i < 8 && p; i++) {
                const inp = p.querySelector('input.ones-select-selection-search-input');
                if (inp) { inp.focus(); return true; }
                p = p.parentElement;
            }
            return false;
        }""",
        label,
    )
    if not focused:
        return []
    page.keyboard.press("Meta+a")
    page.keyboard.press("Backspace")
    page.keyboard.type(keyword)
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        _time.sleep(0.8)
        if hits:
            break
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    seen = set()
    out = []
    for h in hits:
        key = (h["text"], h["uuid"])
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out


def capture_field_options_fiber(page, label, keyword=""):
    """从 React fiber 提取下拉选项 {text, uuid}（稳定兜底，网络捕获失败时用）。

    ONES 选项数据在虚拟列表 List fiber 的 memoizedProps.data[] 中：
    - data[].value = 选项 uuid
    - 选项显示名取下拉 DOM 可见文本（按顺序与 data 对齐后去重）。
    """
    item = page.locator(".ones-form-item", has=page.locator(f"label:has-text('{label}')"))
    if item.count() == 0:
        return []
    item.locator(".ones-select").first.click()
    page.wait_for_timeout(800)
    if keyword:
        page.keyboard.type(keyword)
        page.wait_for_timeout(1200)

    data = page.evaluate(
        """() => {
            const dds = Array.from(document.querySelectorAll('.ones-select-dropdown')).filter(d => {
                let p = d;
                while (p && p !== document.body) {
                    if (getComputedStyle(p).display === 'none') return false;
                    p = p.parentElement;
                }
                return d.getBoundingClientRect().width > 0;
            });
            if (!dds.length) return {texts: [], uuids: []};
            const opts = Array.from(dds[dds.length - 1].querySelectorAll('[class*=option]'));
            const texts = [];
            const seen = new Set();
            for (const o of opts) {
                const t = (o.innerText || '').trim();
                if (t && !seen.has(t)) { seen.add(t); texts.push(t); }
            }
            const uuids = [];
            if (opts.length) {
                const k = Object.keys(opts[0]).find(x => x.startsWith('__reactFiber$'));
                let f = k ? opts[0][k] : null;
                let i = 0;
                while (f && i < 40) {
                    const mp = f.memoizedProps || {};
                    if (Array.isArray(mp.data)) {
                        mp.data.forEach(x => {
                            const d = x && x.data ? x.data : {};
                            const uid = (x && x.value) || d.uuid || d.option_uuid || d.id;
                            if (uid) uuids.push(String(uid));
                        });
                        break;
                    }
                    f = f.return;
                    i++;
                }
            }
            return {texts, uuids};
        }"""
    )
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    texts = data.get("texts", [])
    uuids = data.get("uuids", [])
    return [{"text": texts[i], "uuid": uuids[i]} for i in range(min(len(texts), len(uuids)))]


def list_related_tasks(page, team_uuid, task_uuid, title):
    """打开主工单抽屉的「关联内容」，返回已渲染的关联工作项标题列表。

    注意：关联列表是 React Virtualized，只返回当前已渲染行；如需全量请滚动后多次调用合并。
    """
    open_work_order_drawer(page, team_uuid, task_uuid, title)
    page.wait_for_timeout(4000)
    return page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('.task-item').forEach(r => {
                const t = (r.innerText || '').trim();
                if (t && !out.includes(t)) out.push(t);
            });
            return out;
        }"""
    )


def dedup_check(titles):
    """统计关联工作项标题重复情况，返回 {标题: 出现次数}（仅次数>1）。"""
    from collections import Counter
    return {t: c for t, c in Counter(titles).items() if c > 1}


def build_defect_fields(page, team_uuid, parent_task_uuid, summary, desc, handler_uuid, sample_defect_uuid=None, overrides=None, severity_text=DEFAULT_SEVERITY):
    """从接口构建缺陷 field_values（全 API，不依赖 UI 弹窗）。

    字段来源：
        - 主工单 info：来源项目(5nUKjALP)、功能模块(W9qkyVXr)、产品负责人(Wq56Wyjw)、
          优先级(field012) 等共有字段直接复用主工单值；
        - 同类型缺陷模板 sample_defect_uuid：系统环境(R3UqL3Vm)、负责人/验证人(Sg5vqjRr)
          等缺陷类型特有字段（取同工单已有缺陷最稳妥）；
        - 动态设置：field001=标题、field002=描述、95jUV2Mb=处理人（按 UI/后端规则传入）；
        - 严重程度等未填字段保持 null（用 ONES 默认值）。

    overrides: 可选 dict，字段 uuid -> 值，用于补系统环境(R3UqL3Vm)/严重程度(field038)/
    验证人(Sg5vqjRr)等缺陷特有字段（无样例缺陷时父工单没有这些字段）。
    默认规则：
        - 严重程度 field038 默认「一般」；黑盒测试报告里的 S1~S4 仅自用，不据此定级；
        - 负责人 field004 / 验证人 Sg5vqjRr = 当前 ONES 登录账号（get_current_user）。

    返回可直接传给 create_linked_defect 的 field_values 数组。
    """
    FIELD_TYPES = {
        "field001": 2, "field002": 2, "5nUKjALP": 1, "W9qkyVXr": 1,
        "Wq56Wyjw": 8, "field012": 1, "Jtnem8qs": 1, "R3UqL3Vm": 1,
        "field004": 8, "Sg5vqjRr": 8, "DPNDusA2": 8, "95jUV2Mb": 8,
        "field038": 1, "NnkkhDGK": 1,
    }
    # 缺陷创建白名单：只提交缺陷类型可写字段，避免把需求/模板冗余字段带进 add3
    DEFECT_FIELD_WHITELIST = (
        "field001", "field002", "5nUKjALP", "W9qkyVXr", "Wq56Wyjw", "field012",
        "Jtnem8qs", "R3UqL3Vm", "field004", "Sg5vqjRr", "DPNDusA2", "95jUV2Mb",
        "field038", "NnkkhDGK",
    )
    parent = get_task_info(page, team_uuid, parent_task_uuid)
    parent_fv = {f.get("field_uuid"): f for f in (parent or {}).get("field_values", [])}
    if sample_defect_uuid:
        r = _api(page, "POST", f"/project/api/project/team/{team_uuid}/tasks/info", {"ids": [sample_defect_uuid]})
        sample = (r or {}).get("tasks", [{}])[0]
        fvs = [dict(f) for f in sample.get("field_values", [])]
        fv_map = {f["field_uuid"]: f for f in fvs}
        # 模板缺陷可能缺少部分必填/共有字段（如 5nUKjALP 来源项目），从主工单补齐
        for key in ("5nUKjALP", "W9qkyVXr", "Wq56Wyjw", "field012", "Jtnem8qs"):
            if key not in fv_map and key in parent_fv:
                fv_map[key] = dict(parent_fv[key])
        fv_map = {k: v for k, v in fv_map.items() if k in DEFECT_FIELD_WHITELIST}
        # 主工单共有字段值覆盖缺陷模板（保证与主工单一致）
        for key, fv in parent_fv.items():
            if key in fv_map:
                fv_map[key]["value"] = fv.get("value")
    else:
        fv_map = {k: dict(v) for k, v in parent_fv.items() if k in DEFECT_FIELD_WHITELIST}
    if "field001" in fv_map:
        fv_map["field001"]["value"] = summary
    if "field002" in fv_map:
        fv_map["field002"]["value"] = desc
    if "95jUV2Mb" in fv_map:
        fv_map["95jUV2Mb"]["value"] = handler_uuid
    else:
        fv_map["95jUV2Mb"] = {"field_uuid": "95jUV2Mb", "type": 8, "value": handler_uuid, "value_type": 0, "date_value": ""}
    # 负责人(field004) / 验证人(Sg5vqjRr) = 当前 ONES 登录账号，不再沿用父工单负责人
    current = get_current_user(page)
    fv_map["field004"] = {"field_uuid": "field004", "type": 8, "value": current.get("uuid") or "", "value_type": 0, "date_value": ""}
    fv_map["Sg5vqjRr"] = {"field_uuid": "Sg5vqjRr", "type": 8, "value": current.get("uuid") or "", "value_type": 0, "date_value": ""}
    # 严重程度默认「一般」（黑盒报告的 S1~S4 仅自用，不据此定级）
    fv_map["field038"] = {"field_uuid": "field038", "type": 1, "value": SEVERITY.get(severity_text, SEVERITY[DEFAULT_SEVERITY]), "value_type": 0, "date_value": ""}
    for fuuid, val in (overrides or {}).items():
        if val is None:
            continue
        fv_map[fuuid] = {"field_uuid": fuuid, "type": FIELD_TYPES.get(fuuid, 1), "value": val, "value_type": 0, "date_value": ""}
    return list(fv_map.values())
