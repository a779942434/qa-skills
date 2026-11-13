#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_skill_integrity.py 的回归测试：防止闸门自己被“修绿”。"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "check_skill_integrity.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("check_skill_integrity", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ci = load_tool()
        self.ci.ROOT = self.root

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def test_home_path_and_exemption(self):
        bad = self.write("skill/a.md", "path=/Users/alice/private\n")
        ok = self.write("skill/b.md", "path=/Users/x/test\n")
        problems = self.ci.check_sensitive([bad, ok], [])
        self.assertTrue(any("absolute-home-path" in p for p in problems))
        self.assertFalse(any("b.md" in p for p in problems))

    def test_task_url_and_credential_literal(self):
        url = self.write("skill/scripts/a.py", "URL='https://ones.shuyilink.com/project/#/team/2YPZxEgX/task/abc123'\n")
        cred = self.write("skill/scripts/b.py", "PASSWORD = 'hunter2secret'\n")
        env = self.write("skill/scripts/c.py", "token = init.get('token')\n")
        problems = self.ci.check_sensitive([url, cred, env], [])
        self.assertTrue(any("hardcoded-task-url" in p for p in problems))
        self.assertTrue(any("credential-literal" in p for p in problems))
        self.assertFalse(any("c.py" in p for p in problems))

    def test_links_relative_to_skill_root(self):
        skill = self.write("skill/SKILL.md", "[入口](scripts/run.py)\n[坏链](scripts/missing.py)\n")
        self.write("skill/scripts/run.py", "print('ok')\n")
        problems = self.ci.check_links([skill])
        self.assertTrue(any("missing-target" in p and "missing.py" in p for p in problems))
        self.assertFalse(any("run.py" in p for p in problems))

    def test_oneoff_detects_unreferenced_and_ignores_tests(self):
        script = self.write("skill/scripts/close_2086xx.py", "print('x')\n")
        referenced = self.write("skill/scripts/useful.py", "print('y')\n")
        skill = self.write("skill/SKILL.md", "跑 scripts/useful.py\n")
        ignored = self.write("skill/scripts/tests/test_useful.py", "print('z')\n")
        problems = self.ci.check_oneoff([script, referenced, ignored, skill])
        self.assertEqual(problems, ["skill/scripts/close_2086xx.py: oneoff:unreferenced-script"])


if __name__ == "__main__":
    unittest.main()
