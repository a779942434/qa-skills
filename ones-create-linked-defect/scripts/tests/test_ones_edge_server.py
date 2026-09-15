# -*- coding: utf-8 -*-
"""ONES 常驻 Edge 监管器离线单测。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ones_edge_server as server  # noqa: E402
from qa_skill_common.session_helpers import CdpHealth, PersistentSession  # noqa: E402


def settings(tmp):
    return {
        "cdp_port": 9334,
        "ones_url": "https://ones.shuyilink.com",
        "edge": {"executable": "/fake/edge", "session_dir": str(tmp / "edge"), "headless": True},
        "logs_dir": str(tmp / "logs"),
    }


class TestOnesEdgeServer(unittest.TestCase):
    def setUp(self):
        self.tmp_obj = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_obj.name)
        self.settings = settings(self.tmp)

    def tearDown(self):
        self.tmp_obj.cleanup()

    def test_ensure_server_process_starts_supervisor_for_healthy_unmanaged(self):
        proc = mock.Mock(pid=2468)
        with mock.patch.object(server, "resolve_settings", return_value=self.settings), \
             mock.patch.object(server, "cdp_health", return_value=CdpHealth(True, "http://127.0.0.1:9334")), \
             mock.patch.object(server, "wait_cdp_healthy", return_value=CdpHealth(True, "http://127.0.0.1:9334")), \
             mock.patch.object(server.subprocess, "Popen", return_value=proc) as popen:
            started, healthy, _meta = server.ensure_server_process()
        self.assertTrue(started)
        self.assertTrue(healthy)
        popen.assert_called_once()

    def test_ensure_server_process_skips_when_supervisor_alive(self):
        meta = {"pid": 1357, "state": "running"}
        with mock.patch.object(server, "resolve_settings", return_value=self.settings), \
             mock.patch.object(server, "_read_server_meta", return_value=meta), \
             mock.patch.object(server, "_pid_alive", return_value=True), \
             mock.patch.object(server, "cdp_health", return_value=CdpHealth(True, "http://127.0.0.1:9334")), \
             mock.patch.object(server.subprocess, "Popen") as popen:
            started, healthy, _meta = server.ensure_server_process()
        self.assertFalse(started)
        self.assertTrue(healthy)
        popen.assert_not_called()

    def test_ensure_server_process_starts_supervisor_when_unhealthy(self):
        proc = mock.Mock(pid=2468)
        states = [CdpHealth(False, "http://127.0.0.1:9334", error="closed"), CdpHealth(True, "http://127.0.0.1:9334")]
        with mock.patch.object(server, "resolve_settings", return_value=self.settings), \
             mock.patch.object(server, "cdp_health", side_effect=states), \
             mock.patch.object(server, "wait_cdp_healthy", return_value=CdpHealth(True, "http://127.0.0.1:9334")), \
             mock.patch.object(server.subprocess, "Popen", return_value=proc) as popen:
            started, healthy, _meta = server.ensure_server_process(url="https://ones.example/task")
        self.assertTrue(started)
        self.assertTrue(healthy)
        cmd = popen.call_args.args[0]
        self.assertIn("ones_edge_server.py", cmd[1])
        self.assertIn("https://ones.example/task", cmd)

    def test_serve_restarts_when_cdp_becomes_unhealthy(self):
        old = PersistentSession("http://127.0.0.1:9334", self.tmp / "edge", started=True, managed=True)
        new = PersistentSession("http://127.0.0.1:9334", self.tmp / "edge", started=True, managed=True, pid=4321)
        with mock.patch.object(server, "resolve_settings", return_value=self.settings), \
             mock.patch.object(server, "_launch_managed_edge", return_value=old), \
             mock.patch.object(server, "cdp_health", return_value=CdpHealth(False, "http://127.0.0.1:9334", error="edge exited")), \
             mock.patch.object(server, "restart_persistent_session", return_value=new) as restart, \
             mock.patch.object(server, "_open_ones_page", return_value="https://ones.example"), \
             mock.patch.object(server, "stop_persistent_session"), \
             mock.patch.object(server.time, "sleep", side_effect=[None, KeyboardInterrupt]):
            rc = server.serve(health_interval=1, max_restarts=3)
        self.assertEqual(rc, 0)
        restart.assert_called_once()
        self.assertEqual(restart.call_args.kwargs["reason"], "edge exited")


if __name__ == "__main__":
    unittest.main(verbosity=2)
