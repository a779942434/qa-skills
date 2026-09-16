# -*- coding: utf-8 -*-
"""L1 离线单测：持久 MES 会话的启动、健康检查、恢复和关闭策略。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_skill_common import session_helpers as S  # noqa: E402


def health(ok=True, error="", browser="Edge/Test"):
    return S.CdpHealth(ok=ok, cdp_url="http://127.0.0.1:9222", browser=browser, error=error)


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
        self.returncode = -9


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestPersistentSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session_dir = Path(self.tmp.name) / "mes-session"

    def tearDown(self):
        self.tmp.cleanup()

    def test_reuses_existing_cdp_without_spawn(self):
        with mock.patch.object(S, "cdp_health", return_value=health()), \
             mock.patch.object(S.subprocess, "Popen") as popen:
            sess = S.start_persistent_session(session_dir=self.session_dir)
        self.assertFalse(sess.started)
        self.assertIsNone(sess.process)
        popen.assert_not_called()

    def test_cdp_health_checks_version_and_target_list(self):
        responses = [
            FakeResponse({"Browser": "Edge/120", "webSocketDebuggerUrl": "ws://127.0.0.1/devtools"}),
            FakeResponse([{"type": "page"}, {"type": "service_worker"}]),
        ]
        with mock.patch.object(S.urllib.request, "urlopen", side_effect=responses):
            got = S.cdp_health("http://127.0.0.1:9222")
        self.assertTrue(got.ok)
        self.assertEqual(got.browser, "Edge/120")
        self.assertEqual(got.target_count, 2)

    def test_spawns_persistent_browser_and_waits_cdp(self):
        proc = FakeProc()
        states = iter([health(False, "not ready"), health(True)])
        with mock.patch.object(S, "cdp_health", side_effect=lambda *a, **k: next(states)), \
             mock.patch.object(S, "_port_open", return_value=False), \
             mock.patch.object(S, "_browser_executable", return_value="/fake/chrome"), \
             mock.patch.object(S.subprocess, "Popen", return_value=proc) as popen:
            sess = S.start_persistent_session(session_dir=self.session_dir, startup_timeout=2)
        self.assertTrue(sess.started)
        self.assertIs(sess.process, proc)
        args = popen.call_args.args[0]
        self.assertIn("--remote-debugging-port=9222", args)
        self.assertIn(f"--user-data-dir={self.session_dir}", args)
        self.assertIn("--headless=new", args)
        self.assertIn("--disable-session-crashed-bubble", args)
        self.assertIn("--hide-crash-restore-bubble", args)
        self.assertIn("--disable-crash-reporter", args)
        self.assertIn("--disable-breakpad", args)
        self.assertIn("--noerrdialogs", args)

    def test_unhealthy_unknown_port_is_not_killed(self):
        with mock.patch.object(S, "cdp_health", return_value=health(False, "stuck")), \
             mock.patch.object(S, "_port_open", return_value=True), \
             mock.patch.object(S, "_read_session_meta", return_value={}), \
             mock.patch.object(S, "_stop_recorded_unhealthy_session", return_value=False), \
             mock.patch.object(S, "_terminate_pid") as terminate, \
             mock.patch.object(S.time, "sleep"):
            with self.assertRaises(RuntimeError):
                S.start_persistent_session(session_dir=self.session_dir, startup_timeout=1)
        terminate.assert_not_called()

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
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "session.json").write_text(json.dumps(meta), encoding="utf-8")
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

    def test_restart_preserves_session_dir_and_records_reason(self):
        old = S.PersistentSession("http://127.0.0.1:9222", self.session_dir,
                                   started=True, managed=True, restarts=2)
        new = S.PersistentSession("http://127.0.0.1:9222", self.session_dir,
                                   started=True, managed=True, pid=9876)
        with mock.patch.object(S, "stop_persistent_session", return_value=True), \
             mock.patch.object(S, "_port_open", return_value=False), \
             mock.patch.object(S, "start_persistent_session", return_value=new) as start, \
             mock.patch.object(S, "cdp_health", return_value=health()):
            got = S.restart_persistent_session(old, reason="browser crash")
        self.assertIs(got, new)
        self.assertEqual(got.restarts, 3)
        self.assertEqual(got.recoveries_this_run, 1)
        self.assertEqual(got.last_health_error, "browser crash")
        self.assertEqual(start.call_args.kwargs["session_dir"], self.session_dir)
        meta = S._read_session_meta(self.session_dir)
        self.assertEqual(meta["restarts"], 3)
        self.assertEqual(meta["last_restart_reason"], "browser crash")

    def test_ensure_mes_session_restarts_after_cdp_disconnect(self):
        sessions = [
            (object(), object(), object(), object()),
            (object(), object(), object(), object()),
        ]
        persistent = S.PersistentSession("http://127.0.0.1:9222", self.session_dir,
                                         started=True, managed=True)
        restarted = S.PersistentSession("http://127.0.0.1:9222", self.session_dir,
                                        started=True, managed=True, restarts=1)
        connect = mock.Mock(side_effect=[RuntimeError("connect_over_cdp websocket closed"), sessions[1]])
        with mock.patch.object(S, "start_persistent_session", return_value=persistent), \
             mock.patch.object(S, "connect_persistent_session", connect), \
             mock.patch.object(S, "restart_persistent_session", return_value=restarted), \
             mock.patch.object(S, "cdp_health", return_value=health(False, "closed")):
            got = S.ensure_mes_session(login=False, restart_attempts=1)
        self.assertEqual(got, (restarted, *sessions[1]))
        self.assertEqual(connect.call_count, 2)

    def test_ensure_mes_session_rejects_ones_port_and_user_profile(self):
        with self.assertRaises(RuntimeError):
            S.ensure_mes_session(cdp_port=9334, login=False)
        with self.assertRaises(RuntimeError):
            S.ensure_mes_session(
                session_dir=Path.home() / "Library" / "Application Support" / "Google" / "Chrome",
                login=False,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
