# -*- coding: utf-8 -*-
"""L1 离线单测：持久 MES 会话的启动、复用和关闭策略。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import session_helpers as S  # noqa: E402


class FakeProc:
    def __init__(self, pid=1234):
        self.pid = pid
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.killed = True


class TestPersistentSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session_dir = Path(self.tmp.name) / "mes-session"

    def tearDown(self):
        self.tmp.cleanup()

    def test_reuses_existing_cdp_without_spawn(self):
        with mock.patch.object(S, "_cdp_ready", return_value=True), \
             mock.patch.object(S.subprocess, "Popen") as popen:
            sess = S.start_persistent_session(session_dir=self.session_dir)
        self.assertFalse(sess.started)
        self.assertIsNone(sess.process)
        popen.assert_not_called()

    def test_spawns_persistent_browser_and_waits_cdp(self):
        proc = FakeProc()
        ready = iter([False, True])
        with mock.patch.object(S, "_cdp_ready", side_effect=lambda *a, **k: next(ready)), \
             mock.patch.object(S, "_browser_executable", return_value="/fake/chrome"), \
             mock.patch.object(S.subprocess, "Popen", return_value=proc) as popen:
            sess = S.start_persistent_session(session_dir=self.session_dir, startup_timeout=2)
        self.assertTrue(sess.started)
        self.assertIs(sess.process, proc)
        args = popen.call_args.args[0]
        self.assertIn("--remote-debugging-port=9222", args)
        self.assertIn(f"--user-data-dir={self.session_dir}", args)
        self.assertIn("--headless=new", args)

    def test_stop_only_kills_session_started_by_runner(self):
        proc = FakeProc()
        reused = S.PersistentSession("http://127.0.0.1:9222", self.session_dir, process=proc, started=False)
        self.assertFalse(S.stop_persistent_session(reused))
        self.assertFalse(proc.terminated)
        started = S.PersistentSession("http://127.0.0.1:9222", self.session_dir, process=proc, started=True, managed=True)
        self.assertTrue(S.stop_persistent_session(started))
        self.assertTrue(proc.terminated)

    def test_stop_reused_managed_session_terminates_recorded_pid(self):
        meta = {"managed": True, "pid": 4321, "cdp_url": "http://127.0.0.1:9222"}
        (self.session_dir).mkdir(parents=True, exist_ok=True)
        (self.session_dir / "session.json").write_text(__import__("json").dumps(meta), encoding="utf-8")
        reused = S.PersistentSession("http://127.0.0.1:9222", self.session_dir, pid=4321, managed=True)
        with mock.patch.object(S, "_terminate_pid", return_value=True) as kill:
            self.assertTrue(S.stop_persistent_session(reused))
        kill.assert_called_once()
        self.assertFalse((self.session_dir / "session.json").exists())

    def test_connect_persistent_session_delegates_to_connect_session(self):
        sentinel = (1, 2, 3, 4)
        with mock.patch.object(S, "connect_session", return_value=sentinel) as conn:
            got = S.connect_persistent_session("http://127.0.0.1:9222", url_contains="dog")
        self.assertEqual(got, sentinel)
        conn.assert_called_once_with(cdp_url="http://127.0.0.1:9222", url_contains="dog")


if __name__ == "__main__":
    unittest.main(verbosity=2)
