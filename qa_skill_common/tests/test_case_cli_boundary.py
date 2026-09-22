# -*- coding: utf-8 -*-
"""L1 静态断言：case_cli 必须只是 phase_runner 的门面，不得自建第二套状态管理。

背景（计划 P1-2）：SKILL 自己禁止「另写平行替代脚本」，而 phase_runner 已
持有检查点/恢复/数据台账。若 case_cli 长出第二套状态读写，纪律即失效。
所以这里用**静态断言**把边界钉死：

  1. case_cli 源码不得出现 `run_state.json` / `data_ledger.json` 字面量；
  2. 不得直接对这两个文件 open()/json.dump()；
  3. 状态一律经 RunState / PhaseRunner 公共接口（断言确实引用了它们）。

运行：python3 -m unittest discover -s qa_skill_common/tests -t . -v
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASE_CLI = ROOT / "qa_skill_common/case_cli.py"
FORBIDDEN_LITERALS = ("run_state.json", "data_ledger.json", "run_state", "data_ledger")
STATE_FILES = ("run_state.json", "data_ledger.json")


def _source() -> str:
    return CASE_CLI.read_text(encoding="utf-8")


def _strip_comments_and_docstring(src: str) -> str:
    """去掉注释与字符串文档，只留可执行代码（避免把注释里的说明也算违规）。"""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    src = re.sub(r"(?m)^\s*#.*$", "", src)
    src = re.sub(r"(?m)\s+#.*$", "", src)
    return src


class TestNoDirectStateAccess(unittest.TestCase):
    def test_no_state_file_literals_in_source(self):
        src = _source()
        for bad in STATE_FILES:
            self.assertNotIn(
                bad, src,
                "case_cli.py 出现 {!r}：状态必须经 RunState/PhaseRunner，"
                "不得直接触碰状态文件".format(bad))

    def test_no_open_or_write_on_state_paths_in_code(self):
        code = _strip_comments_and_docstring(_source())
        for bad in FORBIDDEN_LITERALS:
            self.assertNotIn(bad, code)
        # 不得自己实现状态落盘
        self.assertNotRegex(code, r"def\s+save\s*\(",
                            "case_cli 不应自建 save()：状态落盘归 RunState")

    def test_uses_public_interfaces(self):
        src = _source()
        self.assertIn("RunState", src, "应经 RunState 读状态")
        self.assertIn("results_for_report", src, "报告数据应取自 RunState 公共接口")


class TestEntrypointsDelegate(unittest.TestCase):
    SKILLS = ("web-blackbox-testing", "ones-create-linked-defect")

    def test_entry_scripts_exist_and_delegate(self):
        for skill in self.SKILLS:
            entry = ROOT / skill / "scripts/qa_case.py"
            self.assertTrue(entry.exists(), "缺少入口 {}".format(entry))
            src = entry.read_text(encoding="utf-8")
            self.assertIn("qa_skill_common.case_cli", src)
            self.assertIn("main", src)


class TestFaqCaseCliImports(unittest.TestCase):
    def test_module_imports_without_playwright_installed_side_effects(self):
        """import 阶段不应启动浏览器/读写状态（懒加载）。"""
        import importlib

        mod = importlib.import_module("qa_skill_common.case_cli")
        self.assertTrue(hasattr(mod, "main"))
        self.assertTrue(hasattr(mod, "cmd_exec"))


if __name__ == "__main__":
    unittest.main()
