import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from qa_skill_common.field_contracts import default_registry  # noqa: E402


class TestFieldContracts(unittest.TestCase):
    def test_alias_and_api_mapping(self):
        reg = default_registry()
        item = reg.resolve("委外计划排产", "开始时间")
        self.assertIsNotNone(item)
        self.assertEqual(item.api_field, "queryStartTime")
        self.assertEqual(item.control, "date")

    def test_query_type_mapping(self):
        item = default_registry().resolve("委外计划排产", "查询条件")
        self.assertIn("1=完工日期", item.value_format)


if __name__ == "__main__":
    unittest.main(verbosity=2)
