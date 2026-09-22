# -*- coding: utf-8 -*-
"""L1 离线单测：遥测过滤口径（G3）。

measure_context.py 在 tools/ 下（非包），用 importlib 按路径加载后再 patch
其模块级 SESSIONS_GLOB，验证「QA 命中 / 非 QA 过滤 / cwd 未知保留」三种情形。

运行：python3 -m unittest discover -s qa_skill_common/tests -t . -v
"""
import importlib.util
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
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("qa_measure_context",
                                               ROOT / "tools" / "measure_context.py")
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)


def _write_rollout(path: Path, cwd: str, tokens=1000, cached=900, output=10):
    lines = [
        json.dumps({"type": "session_meta", "payload": {"cwd": cwd}}),
        json.dumps({"type": "response_item", "payload": {"type": "function_call"}}),
        json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": tokens, "cached_input_tokens": cached,
                                  "output_tokens": output}}}}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestQaSessionDetection(unittest.TestCase):
    def test_tristate(self):
        self.assertTrue(mc._is_qa_session("/Users/x/qa-skills"))
        self.assertTrue(mc._is_qa_session("/Users/x/.codex/worktrees/0462/qa-skills"))
        self.assertFalse(mc._is_qa_session("/Users/x/kaoyan_app"))
        self.assertIsNone(mc._is_qa_session(""))
        self.assertIsNone(mc._is_qa_session(None))


class TestRunSessionsFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _run(self, only_qa=True):
        buf = io.StringIO()
        with mock.patch.object(mc, "SESSIONS_GLOB", str(self.dir / "*.jsonl")):
            with redirect_stdout(buf):
                rows = mc.run_sessions(only_qa=only_qa)
        return rows, buf.getvalue()

    def test_keeps_qa_and_unknown_drops_others(self):
        _write_rollout(self.dir / "qa.jsonl", "/Users/x/qa-skills")
        _write_rollout(self.dir / "other.jsonl", "/Users/x/kaoyan_app")
        _write_rollout(self.dir / "unknown.jsonl", "")
        rows, out = self._run(only_qa=True)
        self.assertEqual({r["file"] for r in rows}, {"qa.jsonl", "unknown.jsonl"})
        self.assertIn("cwd 未知保留 1 份", out)
        self.assertIn("命中 QA 1 份", out)

    def test_all_sessions_keeps_everything(self):
        _write_rollout(self.dir / "qa.jsonl", "/Users/x/qa-skills")
        _write_rollout(self.dir / "other.jsonl", "/Users/x/kaoyan_app")
        rows, out = self._run(only_qa=False)
        self.assertEqual({r["file"] for r in rows}, {"qa.jsonl", "other.jsonl"})
        self.assertIn("全部 2 份 rollout", out)

    def test_cwd_recorded_on_row(self):
        _write_rollout(self.dir / "qa.jsonl", "/Users/x/qa-skills")
        rows, _ = self._run(only_qa=True)
        self.assertEqual(rows[0]["cwd"], "/Users/x/qa-skills")


if __name__ == "__main__":
    unittest.main()
