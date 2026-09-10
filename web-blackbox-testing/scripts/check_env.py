#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web-blackbox-testing 使用前自检。

用法: python scripts/check_env.py

检查项:
    1. Python 依赖（playwright / pyyaml）
    2. 浏览器可启动（真实起一次无头浏览器，最能反映「能不能跑」）
    3. 登录凭据（MES_ACCOUNT / MES_PASSWORD）
    4. 被测站点连通（MES_URL）
    5. 输出目录可写

退出码：存在 FAIL 返回 1，否则返回 0。
环境与全部变量的总表见 scripts/qa_skill_common/references/environment.md。
"""
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qa_skill_common import env_check as ec  # noqa: E402


def main():
    results = []
    results += ec.check_deps()
    results += ec.check_browser()
    results += ec.check_env_vars(["MES_ACCOUNT", "MES_PASSWORD"])
    results += ec.check_site(os.environ.get("MES_URL", ""))
    results += ec.check_writable(os.environ.get("OUT_DIR", os.getcwd()))
    return ec.report("web-blackbox-testing 环境自检", results)


if __name__ == "__main__":
    sys.exit(main())
