# -*- coding: utf-8 -*-
"""兼容入口：session_helpers 实现已迁移至 qa_skill_common。

保持既有用法不变：`from session_helpers import ...`。
"""
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[0]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qa_skill_common.session_helpers import *  # noqa: F401,F403


if __name__ == "__main__":
    print("session_helpers 已迁移至 qa_skill_common，可用函数见 qa_skill_common/session_helpers.py")
