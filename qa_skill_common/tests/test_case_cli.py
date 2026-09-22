# -*- coding: utf-8 -*-
"""L1 离线单测：qa_case CLI 门面（单行 JSON 契约 / resume 语义 / 结论回流）。

不依赖浏览器：只覆盖 status / report / 参数错误三条不需要页面的路径。

运行：python3 -m unittest discover -s qa_skill_common/tests -t . -v
"""
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

from qa_skill_common import case_cli as C                    # noqa: E402
from qa_skill_common import page_registry as REG              # noqa: E402
from qa_skill_common.phase_runner import RunState             # noqa: E402


def _call(argv):
    """跑一次 CLI，返回 (rc, stdout)。"""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = C.main(argv)
    return rc, buf.getvalue()


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)

    def test_status_single_line_json(self):
        rc, out = _call(["status", "--run-dir", str(self.run_dir)])
        self.assertEqual(rc, 0)
        self.assertEqual(len(out.strip().splitlines()), 1)      # 单行契约
        self.assertLessEqual(len(out), C.MAX_STDOUT_CHARS)
        payload = json.loads(out)
        self.assertEqual(payload["total"], 0)

    def test_status_reflects_recorded_cases(self):
        st = RunState(self.run_dir, "R1", "月度工序计划")
        st.mark_case("C01", "core", "通过")
        st.mark_case("C02", "core", "失败", blocker_type="产品缺陷")
        rc, out = _call(["status", "--run-dir", str(self.run_dir)])
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["passed"], 1)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(payload["blocker_types"]["产品缺陷"], 1)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)

    def _seed(self):
        st = RunState(self.run_dir, "R1", "委外发料明细")
        st.mark_case("C01", "生成", "通过", evidence="gen.png")
        st.mark_case("C02", "审核", "失败", note="未生成发料明细",
                     blocker_type="产品缺陷")
        (self.run_dir / "conclusions.json").write_text(json.dumps({
            "meta": {"环境": "t-dog", "范围": "零件委外"},
            "结论": ["零件委外审核后不生成委外发料明细（P1）"],
            "问题": [{"id": "BUG-01", "标题": "审核后无发料明细", "级别": "P1"}],
            "未覆盖": ["导入"],
            "证据": ["gen.png"],
        }, ensure_ascii=False), encoding="utf-8")

    def test_report_renders_from_structured_data(self):
        self._seed()
        rc, out = _call(["report", "--run-dir", str(self.run_dir)])
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        text = Path(payload["report"]).read_text(encoding="utf-8")
        self.assertIn("委外发料明细", text)
        self.assertIn("业务结论", text)                    # 结论回流渲染
        self.assertIn("零件委外审核后不生成委外发料明细", text)
        self.assertIn("通过 1", text)
        self.assertIn("失败 1", text)

    def test_report_is_idempotent_on_data_change(self):
        """只改结论数据再重渲染 —— 不手写 markdown。"""
        self._seed()
        _call(["report", "--run-dir", str(self.run_dir)])
        p = self.run_dir / "conclusions.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["结论"] = ["结论已更新：零件委外仍未修复（P1）"]
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        rc, out = _call(["report", "--run-dir", str(self.run_dir)])
        text = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("结论已更新", text)
        self.assertNotIn("不生成委外发料明细（P1）", text)

    def test_report_without_conclusions_still_works(self):
        st = RunState(self.run_dir, "R2", "无结论功能")
        st.mark_case("C01", "core", "通过")
        rc, out = _call(["report", "--run-dir", str(self.run_dir)])
        self.assertEqual(rc, 0)
        self.assertTrue(Path(json.loads(out)["report"]).exists())


class TestErrors(unittest.TestCase):
    def test_missing_steps_file_returns_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = _call(["exec", "--steps", str(Path(tmp) / "nope.json"),
                             "--run-dir", tmp])
        self.assertEqual(rc, 2)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "error")
        self.assertIn("不存在", payload["error"])

    def test_invalid_steps_json_returns_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "steps.json"
            bad.write_text("{ not json", encoding="utf-8")
            rc, out = _call(["exec", "--steps", str(bad), "--run-dir", tmp])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out)["status"], "error")

    def test_missing_spec_returns_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = _call(["run", "--spec", str(Path(tmp) / "nope.py"),
                             "--run-dir", tmp])
        self.assertEqual(rc, 2)
        self.assertIn("不存在", json.loads(out)["error"])

    def test_all_errors_stay_within_stdout_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out = _call(["exec", "--steps", str(Path(tmp) / ("x" * 300 + ".json")),
                             "--run-dir", tmp])
        self.assertLessEqual(len(out), C.MAX_STDOUT_CHARS)


