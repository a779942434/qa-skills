# -*- coding: utf-8 -*-
"""MES 黑盒测试公共工具箱：登录/导航/下拉/表单/表格/造数（幂等，环境无关）。

共享实现：由各技能目录下的兼容入口转发，避免跨技能复制维护。
"""
import os
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from .bbt_helpers import wait_text, wait_button, wait_toast

# 目标站点与账号不再写死（如 t-ousida/t-dafu），全部通过环境变量指定，留空即未配置：
#   MES_URL       被测 MES 站点根地址，如 http://t-dafu.ob.shuyilink.com
#   MES_ACCOUNT   Keycloak 登录账号
#   MES_PASSWORD  Keycloak 登录密码
URL = os.environ.get("MES_URL", "").rstrip("/")
ACCOUNT = os.environ.get("MES_ACCOUNT", "")
PASSWORD = os.environ.get("MES_PASSWORD", "")


def _page_url(path):
    """由站点根地址拼接页面路径；未配置 MES_URL 时返回空串。"""
    return URL + path if URL else ""


PD_URL = _page_url("/master-data/product/product-message-definition/index")
CR_URL = _page_url("/master-data/technology/process-route-definition/index")
OSD_URL = _page_url("/plan/work-plan/order-cycle-definition-OSD/index")

__all__ = [
    "URL", "PD_URL", "CR_URL", "OSD_URL", "ACCOUNT", "PASSWORD",
    "login_ousida", "login_for_page", "base_url_for", "goto",
    "wait_text", "wait_button", "wait_toast",
    "wait_table_rows", "click_leaf", "select_dialog_option", "fill_form_item",
    "click_nth_add", "confirm_msgbox", "toast_texts", "read_table_by_header",
    "find_row", "open_product_series", "ensure_product", "ensure_craft",
    "ensure_proc", "ensure_bom",
]


def login_ousida(page, base_url=None):
    """在目标 MES 站点完成 Keycloak 登录（环境无关，不再写死 t-ousida）。

    目标地址取 base_url 参数；未传时取环境变量 MES_URL。
    账号密码取环境变量 MES_ACCOUNT / MES_PASSWORD；未配置时抛出明确提示。
    """
    url = (base_url or URL).rstrip("/")
    if not url:
        raise RuntimeError(
            "未配置被测站点：请设置环境变量 MES_URL，或调用 login_ousida(page, base_url='http://<host>')"
        )
    if not ACCOUNT or not PASSWORD:
        raise RuntimeError("未配置登录账号：请设置环境变量 MES_ACCOUNT 与 MES_PASSWORD")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    if page.locator("input[name=username]").count() > 0:
        page.fill("input[name=username]", ACCOUNT)
        page.fill("input[name=password]", PASSWORD)
        page.locator("button#kc-login").click()
        page.wait_for_timeout(9000)


def base_url_for(target_url):
    """从目标页面 URL 提取站点根地址（scheme://netloc），供登录时定位同站点登录页。"""
    s = urlsplit(target_url)
    return f"{s.scheme}://{s.netloc}"


def login_for_page(page, target_url):
    """登录目标页面所在的 MES 站点：优先 MES_URL，未配置则取 target_url 的根地址。"""
    login_ousida(page, base_url=(URL or base_url_for(target_url)))


def goto(page, url):
    if not url:
        raise RuntimeError("目标 URL 为空：请先设置 MES_URL 环境变量或传入具体页面地址")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)



