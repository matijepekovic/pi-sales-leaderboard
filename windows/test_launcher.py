#!/usr/bin/env python3
"""Behavior tests for the Windows launcher and current Stats UI shell."""
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
from stats_core.windows import qr as remote_qr  # noqa: E402


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
        self.assertEqual(len(launches), 1)

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

    def test_kiosk_browser_pid_is_recorded_and_cleared(self):
        browser = FakeProcess(None)
        browser.pid = 45678
        with tempfile.TemporaryDirectory() as temp:
            launcher.data_dir = lambda: Path(temp)
            launcher.log = lambda message: None
            launcher.write_kiosk_browser_pid(browser)
            pid_file = Path(temp) / launcher.KIOSK_BROWSER_PID_NAME
            self.assertEqual(pid_file.read_text(encoding="ascii"), "45678")
            launcher.clear_kiosk_browser_pid()
            self.assertFalse(pid_file.exists())

    def test_installer_never_kills_ota_parent_tree(self):
        iss = (WINDOWS_DIR / "Stats.iss").read_text(encoding="utf-8")
        updater = (WINDOWS_DIR / "updater.py").read_text(encoding="utf-8")
        self.assertNotIn("taskkill /IM StatsLauncher.exe /T /F", iss)
        self.assertNotIn("taskkill /IM StatsServer.exe /T /F", iss)
        self.assertIn("windows-kiosk-browser.pid", iss)
        self.assertIn("taskkill /PID %P /T /F", iss)
        self.assertIn("/LOG=", updater)


class RemoteQrTests(unittest.TestCase):
    def test_generate_uses_current_lan_address(self):
        original_lan = remote_qr._lan_ipv4
        original_static = remote_qr.STATIC_DIR
        original_output = remote_qr.OUTPUT
        try:
            with tempfile.TemporaryDirectory() as temp:
                remote_qr._lan_ipv4 = lambda: "192.168.50.25"
                remote_qr.STATIC_DIR = Path(temp)
                remote_qr.OUTPUT = Path(temp) / "remote-qr.svg"
                self.assertEqual(remote_qr.remote_url(), "http://192.168.50.25:8765/settings")
                self.assertEqual(remote_qr.generate(), "http://192.168.50.25:8765/settings")
                self.assertIn("<svg", remote_qr.OUTPUT.read_text(encoding="utf-8"))
        finally:
            remote_qr._lan_ipv4 = original_lan
            remote_qr.STATIC_DIR = original_static
            remote_qr.OUTPUT = original_output


class CurrentUiOwnershipTests(unittest.TestCase):
    def test_settings_is_real_modular_shell(self):
        template = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")
        self.assertNotIn("settings/base.html", template)
        self.assertNotIn("data-screen-display.js", template)
        self.assertNotIn("windows-sidebar.js", template)
        for section in ("settingsData", "settingsFilters", "settingsScreens", "settingsDisplay"):
            self.assertIn(section, template)
        for script in ("runtime.js", "shell.js", "data.js", "filters.js", "screens.js", "display.js"):
            self.assertIn(f"/static/settings/{script}", template)

    def test_data_ui_owns_source_report_and_data_filter_workflow(self):
        script = (APP_DIR / "static" / "settings" / "data.js").read_text(encoding="utf-8")
        self.assertIn("/api/data/sources", script)
        self.assertIn("/api/data/reports", script)
        self.assertIn("Data Filters", script)
        self.assertIn("View Data", script)
        self.assertIn("Read Report Fields", script)
        self.assertIn("Test Pull", script)

    def test_filter_ui_is_user_manageable_and_testable(self):
        script = (APP_DIR / "static" / "settings" / "filters.js").read_text(encoding="utf-8")
        self.assertIn("/api/filters", script)
        self.assertIn("/api/filters/preview", script)
        self.assertIn("actual pulled Report data", script)
        self.assertIn("Save Filter", script)
        self.assertIn("Test Filter", script)

    def test_screen_ui_assigns_filters_and_live_previews(self):
        script = (APP_DIR / "static" / "settings" / "screens.js").read_text(encoding="utf-8")
        self.assertIn("filter_ids", script)
        self.assertIn("+ Create Filter", script)
        self.assertIn("/api/screens/preview", script)
        self.assertNotIn("display_filter_mappings", script)
        self.assertNotIn("filter_values", script)

    def test_display_is_generic_screen_renderer(self):
        template = (APP_DIR / "templates" / "display.html").read_text(encoding="utf-8")
        script = (APP_DIR / "static" / "display" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/static/display/app.js", template)
        self.assertNotIn("custom-screen.js", template)
        self.assertIn("/api/display/render", script)
        self.assertIn("payload.sections", script)
        self.assertNotIn("whole_office", script)
        self.assertNotIn("team_vs_team", script)
        self.assertNotIn("product_close", script)


if __name__ == "__main__":
    unittest.main()
