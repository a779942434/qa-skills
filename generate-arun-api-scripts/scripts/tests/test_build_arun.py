# -*- coding: utf-8 -*-
"""build_arun 配置外置回归：不把客户环境和内网地址写死在生成器里。"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import build_arun as B  # noqa: E402


class TestBuildArunSettings(unittest.TestCase):
    def test_constants_have_no_internal_registry_default(self):
        self.assertEqual(B.DUBBO["registry_center"]["address"], "")
        self.assertIsNone(B.API_STEP_TOP["project"])

    def test_api_step_uses_settings(self):
        settings = B.load_settings_from_dict({
            "project": 7,
            "dubbo": {"registry_center": {"address": "registry.test:21811"}},
        })
        step = B.build_api_step({"name": "查询", "url": "/query"}, settings=settings)
        self.assertEqual(step["project"], 7)
        self.assertEqual(step["data"]["dubbo"]["registry_center"]["address"], "registry.test:21811")

    def test_cli_requires_project_and_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "steps.json"
            spec.write_text(json.dumps([{"name": "查询", "url": "/query"}]), encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True), \
                 mock.patch.object(B, "load_settings", return_value=B.load_settings_from_dict({})):
                with self.assertRaises(SystemExit):
                    B.main([str(spec), "-o", "-"])

    def test_cli_reads_external_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "steps.json"
            settings = root / "settings.yaml"
            spec.write_text(json.dumps([{"name": "查询", "url": "/query"}]), encoding="utf-8")
            settings.write_text(
                "project: 7\ndubbo:\n  registry_center:\n    address: registry.test:21811\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                B.main([str(spec), "--settings", str(settings), "-o", "-", "--compact"])
            steps = json.loads(output.getvalue())
            self.assertEqual(steps[0]["project"], 7)
            self.assertEqual(steps[0]["data"]["dubbo"]["registry_center"]["address"], "registry.test:21811")


if __name__ == "__main__":
    unittest.main()
