# -*- coding: utf-8 -*-
"""兼容入口：MES 登录、导航和造数公共函数已迁移至 qa_skill_common。

保持既有用法不变：`from bbt_osd_common import ...`。
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qa_skill_common.bbt_osd_common import *  # noqa: F401,F403
