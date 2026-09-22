# -*- coding: utf-8 -*-
"""单用例/批次执行闭环入口（实现见 qa_skill_common.case_cli）。

用法：
    python scripts/qa_case.py exec --steps steps.json --run-dir runs/<日期_功能> --label C07
    python scripts/qa_case.py run  --spec runs/<日期_功能>/run_all.py --resume
    python scripts/qa_case.py status --run-dir runs/<日期_功能>
    python scripts/qa_case.py report --run-dir runs/<日期_功能>

一次调用跑一批：stdout 只回单行 JSON 摘要（≤4KB），完整现场落
<run-dir>/cases/<label>.json。
"""
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[0]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qa_skill_common.case_cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
