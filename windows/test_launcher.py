#!/usr/bin/env python3
"""Small behavior tests for the Windows Stats launcher and phone QR."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

WINDOWS_DIR = Path(__file__).resolve().parent
ROOT_DIR = WINDOWS_DIR.parent
APP_DIR = ROOT_DIR / "app"
sys.path.insert(0, str(WINDOWS_DIR))
sys.path.insert(0, str(APP_DIR))
import launcher  # noqa: E402
import remote_qr_v109  # noqa: E402


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.returncode = exit_code
        self.pid = 12345

    def poll(self):
        return self.exit_code


class LauncherBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "data_dir": launcher.data_dir,
            "start_server": launcher.start_server,
            "wait_for_server": launcher.wait_for_server,
            "health_ok": launcher.health_ok,
            "launch_browser": launcher.launch_browser,
            "restart_request_stamp": launcher.restart_request_stamp,
            "sleep": launcher.time.sleep,
            "log": launcher.log,
        }
        launcher._SERVER = None
        launcher._BROWSER = None

    def tearDown(self):
        launcher.data_dir = self.originals["data_dir"]
        launcher.start_server = self.originals["start_server"]
        launcher.wait_for_server = self.originals["wait_for_server"]
        launcher.health_ok = self.originals["health_ok"]
        launcher.launch_browser = self.originals["launch_browser"]
        launcher.restart_request_stamp = self.originals["restart_request_stamp"]
        launcher.time.sleep = self.originals["sleep"]
        launcher.log = self.originals["log"]
        launcher._SERVER = None
        launcher._BROWSER = None

    def test_browser_close_exits_without_relaunch(self):
        server = FakeProcess(None)
        browser = FakeProcess(0)
        launches = []

        with tempfile.TemporaryDirectory() as temp:
            launcher.data_dir = lambda: Path(temp)
            launcher.start_server = lambda: server
            launcher.wait_for_server = lambda: True
            launcher.health_ok = lambda *args, **kwargs: True
            launcher.launch_browser = lambda: launches.append(browser) or browser
            launcher.restart_request_stamp = lambda path: None
            launcher.time.sleep = lambda seconds: None
            launcher.log = lambda message: None

            self.assertEqual(launcher.supervise(), 0)

        self.assertEqual(len(launches), 1, "closing the browser must not relaunch it")

    def test_missing_browser_exits_instead_of_looping(self):
        server = FakeProcess(None)

        with tempfile.TemporaryDirectory() as temp:
            launcher.data_dir = lambda: Path(temp)
            launcher.start_server = lambda: server
            launcher.wait_for_server = lambda: True
            launcher.health_ok = lambda *args, **kwargs: True
            launcher.launch_browser = lambda: None
            launcher.restart_request_stamp = lambda path: None
            launcher.time.sleep = lambda seconds: None
            launcher.log = lambda message: None

            self.assertEqual(launcher.supervise(), 1)


class RemoteQrTests(unittest.TestCase):
    def test_generate_uses_current_lan_address(self):
        original_lan = remote_qr_v109._lan_ipv4
        original_static = remote_qr_v109.STATIC_DIR
        original_output = remote_qr_v109.OUTPUT
        try:
            with tempfile.TemporaryDirectory() as temp:
                remote_qr_v109._lan_ipv4 = lambda: "192.168.50.25"
                remote_qr_v109.STATIC_DIR = Path(temp)
                remote_qr_v109.OUTPUT = Path(temp) / "remote-qr-v109.svg"

                self.assertEqual(
                    remote_qr_v109.remote_url(),
                    "http://192.168.50.25:8765/settings",
                )
                self.assertEqual(
                    remote_qr_v109.generate(),
                    "http://192.168.50.25:8765/settings",
                )
                svg = remote_qr_v109.OUTPUT.read_text(encoding="utf-8")
                self.assertIn("<svg", svg)
                self.assertIn("fill=\"#fff\"", svg)
        finally:
            remote_qr_v109._lan_ipv4 = original_lan
            remote_qr_v109.STATIC_DIR = original_static
            remote_qr_v109.OUTPUT = original_output

    def test_desktop_qr_double_click_opens_settings(self):
        script = (APP_DIR / "static" / "remote-qr-overlay-v110.js").read_text(encoding="utf-8")
        self.assertIn("pointer-events:auto", script)
        self.assertIn("addEventListener('dblclick'", script)
        self.assertIn("window.location.assign('/settings')", script)
        self.assertIn("Double-click to open Settings", script)


if __name__ == "__main__":
    unittest.main()
