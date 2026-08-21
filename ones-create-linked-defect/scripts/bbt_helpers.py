# -*- coding: utf-8 -*-
"""兼容入口：公共黑盒测试辅助函数已迁移至 qa_skill_common。

保持既有用法不变：`from bbt_helpers import ...`。
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qa_skill_common.bbt_helpers import *  # noqa: F401,F403


if __name__ == "__main__":
    print("bbt_helpers 可用函数:")
    print("  connect / disconnect / attach_error_watchers / collect_toasts / error_report")
    print("  wait_visible / wait_until / wait_text / wait_button / wait_toast / retry / close_dialog")
    print("  table_columns / read_table_rows / snap / record_baseline / assert_new_target")
    print("  find_page / parse_import_template / recon_page_structure / recon_once")