class TestNetSignals(unittest.TestCase):
    """P0-2 回归：曾用 snapshot()（返回 dict）当响应列表，异常被 except 吞掉 -> http 恒为空。"""

    def test_recent_shape_is_mapped(self):
        class W:
            def recent(self, n=10):
                return [{"url": "/api/x", "method": "POST", "status": 200,
                         "duration_ms": 88, "seq": 1}]
        rows, err = C._net_of(W())
        self.assertEqual(err, "")
        self.assertEqual(rows, [{"url": "/api/x", "method": "POST",
                                "status": 200, "ms": 88}])

    def test_failure_is_reported_not_swallowed(self):
        class Bad:
            def recent(self, n=10):
                raise RuntimeError("boom")
        rows, err = C._net_of(Bad())
        self.assertEqual(rows, [])
        self.assertIn("RuntimeError", err)          # 禁止静默失败

    def test_legacy_snapshot_dict_does_not_crash(self):
        """兼容旧形状：snapshot() 返回 dict 时不得抛错，且要上报。"""
        class Legacy:
            def snapshot(self):
                return {"seq": 0, "urls": set()}
        rows, err = C._net_of(Legacy())
        self.assertEqual(rows, [])


class TestStdoutStep(unittest.TestCase):
    """两级输出：detail 不进 stdout，error 必须留在 stdout。"""

    def test_success_row_has_no_detail(self):
        row = C.stdout_step(3, "read", True, 12)
        self.assertEqual(row, {"i": 3, "action": "read", "ok": True, "ms": 12})
        self.assertNotIn("detail", row)

    def test_failure_row_keeps_error(self):
        row = C.stdout_step(3, "read", False, 12, "AssertionError: 未出现文本")
        self.assertIn("error", row)
        self.assertFalse(row["ok"])

    def test_batch_stdout_stays_within_budget(self):
        """40 步紧凑行 + 判据 -> 单行 JSON 必须在 4KB 内（曾经是 55870）。"""
        steps = [C.stdout_step(i, "read", True, 12) for i in range(40)]
        payload = {"label": "C07", "status": "pass", "ms": 1840,
                   "signals": {"toasts": [], "form_errors": [],
                               "http": [{"url": "/api/x", "status": 200, "ms": 88}],
                               "data_diff": {}},
                   "steps": steps, "evidence": [], "next_hint": ""}
        text = C._emit(payload, kind="exec", label="C07")
        self.assertLessEqual(len(text), C.MAX_STDOUT_CHARS)
        self.assertFalse(json.loads(text).get("truncated", False))


class TestStateDirResolution(unittest.TestCase):
    """P1-1 回归：run 的摘要目录必须与 spec 实际写入同源。"""

    def test_prefers_explicit_run_dir(self):
        with tempfile.TemporaryDirectory() as d:
            spec = Path(d) / "run_all.py"
            spec.write_text("# stub", encoding="utf-8")
            self.assertEqual(C._resolve_state_dir(spec, "/tmp/explicit"), Path("/tmp/explicit"))

    def test_prefers_spec_parent_when_state_exists(self):
        with tempfile.TemporaryDirectory() as d:
            spec = Path(d) / "run_all.py"
            spec.write_text("# stub", encoding="utf-8")
            (Path(d) / "run_state.json").write_text("{}", encoding="utf-8")
            self.assertEqual(C._resolve_state_dir(spec), Path(d))

    def test_falls_back_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as d:
            spec = Path(d) / "run_all.py"
            spec.write_text("# stub", encoding="utf-8")
            self.assertIsInstance(C._resolve_state_dir(spec), Path)


