import sys
import unittest
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from qa_skill_common.data_factory import (  # noqa: E402
    DataRecipe, make_batch_id, make_numbered_codes, validate_recipe,
)


class TestDataFactory(unittest.TestCase):
    def test_batch_and_codes_are_stable_in_shape(self):
        batch = make_batch_id("委外", now=datetime(2026, 9, 15), short=True)
        self.assertTrue(batch.startswith("委外-20260915-"))
        codes = make_numbered_codes(batch, "S", 2)
        self.assertEqual(codes, [batch + "-S-01", batch + "-S-02"])

    def test_recipe_requires_all_preconditions(self):
        recipe = DataRecipe("disabled-product-import", requires=("disabled_product", "enabled_route"))
        result = validate_recipe(recipe, lambda key: key == "disabled_product")
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"], ["enabled_route"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
