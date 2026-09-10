# -*- coding: utf-8 -*-
"""兼容入口：通用主子表侦察实现已迁移至 qa_skill_common。

原命令保持不变：`python scripts/recon-generic/recon_subtables.py --url <页面URL> --max-rows 5`。
"""
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qa_skill_common.recon_generic.recon_subtables import main


if __name__ == "__main__":
    main()
