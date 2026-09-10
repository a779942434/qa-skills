# -*- coding: utf-8 -*-
"""兼容入口：DataGrip 数据源实现已迁移至 qa_skill_common。

原命令保持不变：`python scripts/datagrip_datasources.py <list|info|query|tables> ...`。
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qa_skill_common.datagrip_datasources import *  # noqa: F401,F403
from qa_skill_common.datagrip_datasources import main  # noqa: F401


if __name__ == "__main__":
    main()
