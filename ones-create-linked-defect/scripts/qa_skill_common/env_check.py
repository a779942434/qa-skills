# -*- coding: utf-8 -*-
"""公共环境自检核心（供 web-blackbox-testing / ones-create-linked-defect 复用）。

设计目标：把「新用户不知道自己缺什么」变成「跑一次自检 → 每条 FAIL 都给出修复命令」。
技能侧只做薄封装，公共检查项（依赖/浏览器/站点/环境变量/目录）只在这里维护一份。
"""
from __future__ import annotations

import os
import tempfile
import urllib.request

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# 依赖缺失时的统一修复指引：注意区分 pip install 与 playwright install
DEPS_FIX = "pip install playwright pyyaml（只装 Python 包；不要运行 playwright install 下载浏览器）"
BROWSER_FIX = (
    "安装系统 Chrome/Edge，或 export MES_BROWSER_PATH=/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome；"
    "若在沙箱内运行自检，请改用非沙箱权限"
)


class Result:
    __slots__ = ("name", "status", "detail", "fix")

    def __init__(self, name, status, detail="", fix=""):
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix


def ok(name, detail=""):
    return Result(name, PASS, detail)


def warn(name, detail="", fix=""):
    return Result(name, WARN, detail, fix)


def fail(name, detail="", fix=""):
    return Result(name, FAIL, detail, fix)


def check_deps(modules=("playwright", "yaml")):
    """检查 Python 依赖是否已安装。"""
    results = []
    for mod in modules:
        try:
            __import__(mod)
            results.append(ok(f"依赖 {mod}"))
        except ImportError:
            results.append(fail(f"依赖 {mod}", "未安装", DEPS_FIX))
    return results


def check_browser():
    """尝试真实启动一次无头浏览器（最能反映「能不能跑」的检查）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [fail("浏览器可启动", "playwright 未安装", DEPS_FIX)]
    try:
        from .bbt_helpers import launch_mes_browser
    except Exception as exc:  # noqa: BLE001
        return [fail("浏览器可启动", f"无法加载公共包：{exc}")]
    pw = None
    try:
        pw = sync_playwright().start()
        browser = launch_mes_browser(pw, headless=True)
        browser.close()
        return [ok("浏览器可启动")]
    except Exception as exc:  # noqa: BLE001
        return [fail("浏览器可启动", str(exc)[:140], BROWSER_FIX)]
    finally:
        try:
            if pw is not None:
                pw.stop()
        except Exception:  # noqa: BLE001
            pass


def check_site(url, timeout=8):
    """检查被测站点是否可达（仅 HEAD/GET，不做登录）。"""
    if not url:
        return [warn("站点连通", "未设置 MES_URL，跳过", "export MES_URL=http://<你的测试站点>")]
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return [ok("站点连通", f"HTTP {resp.status}")]
    except Exception as exc:  # noqa: BLE001
        return [fail("站点连通", f"{url} 不可达：{str(exc)[:100]}", "检查网络/网关，确认 MES_URL 正确")]


def check_env_vars(names):
    """检查环境变量是否已设置（未设置按 WARN 处理，附 export 指引）。"""
    results = []
    for name in names:
        if os.environ.get(name):
            results.append(ok(f"环境变量 {name}", "已设置"))
        else:
            results.append(warn(f"环境变量 {name}", "未设置", f"export {name}=..."))
    return results


def check_writable(path):
    """检查目录可写（不存在则尝试创建）。"""
    from pathlib import Path

    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(p), prefix=".envcheck_", delete=True):
            pass
        return [ok("输出目录可写", str(p))]
    except Exception as exc:  # noqa: BLE001
        return [fail("输出目录可写", f"{p}: {str(exc)[:100]}", "改用可写目录（如 export OUT_DIR=/tmp/qa-out）")]


def report(title, results, show_fixes=True):
    """统一输出格式，返回退出码（有 FAIL=1，否则 0）。"""
    print(f"== {title} ==")
    for r in results:
        suffix = f"  [{r.detail}]" if r.detail else ""
        print(f"  [{r.status}] {r.name}{suffix}")
    fails = [r for r in results if r.status == FAIL]
    warns = [r for r in results if r.status == WARN]
    print("==")
    print(f"结果: {len(results) - len(fails) - len(warns)} PASS, {len(warns)} WARN, {len(fails)} FAIL")
    if fails:
        if show_fixes:
            print("修复指引:")
            for r in fails:
                if r.fix:
                    print(f"  - {r.name}: {r.fix}")
        print("请先解决 FAIL 项再执行任务；环境变量类可先跳过、按需再配。")
        return 1
    if warns:
        print("WARN 项不阻塞，但注意按提示处理。")
    return 0
