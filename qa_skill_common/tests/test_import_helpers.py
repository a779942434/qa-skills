import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from qa_skill_common.import_helpers import (  # noqa: E402
    ImportCase, parse_failed_import, validate_import_result, write_import_workbook,
)


class TestImportHelpers(unittest.TestCase):
    def test_mixed_workbook_and_failed_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.xlsx"
            write_import_workbook(
                path,
                ["产品编号", "开工日期", "失败内容"],
                [ImportCase("ok", "正常", ["P1", "2026-09-15", ""]),
                 ImportCase("bad", "缺日期", ["P1", "", "开工日期不能为空"])],
            )
            rows = parse_failed_import(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[1]["_message"], "开工日期不能为空")

    def test_validate_partial_success(self):
        result = {
            "response_data": {
                "successCount": "1",
                "failedCount": "2",
                "failedMessageList": [
                    {"msg": "开工日期不能晚于完工日期"},
                    {"msg": "供应商编号不存在或未启用"},
                ],
            }
        }
        checked = validate_import_result(
            result, expected_success=1, expected_failed=2,
            required_messages=["供应商编号不存在"],
        )
        self.assertTrue(checked["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
