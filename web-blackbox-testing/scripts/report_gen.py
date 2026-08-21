# -*- coding: utf-8 -*-
"""兼容入口：report_gen 实现已迁移至 qa_skill_common。

保持既有用法不变：`from report_gen import ...`。
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qa_skill_common.report_gen import *  # noqa: F401,F403


if __name__ == "__main__":
    print("report_gen 已迁移至 qa_skill_common，可用函数见 qa_skill_common/report_gen.py")
