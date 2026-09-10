# -*- coding: utf-8 -*-
"""兼容入口：MES 造数命令已迁移至 qa_skill_common。

原命令保持不变：`python scripts/bbt_osd_setup.py`。
"""
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[0]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qa_skill_common.bbt_osd_setup import main


if __name__ == "__main__":
    main()