def wait_table_rows(page, min_rows=1, timeout=15000):
    """轮询直到主表行数 >= min_rows。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if page.locator(".el-table__row").count() >= min_rows:
                return True
        except Exception:
            pass
        page.wait_for_timeout(300)
    return False


def click_leaf(page, text):
    """按叶子文本点击（菜单/树）。"""
    return page.evaluate(
        """(txt) => {
            let el = null;
            const w = (n) => { if (el) return; if (n.childElementCount===0 && n.textContent && n.textContent.trim()===txt) { el=n; return; } for (const c of n.children) w(c); };
            w(document.body);
            if (!el) return false;
            let p = el;
            while (p && p !== document.body && !p.onclick && !p.closest('[class*=tree]') && !p.closest('[class*=item]') && !p.closest('[class*=node]')) p = p.parentElement;
            (p && p !== document.body ? p : el).click();
            return true;
        }""",
        text,
    )


def select_dialog_option(page, text):
    """在弹窗下拉中选择选项（键入关键词后点可见项）。"""
    page.locator(".el-dialog .el-select__wrapper").first.click()
    page.wait_for_timeout(700)
    page.keyboard.type(text)
    page.wait_for_timeout(900)
    try:
        page.locator(".el-select-dropdown__item:visible", has_text=text).first.click(timeout=5000)
        page.wait_for_timeout(500)
        return True
    except Exception:
        return False


def fill_form_item(page, idx, value):
    """按 el-form-item 索引填第一个输入框。"""
    page.locator(".el-dialog .el-form-item").nth(idx).locator("input").first.fill(value)


def click_nth_add(page, n=1):
    """点第 n 个「新增」按钮（0 起；子表新增通常是第 1 个）。"""
    page.locator("button:has-text('新增')").nth(n).click()
    page.wait_for_timeout(1800)


def confirm_msgbox(page):
    page.locator(".el-message-box button:has-text('确定')").first.click()
    page.wait_for_timeout(1500)


def toast_texts(page):
    return page.locator(".el-message, .el-notification").all_inner_texts()


def read_table_by_header(page, keyword):
    """按表头关键字找子表，返回 {hdr, rows} 或 None。"""
    return page.evaluate(
        """(kw) => {
            const ts = Array.from(document.querySelectorAll('.el-table'));
            for (const t of ts) {
                const h = Array.from(t.querySelectorAll('th')).map(x => (x.innerText||'').trim());
                if (h.some(x => x.includes(kw))) {
                    return {hdr: h, rows: Array.from(t.querySelectorAll('.el-table__row')).map(r => (r.innerText||'').trim().replace(/\\n+/g,' | '))};
                }
            }
            return null;
        }""",
        keyword,
    )


def find_row(page, keyword):
    """返回主表第一行含关键字的行 index，找不到返回 None。"""
    rows = page.locator(".el-table__row")
    for i in range(rows.count()):
        if keyword in rows.nth(i).inner_text():
            return i
    return None


def open_product_series(page, series="半成品(CPXL002)"):
    """产品信息定义：展开树并切到目标系列（先点成品，再点目标系列）。"""
    click_leaf(page, "成品(CPXL003)")
    wait_text(page, series)
    click_leaf(page, series)
    wait_button(page, "新增")
    wait_table_rows(page, min_rows=1)
    page.wait_for_timeout(1200)


# ---------- 造数（幂等：已存在则跳过） ----------

def ensure_product(page, name, code, series="半成品(CPXL002)"):
    """产品信息定义造产品。"""
    goto(page, PD_URL)
    open_product_series(page, series)
    if find_row(page, name) is not None:
        print(f"[ensure] 产品已存在，跳过: {name}")
        return False
    page.locator("button:has-text('新增')").first.click()
    page.wait_for_timeout(1800)
    items = page.locator(".el-dialog .el-form-item")
    items.nth(1).locator("input").first.fill(name)   # 产品名称
    items.nth(3).locator("input").first.fill(code)   # 产品编号
    page.locator(".el-dialog button:has-text('确定')").first.click()
    page.wait_for_timeout(2500)
    print(f"[ensure] 产品新增 {name}:", toast_texts(page))
    return True


def ensure_craft(page, product, route):
    """工艺路线定义造主表（产品+工艺路线）。"""
    goto(page, CR_URL)
    wait_table_rows(page, min_rows=1)
    if find_row(page, route) is not None:
        print(f"[ensure] 工艺路线已存在，跳过: {route}")
        return False
    page.locator("button:has-text('新增')").first.click()
    page.wait_for_timeout(1800)
    select_dialog_option(page, product)
    page.wait_for_timeout(600)
    fill_form_item(page, 1, route)   # 工艺路线
    page.locator(".el-dialog button:has-text('确定')").first.click()
    page.wait_for_timeout(2500)
    print(f"[ensure] 工艺路线新增 {route}:", toast_texts(page))
    return True


def ensure_proc(page, route, procs):
    """工艺路线定义给主表加工序（procs=[(工序名, 顺序), ...]）。"""
    goto(page, CR_URL)
    wait_table_rows(page, min_rows=1)
    idx = find_row(page, route)
    if idx is None:
        print(f"[ensure] 工艺路线不存在，跳过工序: {route}")
        return False
    page.locator(".el-table__row").nth(idx).locator("td").nth(1).click()
    page.wait_for_timeout(2200)
    tbl = read_table_by_header(page, "工序顺序")
    existing = " | ".join(tbl["rows"]) if tbl else ""
    for name, order in procs:
        if name in existing:
            print(f"[ensure] 工序已存在，跳过: {name}")
            continue
        click_nth_add(page, 1)
        items = page.locator(".el-dialog .el-form-item")
        items.nth(2).locator(".el-select").first.click()
        page.wait_for_timeout(700)
        page.keyboard.type(name)
        page.wait_for_timeout(900)
        try:
            page.locator(".el-select-dropdown__item:visible", has_text=name).first.click(timeout=5000)
        except Exception:
            print(f"[ensure] 选工序失败: {name}")
        page.wait_for_timeout(500)
        items.nth(1).locator("input").first.fill(order)  # 工序顺序
        page.locator(".el-dialog button:has-text('确定')").first.click()
        page.wait_for_timeout(2200)
        print(f"[ensure] 工序新增 {name}(顺序{order}):", toast_texts(page))
        existing += " " + name
    return True


def ensure_bom(page, product, bom_rows):
    """产品信息定义给产品造 BOM（bom_rows=[(bom产品名, 母件产出量, 子件消耗量), ...]）。"""
    goto(page, PD_URL)
    open_product_series(page)
    idx = find_row(page, product)
    if idx is None:
        print(f"[ensure] 产品不存在，跳过BOM: {product}")
        return False
    page.locator(".el-table__row").nth(idx).locator("td").nth(1).click()
    page.wait_for_timeout(2200)
    tbl = read_table_by_header(page, "母件产出量")
    existing = " | ".join(tbl["rows"]) if tbl else ""
    for bom_product, out_qty, in_qty in bom_rows:
        if bom_product in existing:
            print(f"[ensure] BOM已存在，跳过: {bom_product}")
            continue
        click_nth_add(page, 1)
        items = page.locator(".el-dialog .el-form-item")
        items.nth(0).locator(".el-select").first.click()
        page.wait_for_timeout(700)
        page.keyboard.type(bom_product)
        page.wait_for_timeout(900)
        try:
            page.locator(".el-select-dropdown__item:visible", has_text=bom_product).first.click(timeout=5000)
        except Exception:
            print(f"[ensure] 选BOM产品失败: {bom_product}")
        page.wait_for_timeout(500)
        items.nth(1).locator("input").first.fill(str(out_qty))  # 母件产出量
        items.nth(2).locator("input").first.fill(str(in_qty))   # 子件消耗量
        page.locator(".el-dialog button:has-text('确定')").first.click()
        page.wait_for_timeout(2200)
        print(f"[ensure] BOM新增 {bom_product}:", toast_texts(page))
        existing += " " + bom_product
    return True
