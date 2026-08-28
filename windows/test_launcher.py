#!/usr/bin/env python3
"""Small behavior tests for the Windows Stats launcher and desktop UI."""
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
import windows_theme_editor_v122  # noqa: E402


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

    def test_installer_never_kills_the_ota_parent_tree(self):
        iss = (WINDOWS_DIR / "Stats.iss").read_text(encoding="utf-8")
        updater = (WINDOWS_DIR / "updater.py").read_text(encoding="utf-8")
        self.assertNotIn("taskkill /IM StatsLauncher.exe /T /F", iss)
        self.assertNotIn("taskkill /IM StatsServer.exe /T /F", iss)
        self.assertIn("windows-kiosk-browser.pid", iss)
        self.assertIn("taskkill /PID %P /T /F", iss)
        self.assertIn("/LOG=", updater)


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

    def test_production_settings_guard_cannot_spin_before_options_load(self):
        script = (APP_DIR / "static" / "production-coming-eventually.js").read_text(encoding="utf-8")
        self.assertIn("wholeOfficeOption", script)
        self.assertIn("if(!wholeOfficeOption) return false", script)
        self.assertIn("let applying=false", script)
        self.assertIn("let applyQueued=false", script)
        self.assertIn("new MutationObserver(scheduleApply)", script)
        self.assertNotIn("new MutationObserver(apply)", script)
        self.assertNotIn("observer.observe(document.documentElement", script)

    def test_settings_back_button_and_connection_examples(self):
        script = (APP_DIR / "static" / "settings-production-v107.js").read_text(encoding="utf-8")
        template = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")
        gates = (APP_DIR / "production_gates.py").read_text(encoding="utf-8")

        self.assertIn("← Back to Stats", script)
        self.assertIn("window.location.assign('/')", script)
        self.assertIn("Example: https://your-pod.online.tableau.com", script)
        self.assertIn("Example: your-site", script)
        self.assertIn("Example: stats-pat", script)
        self.assertIn("settings-production-v107.js", template)
        self.assertIn("_remove_compiled_connection_defaults", gates)
        self.assertIn('tableau_configured.DEFAULTS[key] = ""', gates)

    def test_windows_settings_use_sidebar_workspace(self):
        script = (APP_DIR / "static" / "windows-settings-sidebar-v121.js").read_text(encoding="utf-8")
        template = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")

        self.assertIn("const isWindows=/windows|win32|win64/i.test(platform);", script)
        self.assertIn("grid-template-columns:clamp(220px,20vw,280px) minmax(0,1fr)", script)
        self.assertIn("windowsSettingsNav", script)
        self.assertIn("windowsSettingsContent", script)
        self.assertIn("activateSection", script)
        self.assertIn('section.id!=="v110QrSection"', script)
        self.assertIn("max-width:1600px", script)
        self.assertIn("windows-settings-sidebar-v121.js", template)


class WindowsThemeEditorTests(unittest.TestCase):
    def test_transform_values_are_bounded(self):
        cleaned = windows_theme_editor_v122.clean_transform({
            "x": 999,
            "y": -999,
            "scale_x": 1,
            "scale_y": 900,
            "rotation": 720,
            "opacity": -5,
        })
        self.assertEqual(cleaned["x"], 300)
        self.assertEqual(cleaned["y"], -300)
        self.assertEqual(cleaned["scale_x"], 20)
        self.assertEqual(cleaned["scale_y"], 500)
        self.assertEqual(cleaned["rotation"], 180)
        self.assertEqual(cleaned["opacity"], 0)

    def test_visual_theme_editor_is_wired_into_windows_build(self):
        server_entry = (WINDOWS_DIR / "server_entry.py").read_text(encoding="utf-8")
        display = (APP_DIR / "templates" / "display.html").read_text(encoding="utf-8")
        settings = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")
        preview = (APP_DIR / "static" / "theme-editor-preview-v122.js").read_text(encoding="utf-8")
        runtime = (APP_DIR / "static" / "theme-transform-runtime-v122.js").read_text(encoding="utf-8")
        host = (APP_DIR / "static" / "windows-theme-visual-editor-v122.js").read_text(encoding="utf-8")

        self.assertIn("windows_theme_editor_v122.install(server.app, server.PUBLIC_ENDPOINTS)", server_entry)
        self.assertIn("theme-transform-runtime-v122.js", display)
        self.assertIn("theme-editor-preview-v122.js", display)
        self.assertLess(display.index("theme-editor-preview-v122.js"), display.index("tv-preview-v63.js"))
        self.assertIn("windows-theme-visual-editor-v122.js", settings)
        self.assertIn('addEventListener("dblclick"', preview)
        self.assertIn('addEventListener("contextmenu"', preview)
        self.assertIn('data-handle="rotate"', preview)
        self.assertIn("nwse-resize", preview)
        self.assertIn("Upload New Asset", preview)
        self.assertIn("Change Color", preview)
        self.assertIn("Opacity", preview)
        self.assertIn("Remove Asset", preview)
        self.assertIn("theme_editor_sample:true", preview)
        self.assertIn("assigned_team_id:teamId", preview)
        self.assertIn("/api/windows/theme-transforms/", preview)
        self.assertIn("StatsThemeTransforms", runtime)
        self.assertIn("te-transform-row", runtime)
        self.assertIn("StatsThemeEditorHost", host)
        self.assertIn('searchParams.set("themeEditor","1")', host)
        self.assertIn("↻ Sample", host)


if __name__ == "__main__":
    unittest.main()
