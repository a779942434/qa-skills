# -*- coding: utf-8 -*-
"""兼容入口：MES 登录、导航和造数公共函数已迁移至 qa_skill_common。

保持既有用法不变：`from bbt_osd_common import ...`。
"""
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[0]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qa_skill_common.bbt_osd_common import *  # noqa: F401,F403