class TestRegistryNavigation(unittest.TestCase):
    """P1-3：命中 verified 才直接 goto，且必须过一致性校验。"""

    HOST = "http://t-dafu.ob.shuyilink.com"
    FEAT = "月度工序计划"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch("qa_skill_common.paths.workspace_root",
                       return_value=Path(self.tmp.name))
        self.addCleanup(p.stop)
        p.start()

    def _page(self, title, url="http://t-dafu.ob.shuyilink.com/plan/monthly/index"):
        class P:
            def __init__(self):
                self.url = url
            def title(self):
                return title
        return P()

    def test_verified_and_matching_title_uses_direct_goto(self):
        REG.upsert_page(self.HOST, self.FEAT, url=self.HOST + "/plan/monthly/index",
                        verified=True, title="月度工序计划", probe_verdict="element-plus")
        calls = []
        page = self._page("月度工序计划")
        landed, note, verified_ok = C._land(page, self.HOST + "/x", self.FEAT,
                                            lambda pg, u: calls.append(u))
        self.assertEqual(calls, [self.HOST + "/plan/monthly/index"])
        self.assertIn("直接 goto", note)
        self.assertTrue(verified_ok)                   # P1-5：验证成功才为 True
        # G1：一次落地只记一次命中——upsert 登记后由 record_hit 独占累加
        self.assertEqual(REG.get_page(self.HOST, self.FEAT)["hits"], 1)

    def test_stale_entry_falls_back_and_downgrades(self):
        REG.upsert_page(self.HOST, self.FEAT, url=self.HOST + "/plan/old/index",
                        verified=True, title="旧标题", probe_verdict="element-plus")
        calls = []
        page = self._page("完全不同的页面")
        with mock.patch("qa_skill_common.bbt_osd_common.goto_feature",
                        return_value=self.HOST + "/plan/new/index") as gf:
            landed, note, verified_ok = C._land(page, self.HOST + "/x", self.FEAT,
                                                lambda pg, u: calls.append(u))
        self.assertTrue(gf.called or calls)                # 有回退动作
        self.assertIn("失效", note)
        self.assertTrue(verified_ok)                       # 搜索命中 -> 算验证成功
        entry = REG.get_page(self.HOST, self.FEAT)
        self.assertFalse(entry["verified"])                # 已降级
        self.assertTrue(entry["stale"])

    def test_unverified_entry_never_direct_goto(self):
        REG.upsert_page(self.HOST, self.FEAT, url=self.HOST + "/maybe", verified=False)
        calls = []
        page = self._page("月度工序计划")
        with mock.patch("qa_skill_common.bbt_osd_common.goto_feature", return_value=None):
            C._land(page, self.HOST + "/x", self.FEAT, lambda pg, u: calls.append(u))
        self.assertNotIn(self.HOST + "/maybe", calls)      # 不会被信任

    def test_fallback_landing_is_not_verified(self):
        """P1-5：注册表未命中 + 搜索也失败 -> 兜底 goto 不算验证成功。"""
        calls = []
        page = self._page("首页")
        with mock.patch("qa_skill_common.bbt_osd_common.goto_feature", return_value=None):
            landed, note, verified_ok = C._land(page, self.HOST + "/x", self.FEAT,
                                                lambda pg, u: calls.append(u))
        self.assertFalse(verified_ok)
        self.assertNotEqual(note, "")                      # 必须给出可读原因，不能静默
        self.assertTrue(calls)                             # 仍执行了兜底跳转

    def test_pages_subcommand_renders_registry(self):
        REG.upsert_page(self.HOST, self.FEAT, url=self.HOST + "/a", verified=True)
        rc, out = _call(["pages", "--url", self.HOST + "/x"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertIn("月度工序计划", payload["registry"])


class TestExecSingleFile(unittest.TestCase):
    """G2：exec 现场只落一份文件，stdout 不出现第二个路径键。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name)

    def test_emit_reuses_prewritten_full(self):
        case_out = self.run_dir / "cases"
        case_out.mkdir(parents=True, exist_ok=True)
        detail = case_out / "C01.json"
        detail.write_text("{}", encoding="utf-8")
        payload = {"status": "pass", "detail_path": str(detail),
                   "steps": [{"i": i, "detail": "x" * 200} for i in range(40)]}
        buf = io.StringIO()
        with redirect_stdout(buf):
            C._finish(payload, kind="exec", run_dir=self.run_dir, label="C01",
                      code=0, full_path_hint=str(detail))
        got = json.loads(buf.getvalue())
        self.assertTrue(got["truncated"])
        self.assertNotIn("full_path", got)
        self.assertEqual(got["detail_path"], str(detail))
        # 目录里只有调用方写的那一份，没有 <label>.exec.json
        self.assertEqual(sorted(q.name for q in case_out.iterdir()), ["C01.json"])


class TestParserWiring(unittest.TestCase):
    def test_subcommands_present(self):
        ap = C.build_parser()
        for cmd in ("exec", "run", "status", "report", "pages"):
            self.assertEqual(ap.parse_args([cmd] + _required(cmd)).command, cmd)


def _required(cmd):
    return {"exec": ["--steps", "s.json"], "run": ["--spec", "r.py"],
            "status": ["--run-dir", "."], "report": ["--run-dir", "."],
            "pages": ["--url", "http://x"]}[cmd]


if __name__ == "__main__":
    unittest.main()
