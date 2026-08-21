# -*- coding: utf-8 -*-
"""兼容入口：接口观测等待工具已迁移至 qa_skill_common。

保持既有用法不变：`from api_wait import ApiWatcher`。
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qa_skill_common.api_wait import *  # noqa: F401,F403


if __name__ == "__main__":
    print("api_wait 可用：ApiWatcher(page) -> snapshot() -> 操作 -> wait_new(base)")
