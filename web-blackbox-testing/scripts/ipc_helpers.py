#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IPC 单机/产线界面导航辅助（web-blackbox-testing 技能配套）。

前提：浏览器已登录被测站点，传入当前 Page。
本文件不保存任何账号、密码、Token、站点配置值；系统密码与站点由调用方传入。

主要函数：
- unlock_ipc(page, system_password, base_url): 进入 IPC 系统设置并解锁。
- select_station_and_save(page, station): 选择站点并保存配置。
- enter_ipc_feature(page, feature, base_url): 在 IPC 首页进入单机/产线界面。
- setup_and_enter_ipc(page, station, feature, system_password, base_url): 组合上述流程。
"""
from __future__ import annotations

import time

from playwright.sync_api import Page

DEFAULT_BASE = "http://dog.ob.shuyilink.com"


def _frame_with_text(page: Page, text: str, exact: bool = True):
    """返回第一个包含指定文本的 frame；找不到时退回主 frame。"""
    for frame in page.frames:
        try:
            if frame.get_by_text(text, exact=exact).count() > 0:
                return frame
        except Exception:
            continue
    return page


def _frame_with_button(page: Page, text: str):
    """返回第一个包含指定按钮文本的 frame；找不到时退回主 frame。"""
    for frame in page.frames:
        try:
            if frame.locator(f"button:has-text('{text}')").count() > 0:
                return frame
        except Exception:
            continue
    return page


def _wait_for_button_frame(page: Page, text: str, timeout: int = 20):
    """轮询等待包含指定按钮文本的 frame，避免 IPC iframe 尚未渲染。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for frame in page.frames:
            try:
                if frame.locator(f"button:has-text('{text}')").count() > 0:
                    return frame
            except Exception:
                continue
        page.wait_for_timeout(500)
    return page


def _click_first_visible(locator, timeout: int = 5000):
    """逐个尝试可见元素；全部不可见则尝试第一个。返回是否已点击。"""
    for i in range(locator.count()):
        el = locator.nth(i)
        try:
            if el.is_visible():
                el.click(timeout=timeout)
                return True
        except Exception:
            continue
    if locator.count():
        locator.first.click(timeout=timeout)
        return True
    return False


def unlock_ipc(page: Page, system_password: str = "123456", base_url: str = DEFAULT_BASE):
    """进入 /ipc/setting，输入系统密码并点击解锁。

    解锁密码按用户提供；未提供时默认测试环境通用密码 "123456"。
    """
    if "/ipc/setting" not in page.url:
        page.goto(base_url + "/ipc/setting", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)

    frame = _wait_for_button_frame(page, "解锁")
    password = frame.locator("input[type=password]")
    if password.count():
        password.first.fill(system_password)
    unlock = frame.locator("button:has-text('解锁')")
    unlock.first.click(timeout=5000)
    page.wait_for_timeout(3000)
    return frame


def select_station_and_save(page: Page, station: str):
    """在 IPC 系统设置里精确选择站点，保存配置并确认刷新提示。"""
    frame = _frame_with_button(page, "解锁")
    trigger = frame.get_by_text("请选择站点", exact=False).first
    trigger.click(timeout=5000)
    page.wait_for_timeout(1800)

    option = frame.get_by_text(station, exact=True)
    _click_first_visible(option)
    page.wait_for_timeout(1800)

    save = frame.locator("button:has-text('保存配置')")
    if save.count():
        save.first.click(timeout=5000)
    page.wait_for_timeout(2500)

    # 确认提示不是标准 button，用文本定位并 force click。
    for f in page.frames:
        confirm = f.get_by_text("确认", exact=True)
        if confirm.count():
            try:
                confirm.first.click(force=True, timeout=3000)
                break
            except Exception:
                continue
    page.wait_for_timeout(8000)
    return frame


def enter_ipc_feature(page: Page, feature: str, base_url: str = DEFAULT_BASE):
    """在 IPC 首页点击精确文本入口，进入 /ipc/single 或 /ipc/line。"""
    expected = {
        "单机界面": "/ipc/single",
        "产线界面": "/ipc/line",
    }.get(feature)

    if "/ipc" not in page.url or "/setting" in page.url:
        page.goto(base_url + "/ipc", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)

    frame = _frame_with_text(page, feature)
    entry = frame.get_by_text(feature, exact=True)
    _click_first_visible(entry)

    if expected:
        try:
            page.wait_for_url(f"**{expected}**", timeout=15000)
        except Exception:
            page.wait_for_timeout(5000)
    else:
        page.wait_for_timeout(5000)
    return frame


def setup_and_enter_ipc(
    page: Page,
    station: str,
    feature: str,
    system_password: str = "123456",
    base_url: str = DEFAULT_BASE,
):
    """组合：解锁 → 选站保存 → 进入单机/产线界面。"""
    unlock_ipc(page, system_password, base_url)
    select_station_and_save(page, station)
    enter_ipc_feature(page, feature, base_url)
    return page


def set_card_mock(page: Page, card: str = "1"):
    """打开测试环境刷卡模拟开关（固定规则）。

    刷卡层直接读取键盘，不显示输入框；若键入卡号后无反应，说明需要
    设置 localStorage.card_mock = 1。该函数等价于 F12 -> Application ->
    Storage -> Local Storage 手动新增 card_mock=1。
    """
    page.evaluate("(value) => localStorage.setItem('card_mock', value)", str(card))


def swipe_card(page: Page, card: str = "1", wait_ms: int = 3500):
    """在「请在右下角刷您的工卡」刷卡层直接键入卡号（无需回车）。

    卡号不是固定值，优先使用用户提供的卡号；用户未提供时默认传入 "1"。
    """
    page.keyboard.type(str(card))
    page.wait_for_timeout(wait_ms)


def open_handover_dialog(page: Page):
    """在已进入 /ipc/single 的页面点击「交接班」，返回包含打卡信息的 frame。"""
    frame = _frame_with_text(page, "交接班")
    entry = frame.get_by_text("交接班", exact=True)
    _click_first_visible(entry)
    page.wait_for_timeout(4000)
    return _frame_with_text(page, "打卡信息")


__all__ = [
    "DEFAULT_BASE",
    "unlock_ipc",
    "select_station_and_save",
    "enter_ipc_feature",
    "setup_and_enter_ipc",
    "set_card_mock",
    "swipe_card",
    "open_handover_dialog",
]
