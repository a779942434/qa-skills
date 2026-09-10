# -*- coding: utf-8 -*-
"""兼容入口：report_gen 实现已迁移至 qa_skill_common。

保持既有用法不变：`from report_gen import ...`。
"""
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[0]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qa_skill_common.report_gen import *  # noqa: F401,F403


if __name__ == "__main__":
    print("report_gen 已迁移至 qa_skill_common，可用函数见 qa_skill_common/report_gen.py")
