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
import mimetypes
import re
import time as _time
import uuid as uuid_mod
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

from ones_config import resolve_settings
from qa_skill_common.bbt_helpers import wait_any, wait_gone, wait_dialog_open, wait_app_ready
from qa_skill_common.session_helpers import cdp_health, wait_cdp_healthy


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


def connect(url_contains="ones.shuyilink.com", recover=True):
    """连接常驻浏览器并复用已有 ONES 页面，避免重复多开工单页/弹窗。

    执行完只用 disconnect(pw) 断开，不关闭浏览器窗口。
    CDP 假死或 Edge 意外退出时，交给 ones_edge_server 监管器自动重启/等待恢复，
    客户端自身不杀进程，避免与监管器抢重启。
    """
    settings = resolve_settings()
    url = _cdp_url()
    attempts = 2 if recover else 1
    last_error = None
    if recover:
        try:
            from ones_edge_server import ensure_server_process
            _started, healthy, meta = ensure_server_process(
                url=settings["ones_url"], visible=False,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            healthy = False
            meta = {}
        if not healthy:
            raise SystemExit(
                f"CDP {url} 不健康且监管器未能恢复。\n"
                f"监管器状态: {meta}\n"
                "请查看 logs/ones_edge_server.log 与 bootstrap_edge.log。"
            ) from last_error
    for attempt in range(attempts):
        if not cdp_health(url, timeout=1.0).ok:
            wait_cdp_healthy(url, timeout=45.0)

        pw = None
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.connect_over_cdp(url, timeout=20000)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = _find_page(ctx, url_contains=url_contains)
            if page is None:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
            return pw, browser, ctx, page
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            try:
                if pw is not None:
                    pw.stop()
            except Exception:
                pass
            if attempt >= attempts - 1:
                break
            # 给后台监管器时间完成自动重启，再连接一次；客户端不终止 Edge。
            wait_cdp_healthy(url, timeout=45.0)
    raise SystemExit(
        f"连接 CDP {url} 失败：{last_error}\n"
        "守卫进程会自动检查并重启专用 Edge；仍失败时请查看 ones_edge_server.log。"
    ) from last_error


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


DEFECT_ISSUE_TYPE_UUID = "6FUpniBf"


def get_issue_type_scope(page, team_uuid, project_uuid, issue_type_uuid=DEFECT_ISSUE_TYPE_UUID):
    """按项目 + 工作项类型直接解析 issue_type_scope_uuid。

    这是替代“先找一张历史缺陷再复制 scope”的稳定路径：历史缺陷不是前置条件，
    同一项目下是否已有缺陷也不影响创建。一次 GraphQL 查询即可拿到 scope。
    """
    query = """query ISSUE_TYPE_SCOPES {
      issueTypeScopes {
        uuid
        name
        issueType { uuid name }
        project { uuid }
      }
    }"""
    result = _api(
        page,
        "POST",
        f"/project/api/project/team/{team_uuid}/items/graphql?t=issue-type-scopes",
        {"query": query, "variables": {}},
    )
    if (result or {}).get("errors"):
        raise RuntimeError(f"查询缺陷类型 scope 失败: {result['errors']}")
    scopes = (((result or {}).get("data") or {}).get("issueTypeScopes") or [])
    matches = [
        s for s in scopes
        if ((s.get("project") or {}).get("uuid") == project_uuid
            and ((s.get("issueType") or {}).get("uuid") == issue_type_uuid))
    ]
    if len(matches) == 1:
        return matches[0].get("uuid")
    if not matches:
        raise RuntimeError(
            f"项目中未找到缺陷类型 scope（project={project_uuid}, issue_type={issue_type_uuid}）"
        )
    raise RuntimeError(f"项目中缺陷类型 scope 不唯一（project={project_uuid}）：{matches}")


def get_issue_type_fields(page, team_uuid, issue_type_scope_uuid):
    """读取指定缺陷类型 scope 的字段定义（含 required/options/defaultValue）。"""
    query = """query FIELDS($issueTypeScopeUUID: IssueTypeScopeUUID) {
      fields(
        filter: {
          pool_in: ["task"],
          context: {
            type_equal: "issue_type_scope",
            issueTypeScopeUUID_equal: $issueTypeScopeUUID
          }
        }
      ) {
        uuid
        name
        fieldType
        required
        allowEmpty
        defaultValue
        options { uuid value }
      }
    }"""
    result = _api(
        page,
        "POST",
        f"/project/api/project/team/{team_uuid}/items/graphql?t=fields",
        {"query": query, "variables": {"issueTypeScopeUUID": issue_type_scope_uuid}},
    )
    if (result or {}).get("errors"):
        raise RuntimeError(f"查询缺陷字段定义失败: {result['errors']}")
    return (((result or {}).get("data") or {}).get("fields") or [])


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
        "project_uuid": info.get("project_uuid"),
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


# 缺陷创建白名单：只提交缺陷类型可写字段，避免把需求/模板冗余字段带进 add3
DEFECT_FIELD_WHITELIST = (
    "field001", "field002", "field016", "5nUKjALP", "W9qkyVXr", "Wq56Wyjw", "field012",
    "Jtnem8qs", "R3UqL3Vm", "field004", "Sg5vqjRr", "DPNDusA2", "95jUV2Mb",
    "field038", "NnkkhDGK",
)


def get_parent_field_values(page, team_uuid, task_uuid):
    """只取主工单白名单字段的完整 field_value 对象（避免每个 bug 重复 fetch 完整 info）。"""
    info = get_task_info(page, team_uuid, task_uuid)
    return {f.get("field_uuid"): f for f in (info or {}).get("field_values", [])
            if f.get("field_uuid") in DEFECT_FIELD_WHITELIST}


def get_parent_context(page, team_uuid, task_uuid):
    """一次 fetch 主工单，返回 (required_fields, parent_field_values)，供多次建缺陷复用。"""
    info = get_task_info(page, team_uuid, task_uuid) or {}
    fv = {f.get("field_uuid"): f.get("value") for f in info.get("field_values", [])}
    req = {
        "number": info.get("number"),
        "summary": info.get("summary"),
        "project_uuid": info.get("project_uuid"),
        "owner": info.get("owner"),
        "assign": info.get("assign"),
        "status_uuid": info.get("status_uuid"),
        "issue_type_uuid": info.get("issue_type_uuid"),
        "issue_type_scope_uuid": info.get("issue_type_scope_uuid"),
        "fields": {name: fv.get(uuid) for uuid, name in PARENT_REQUIRED_FIELDS.items()},
    }
    parent_fv = {f.get("field_uuid"): f for f in info.get("field_values", [])
                 if f.get("field_uuid") in DEFECT_FIELD_WHITELIST}
    return req, parent_fv


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
    tasks = (created or {}).get("tasks") or []
    if not tasks:
        raise RuntimeError(f"创建缺陷失败: {created}")
    task = tasks[0]
    number = task.get("number")
    if not number:
        raise RuntimeError(f"创建缺陷失败: {created}")
    try:
        link = _api(page, "POST", f"{base}/task/{parent_task_uuid}/related_tasks", {
            "task_uuids": [task_uuid],
            "task_link_type_uuid": "UUID0001",
            "link_desc_type": "link_out_desc",
        })
    except Exception as exc:
        raise RuntimeError(
            f"缺陷已创建 #{number} uuid={task_uuid}，但关联主工单失败；"
            f"请勿重复创建，重试关联时使用该 uuid。原因: {exc}"
        ) from exc
    if isinstance(link, dict) and link.get("code") not in (None, 200, "200", "OK"):
        raise RuntimeError(
            f"缺陷已创建 #{number} uuid={task_uuid}，但关联主工单失败: {link}"
        )
    return number, task_uuid


def get_parent_handlers(page, team_uuid, task_uuid):
    """从主工单字段获取 (前端人员 uuid, 后端人员 uuid)。

    字段约定（当前 ONES 配置）：
        PAefcDE8 = 前端人员（取主工单前端人员 uuid）
        YBszpWb3 = 后端人员（取主工单后端人员 uuid）
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


def _attachment_meta(path):
    """返回 ONES 附件初始化所需元数据；图片尽量补上尺寸。"""
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    meta = {
        "type": "attachment",
        "name": path.name,
        "ref_type": "task",
        "description": "",
        "ctype": mime,
    }
    if mime.startswith("image/"):
        try:
            from PIL import Image  # 可选依赖；缺失时由 ONES 在文件上传后解析尺寸。
            with Image.open(path) as img:
                meta["image_width"], meta["image_height"] = img.size
        except Exception:
            pass
    return meta


def upload_task_attachment_api(page, team_uuid, task_uuid, file_path, description=""):
    """直接调用 ONES 文件接口，把单个附件绑定到指定 task_uuid。

    ONES 实际是两段式上传：
      1. POST `/project/api/project/team/{team}/res/attachments/upload` 申请 token/resource_uuid；
      2. POST `upload_url`，multipart 字段为 `token` + `file`。
    不经过详情页和“文件”页签，也不会出现页面串台。
    """
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"附件不存在: {path}")
    meta = _attachment_meta(path)
    meta["ref_id"] = task_uuid
    if description:
        meta["description"] = description
    init = _api(
        page,
        "POST",
        f"/project/api/project/team/{team_uuid}/res/attachments/upload",
        meta,
    ) or {}
    upload_url = init.get("upload_url")
    token = init.get("token")
    resource_uuid = init.get("resource_uuid")
    if not upload_url or not token or not resource_uuid:
        raise RuntimeError(f"附件上传初始化失败: {init}")
    resp = page.request.post(
        upload_url,
        multipart={
            "token": token,
            "file": {
                "name": path.name,
                "mimeType": meta["ctype"],
                "buffer": path.read_bytes(),
            },
        },
    )
    if resp.status >= 400:
        raise RuntimeError(f"附件上传失败 {resp.status}: {resp.text()[:300]}")
    return resource_uuid


def upload_task_evidences_api(page, team_uuid, task_uuid, file_paths, timeout=90):
    """按指定 task_uuid 顺序上传附件，并以附件接口新增 uuid 校验成功。"""
    files = [Path(p) for p in file_paths]
    before = get_task_attachments(page, team_uuid, task_uuid)
    before_uuids = {a.get("uuid") for a in (before.get("attachments") or []) if a.get("uuid")}
    uploaded = []
    for path in files:
        uploaded.append(upload_task_attachment_api(page, team_uuid, task_uuid, path))
    expected = [p.name for p in files]
    ok, data, missing = wait_new_attachments(
        page, team_uuid, task_uuid, expected,
        before_uuids=before_uuids, timeout=timeout,
    )
    return ok, data, missing, uploaded


def _inline_image_names(html):
    """从描述富文本中提取图片文件名，用于避免重复插入。"""
    names = set()
    for raw in re.findall(r'filename=([^&"\\]+)', html or ''):
        try:
            name = unquote(raw).strip()
        except Exception:
            name = str(raw).strip()
        if name:
            names.add(name)
    # 兼容未带 filename 参数的极少见图片节点
    for raw in re.findall(r'<img[^>]+data-uuid="([^"]+)"', html or ''):
        if raw:
            names.add(str(raw))
    return names


def _visible_description_editor(page):
    """选择当前真正可见、尺寸最大的描述编辑器，排除隐藏的占位 editor。"""
    editors = page.locator('.cke_wysiwyg_div[contenteditable=true]:visible')
    best = None
    best_area = -1
    for i in range(editors.count()):
        item = editors.nth(i)
        try:
            box = item.bounding_box() or {}
            width = float(box.get('width') or 0)
            height = float(box.get('height') or 0)
            area = width * height
            if width >= 200 and height >= 40 and area > best_area:
                best, best_area = item, area
        except Exception:
            continue
    return best



def _enter_description_edit(page, viewer, timeout=8.0):
    """从查看态进入 CKEditor 编辑态，避开图片中心导致预览弹窗。"""
    deadline = _time.time() + max(float(timeout), 1.0)
    while _time.time() < deadline:
        # 优先点击首个非图片文本段落，正文通常从“严重程度/环境”等文本开始。
        try:
            para = viewer.locator('p:not(:has(img))').filter(has_text=re.compile(r'\S')).first
            if para.count():
                para.click(timeout=2000)
        except Exception:
            pass
        page.wait_for_timeout(250)
        try:
            if page.locator('a.cke_button__onesimage:visible').count():
                return True
        except Exception:
            pass
        # 若已打开图片预览，Escape 只关预览，不取消正文编辑。
        try:
            page.keyboard.press('Escape')
        except Exception:
            pass
        page.wait_for_timeout(200)
        try:
            viewer.click(position={'x': 8, 'y': 8}, timeout=1500)
        except Exception:
            pass
        page.wait_for_timeout(250)
        try:
            if page.locator('a.cke_button__onesimage:visible').count():
                return True
        except Exception:
            pass
    return False

def append_task_description_images(page, team_uuid, task_uuid, image_paths,
                                   timeout=90.0, verify_loaded=True):
    """把截图以内嵌图片形式追加到 ONES 工作项富文本描述并保存。

    为什么不用仅附件：任务“文件”页签里有附件，不代表用户在描述里能直接看到证据。
    本函数走真实 CKEditor 图像上传按钮，等待图片 src 从占位 GIF 变为可访问 URL，
    保存后重新读取 field016/desc_rich，并校验图片节点数量。

    返回 dict：
      requested/skipped/inserted/image_count/verified
    """
    image_files = [Path(p) for p in image_paths
                   if Path(p).suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif', '.webp')]
    result = {
        'requested': [p.name for p in image_files],
        'skipped': [],
        'inserted': [],
        'image_count': 0,
        'verified': False,
    }
    if not image_files:
        result['verified'] = True
        return result

    base = resolve_settings()['ones_url'].rstrip('/')
    task_url = f"{base}/project/#/team/{team_uuid}/task/{task_uuid}"
    if task_uuid not in (page.url or '') or '/task/' not in (page.url or ''):
        page.goto(task_url, wait_until='domcontentloaded', timeout=60000)
    wait_app_ready(page, timeout=min(timeout, 20))
    page.wait_for_timeout(800)

    info = get_task_info(page, team_uuid, task_uuid) or {}
    fv = {f.get('field_uuid'): f.get('value') for f in (info.get('field_values') or [])}
    html = str(fv.get('field016') or info.get('desc_rich') or '')
    existing = _inline_image_names(html)
    result['image_count'] = len(re.findall(r'<img', html))
    # 保存后的 field016 可能是占位 data:gif，但查看态 DOM 的 src 会解析为真实文件 URL，
    # 从查看态补充提取 filename，保证重复执行时能稳定识别已内嵌证据。
    try:
        viewer_imgs = page.locator('.richtext-editor-viewer:visible img')
        for i in range(viewer_imgs.count()):
            src = viewer_imgs.nth(i).get_attribute('src') or ''
            existing |= _inline_image_names(src)
    except Exception:
        pass
    if all(p.name in existing for p in image_files):
        result['skipped'] = [p.name for p in image_files]
        result['verified'] = True
        return result
    todo = [p for p in image_files if p.name not in existing]
    result['skipped'] = [p.name for p in image_files if p.name in existing]
    if not todo:
        result['verified'] = True
        return result
    expected_total = result['image_count'] + len(todo)

    viewer = page.locator('.richtext-input-viewer-wrapper:visible').first
    viewer.wait_for(state='visible', timeout=int(min(timeout, 20) * 1000))
    if not _enter_description_edit(page, viewer, timeout=min(float(timeout), 8.0)):
        raise RuntimeError('未进入描述 CKEditor 编辑态')

    inserted = []
    try:
        for path in todo:
            editor = _visible_description_editor(page)
            if editor is None:
                raise RuntimeError('未找到可见的描述富文本编辑器')
            box = editor.bounding_box() or {}
            x = max(10, min(20, float(box.get('width') or 40) - 2))
            y = max(10, min(20, float(box.get('height') or 40) - 2))
            editor.click(position={'x': x, 'y': y}, timeout=5000)
            page.keyboard.press('Control+End')
            page.wait_for_timeout(200)

            editor = _visible_description_editor(page)
            before_count = editor.locator('.ones-image-figure img').count()
            with page.expect_file_chooser(timeout=int(min(timeout, 15) * 1000)) as chooser_info:
                page.locator('a.cke_button__onesimage:visible').first.click(timeout=5000)
            chooser_info.value.set_files(str(path))

            deadline = _time.time() + max(10.0, float(timeout))
            uploaded = False
            last_src = ''
            while _time.time() < deadline:
                editor = _visible_description_editor(page)
                if editor is None:
                    page.wait_for_timeout(300)
                    continue
                imgs = editor.locator('.ones-image-figure img')
                count = imgs.count()
                if count > before_count:
                    image = imgs.nth(count - 1)
                    last_src = image.get_attribute('src') or ''
                    loaded = True
                    if verify_loaded:
                        try:
                            loaded = bool(image.evaluate('(e) => !!(e.complete && e.naturalWidth > 0)'))
                        except Exception:
                            loaded = False
                    if last_src.startswith('https://') and 'data:image/gif' not in last_src and loaded:
                        uploaded = True
                        break
                page.wait_for_timeout(400)
            if not uploaded:
                raise RuntimeError(f'图片上传未完成: {path.name}; src={last_src[:200]}')
            inserted.append(path.name)

        editor = _visible_description_editor(page)
        if editor is None:
            raise RuntimeError('保存前未找到描述编辑器')
        real_srcs = []
        for i in range(editor.locator('.ones-image-figure img').count()):
            src = editor.locator('.ones-image-figure img').nth(i).get_attribute('src') or ''
            real_srcs.append(src)
        if any('data:image/gif' in src for src in real_srcs):
            raise RuntimeError('保存前仍有图片占位 GIF 未完成上传')

        with page.expect_response(lambda r: '/tasks/update3' in r.url, timeout=int(timeout * 1000)) as response_info:
            page.get_by_role('button', name='保存', exact=True).last.click(timeout=5000)
        response = response_info.value
        if int(response.status) >= 400:
            raise RuntimeError(f'描述保存失败 HTTP {response.status}: {response.text()[:300]}')
        page.wait_for_timeout(1000)

        after = get_task_info(page, team_uuid, task_uuid) or {}
        after_fv = {f.get('field_uuid'): f.get('value') for f in (after.get('field_values') or [])}
        after_html = str(after_fv.get('field016') or after.get('desc_rich') or '')
        count = len(re.findall(r'<img', after_html))
        missing = [] if count >= expected_total else ['图片节点数量不足']
        result.update({
            'inserted': inserted,
            'image_count': count,
            'verified': not missing,
            'missing': missing,
            'after_html': after_html,
        })
        if missing:
            raise RuntimeError(f'保存后描述内图片数量不足: {count}/{expected_total}')
        return result
    except Exception:
        try:
            page.get_by_role('button', name='取消', exact=True).last.click(timeout=2000)
        except Exception:
            pass
        raise


def get_task_attachments(page, team_uuid, task_uuid):
    """读取任务附件列表；这是“文件”页签是否真正加载完成的接口真相。"""
    return _api(
        page,
        "GET",
        f"/project/api/project/team/{team_uuid}/task/{task_uuid}/attachments?since=0",
    ) or {}


def wait_new_attachments(page, team_uuid, task_uuid, expected_names, before_uuids=None, timeout=60, interval=0.8):
    """轮询附件接口，直到所有期望文件名都作为新附件出现。

    不依赖固定 sleep，也不依赖页面虚拟列表是否已渲染。返回 (ok, 最新响应, 缺失文件名)。
    """
    expected = {str(n) for n in expected_names if n}
    before = set(before_uuids or [])
    last = {}
    deadline = _time.time() + max(1, timeout)
    while True:
        try:
            last = get_task_attachments(page, team_uuid, task_uuid)
        except Exception:
            last = {}
        new_items = [
            a for a in (last.get("attachments") or [])
            if a.get("uuid") and a.get("uuid") not in before
        ]
        present = {a.get("name") for a in new_items}
        missing = sorted(expected - present)
        if not missing:
            return True, last, []
        remaining = deadline - _time.time()
        if remaining <= 0:
            return False, last, missing
        _time.sleep(min(interval, remaining))


def open_task_file_tab(page, team_uuid, task_uuid, timeout=15):
    """打开任务详情“文件”页签，并以附件接口响应确认页签数据已就绪。

    先复用当前同任务页面，避免每次都 goto 造成整页重载；随后点击页签并等待上传控件。
    最终以 GET `/task/{uuid}/attachments?since=0` 响应作为数据就绪判据。
    """
    base = resolve_settings()["ones_url"].rstrip("/")
    if task_uuid not in (page.url or "") or "/task/" not in (page.url or ""):
        page.goto(
            f"{base}/project/#/team/{team_uuid}/task/{task_uuid}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
    wait_app_ready(page, timeout=min(timeout, 12))
    tab = page.locator('.ones-tabs-item[title="文件"]:visible').first
    if tab.count() == 0:
        tab = page.locator(".ui-task-detail__tab:visible", has_text="文件").first
    try:
        tab.wait_for(state="visible", timeout=timeout * 1000)
        tab.click(timeout=5000)
    except Exception:
        if tab.count() == 0:
            raise RuntimeError("未找到任务详情“文件”页签")
        tab.evaluate("el => el.click()")
    page.wait_for_selector("input.upload-input", state="attached", timeout=timeout * 1000)
    return get_task_attachments(page, team_uuid, task_uuid)


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
    names = [Path(p).name for p in paths]
    up.set_input_files([str(p) for p in paths])
    confirm_js = """() => {
        const ds = Array.from(document.querySelectorAll('[role=dialog]'));
        for (const d of ds) {
            const r = d.getBoundingClientRect();
            const t = (d.innerText || '');
            if (r.width > 0 && r.height > 0 && t.includes('上传文件') && !t.includes('选择关联关系')) {
                const btn = Array.from(d.querySelectorAll('button')).find(b => (b.innerText || '').trim() === '确定');
                if (btn) return true;
            }
        }
        return false;
    }"""
    try:
        page.wait_for_function(confirm_js, timeout=20000)
    except Exception:
        return False, "等待上传确认弹窗超时"
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
    if not clicked:
        return False, "未找到上传确认按钮"
    try:
        page.wait_for_function(
            """(names) => {
                const text = document.body.innerText || '';
                return names.every(n => text.includes(n)) &&
                    names.every(n => {
                        const i = text.indexOf(n);
                        const tail = text.slice(i, i + 200);
                        return tail.includes('已上传') || tail.includes('上传成功');
                    });
            }""",
            arg=names,
            timeout=60000,
        )
    except Exception:
        return False, "上传确认后未在页面内观察到全部文件完成"
    return True, "已确认上传并等待完成"


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
    wait_app_ready(page)                                   # 替代固定 7s
    page.locator("text=" + title).first.click(timeout=6000)
    wait_any(page, "text=关联内容", timeout=10)             # 等抽屉，替代固定 5s
    return _js_click_text(page, "关联内容")


def open_defect_form(page, team_uuid, task_uuid, title):
    """从工单抽屉打开「新建关联工作项」弹窗并选择工作项类型=缺陷。

    返回新建缺陷弹窗 locator；失败返回 None。弹窗定位统一用 defect_dialog_index()。
    """
    if not open_work_order_drawer(page, team_uuid, task_uuid, title):
        return None
    wait_any(page, "text=新建关联工作项", timeout=8)        # 替代固定 2.5s
    _js_click_text(page, "新建关联工作项")
    wait_dialog_open(page, timeout=8)                       # 替代固定 3.5s
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
    wait_any(page, ".ones-select-dropdown [class*=option]", timeout=6)   # 替代固定 2.5s
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
    wait_gone(page, ".ones-select-dropdown", timeout=6)     # 替代固定 5s
    return find_defect_dialog(page)


def capture_field_options(page, label, keyword, expect=None, timeout=10):
    """在新建缺陷弹窗内捕获某下拉字段的选项（文本 + UUID）。

    原理：聚焦字段搜索框并键入关键词后，前端会请求字段选项接口，响应 JSON 中通常
    同时包含选项文本与 uuid。本函数监听所有 JSON 响应，返回去重后的
    [{"text": ..., "uuid": ...}]。DOM 中的选项不暴露 uuid，必须靠接口响应。

    用法（混合模式）：
        1. open_defect_form(...) 打开弹窗；
        2. capture_field_options(page, "系统环境", "<关键词>", "t-<关键词>") 拿到 uuid；
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
    wait_any(page, ".task-item", timeout=8)                 # 替代固定 4s
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


def build_defect_fields(page, team_uuid, parent_task_uuid, summary, desc, handler_uuid, sample_defect_uuid=None, overrides=None, severity_text=DEFAULT_SEVERITY, parent_fv=None, field_defs=None):
    """从接口构建缺陷 field_values（全 API，不依赖历史缺陷模板）。

    字段来源优先级：
        1. 主工单 info：来源项目、功能模块、产品负责人、优先级等共有字段；
        2. profile overrides：系统环境等缺陷类型特有字段，显式配置优先；
        3. 可选 sample_defect_uuid：仅为未配置的历史模板兜底，不应作为常规前置。

    动态设置：标题、描述、处理人、负责人/验证人、严重程度。
    传入 field_defs 时，提交前会校验缺陷类型的必填字段，缺值直接报出字段名，
    避免盲目复制历史缺陷后把旧环境/旧客户等脏数据带进新缺陷。
    """
    FIELD_TYPES = {
        "field001": 2, "field002": 2, "field016": 20, "5nUKjALP": 1, "W9qkyVXr": 1,
        "Wq56Wyjw": 8, "field012": 1, "Jtnem8qs": 1, "R3UqL3Vm": 1,
        "field004": 8, "Sg5vqjRr": 8, "DPNDusA2": 8, "95jUV2Mb": 8,
        "field038": 1, "NnkkhDGK": 1,
    }
    if parent_fv is None:
        parent_fv = get_parent_field_values(page, team_uuid, parent_task_uuid)
    if sample_defect_uuid:
        r = _api(page, "POST", f"/project/api/project/team/{team_uuid}/tasks/info", {"ids": [sample_defect_uuid]})
        sample = (r or {}).get("tasks", [{}])[0]
        fvs = [dict(f) for f in sample.get("field_values", [])]
        fv_map = {f["field_uuid"]: f for f in fvs}
        # 模板缺陷可能缺少部分共有字段，从主工单补齐。
        for key in ("5nUKjALP", "W9qkyVXr", "Wq56Wyjw", "field012", "Jtnem8qs"):
            if key not in fv_map and key in parent_fv:
                fv_map[key] = dict(parent_fv[key])
        fv_map = {k: v for k, v in fv_map.items() if k in DEFECT_FIELD_WHITELIST}
        # 主工单共有字段值覆盖历史模板，避免旧环境/旧客户数据污染。
        for key, fv in parent_fv.items():
            if key in fv_map:
                fv_map[key]["value"] = fv.get("value")
    else:
        fv_map = {k: dict(v) for k, v in parent_fv.items() if k in DEFECT_FIELD_WHITELIST}

    if "field001" in fv_map:
        fv_map["field001"]["value"] = summary
    else:
        fv_map["field001"] = {"field_uuid": "field001", "type": 2, "value": summary, "value_type": 0, "date_value": ""}

    # 描述字段：缺陷类型的描述为 field016（富文本），确保存在（兼容 field002 纯文本）。
    desc_html = "".join("<p>" + p + "</p>" for p in desc.split(chr(10)) if p.strip()) or "<p></p>"
    fv_map.setdefault("field016", {"field_uuid": "field016", "type": 20, "value": desc_html, "value_type": 0, "date_value": ""})
    fv_map["field016"]["value"] = desc_html
    if "field002" in fv_map:
        fv_map["field002"]["value"] = desc

    if "95jUV2Mb" in fv_map:
        fv_map["95jUV2Mb"]["value"] = handler_uuid
    else:
        fv_map["95jUV2Mb"] = {"field_uuid": "95jUV2Mb", "type": 8, "value": handler_uuid, "value_type": 0, "date_value": ""}

    # 负责人 / 验证人固定为当前 ONES 登录账号，不沿用父工单或历史缺陷。
    current = get_current_user(page)
    fv_map["field004"] = {"field_uuid": "field004", "type": 8, "value": current.get("uuid") or "", "value_type": 0, "date_value": ""}
    fv_map["Sg5vqjRr"] = {"field_uuid": "Sg5vqjRr", "type": 8, "value": current.get("uuid") or "", "value_type": 0, "date_value": ""}
    fv_map["field038"] = {"field_uuid": "field038", "type": 1, "value": SEVERITY.get(severity_text, SEVERITY[DEFAULT_SEVERITY]), "value_type": 0, "date_value": ""}

    type_by_uuid = {f.get("uuid"): FIELD_TYPES.get(f.get("uuid"), 1) for f in (field_defs or []) if f.get("uuid")}
    for fuuid, val in (overrides or {}).items():
        if val is None:
            continue
        fv_map[fuuid] = {
            "field_uuid": fuuid,
            "type": type_by_uuid.get(fuuid, FIELD_TYPES.get(fuuid, 1)),
            "value": val,
            "value_type": 0,
            "date_value": "",
        }

    if field_defs:
        missing = []
        for fd in field_defs:
            fuuid = fd.get("uuid")
            if not fd.get("required") or not fuuid or fuuid not in DEFECT_FIELD_WHITELIST:
                continue
            val = (fv_map.get(fuuid) or {}).get("value")
            if val in (None, "", [], {}):
                missing.append(f"{fd.get('name') or fuuid}({fuuid})")
        if missing:
            raise RuntimeError(
                "缺少缺陷必填字段: " + ", ".join(missing)
                + "；请在 profile overrides 中配置，不要依赖历史缺陷模板"
            )
    return list(fv_map.values())
