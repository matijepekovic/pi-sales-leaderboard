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
from stats_core.windows import qr as remote_qr  # noqa: E402
from stats_core.windows import theme_editor as windows_theme_editor  # noqa: E402


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
        original_lan = remote_qr._lan_ipv4
        original_static = remote_qr.STATIC_DIR
        original_output = remote_qr.OUTPUT
        try:
            with tempfile.TemporaryDirectory() as temp:
                remote_qr._lan_ipv4 = lambda: "192.168.50.25"
                remote_qr.STATIC_DIR = Path(temp)
                remote_qr.OUTPUT = Path(temp) / "remote-qr-v109.svg"

                self.assertEqual(
                    remote_qr.remote_url(),
                    "http://192.168.50.25:8765/settings",
                )
                self.assertEqual(
                    remote_qr.generate(),
                    "http://192.168.50.25:8765/settings",
                )
                svg = remote_qr.OUTPUT.read_text(encoding="utf-8")
                self.assertIn("<svg", svg)
                self.assertIn("fill=\"#fff\"", svg)
        finally:
            remote_qr._lan_ipv4 = original_lan
            remote_qr.STATIC_DIR = original_static
            remote_qr.OUTPUT = original_output

    def test_desktop_qr_double_click_opens_settings(self):
        script = (APP_DIR / "static" / "display" / "remote-qr-overlay.js").read_text(encoding="utf-8")
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

    def test_settings_shell_and_data_workspace_are_wired(self):
        shell = (APP_DIR / "static" / "settings" / "production.js").read_text(encoding="utf-8")
        workspace = (APP_DIR / "static" / "settings" / "data-screen-display.js").read_text(encoding="utf-8")
        template = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")
        settings_service = (APP_DIR / "stats_core" / "services" / "settings.py").read_text(encoding="utf-8")

        self.assertIn("← Back to Stats", shell)
        self.assertIn("window.location.assign(\"/\")", shell)
        self.assertNotIn("tableau.com", shell.lower())
        self.assertIn("/static/settings/production.js", template)
        self.assertIn("/static/settings/data-screen-display.js", template)
        self.assertIn("/api/data/sources", workspace)
        self.assertIn("Display Data — Match Filters", workspace)
        self.assertIn("FEATURE_ACCESS", settings_service)
        self.assertIn('current["github_auto_update"] = False', settings_service)

    def test_windows_settings_use_sidebar_workspace(self):
        script = (APP_DIR / "static" / "settings" / "windows-sidebar.js").read_text(encoding="utf-8")
        template = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")

        self.assertIn("const isWindows=/windows|win32|win64/i.test(platform);", script)
        self.assertIn("grid-template-columns:clamp(220px,20vw,280px) minmax(0,1fr)", script)
        self.assertIn("windowsSettingsNav", script)
        self.assertIn("windowsSettingsContent", script)
        self.assertIn("activateSection", script)
        self.assertIn('section.id!=="v110QrSection"', script)
        self.assertIn("max-width:1600px", script)
        self.assertIn("/static/settings/windows-sidebar.js", template)

    def test_source_connection_ui_is_owned_by_data_workspace(self):
        workspace = (APP_DIR / "static" / "settings" / "data-screen-display.js").read_text(encoding="utf-8")
        template = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")
        server_entry = (WINDOWS_DIR / "server_entry.py").read_text(encoding="utf-8")
        platform = (APP_DIR / "stats_core" / "platform" / "windows.py").read_text(encoding="utf-8")

        self.assertIn("/static/settings/data-screen-display.js", template)
        self.assertNotIn("/static/settings/windows-tableau-login.js", template)
        self.assertIn('data-source-edit="server"', workspace)
        self.assertIn('data-source-edit="site"', workspace)
        self.assertIn('data-source-edit="pat_name"', workspace)
        self.assertIn("Test Connection", workspace)
        self.assertIn("/api/data/sources", workspace)
        self.assertNotIn("tableau_login.install", platform)
        self.assertIn("stats_core.bootstrap", server_entry)
        self.assertFalse((APP_DIR / "stats_core" / "windows" / "tableau_login.py").exists())

    def test_team_builder_uses_normalized_rep_contract(self):
        workflow = (APP_DIR / "static" / "settings" / "team-builder-workflow.js").read_text(encoding="utf-8")
        template = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")

        self.assertIn("/static/settings/team-builder-workflow.js", template)
        self.assertNotIn("/static/settings/tableau-team-members.js", template)
        self.assertFalse((APP_DIR / "static" / "settings" / "tableau-team-members.js").exists())
        self.assertIn("selectedMembers", workflow)
        self.assertIn("builderMembers", workflow)
        self.assertIn("Choose the team lead from the reps assigned", workflow)
        self.assertNotIn("Tableau", workflow)


class WindowsThemeEditorTests(unittest.TestCase):
    def test_transform_values_are_bounded(self):
        cleaned = windows_theme_editor.clean_transform({
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
        platform = (APP_DIR / "stats_core" / "platform" / "windows.py").read_text(encoding="utf-8")
        display = (APP_DIR / "templates" / "display.html").read_text(encoding="utf-8")
        settings = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")
        preview = (APP_DIR / "static" / "display" / "theme-editor-preview.js").read_text(encoding="utf-8")
        runtime = (APP_DIR / "static" / "display" / "theme-transforms.js").read_text(encoding="utf-8")
        host = (APP_DIR / "static" / "settings" / "theme-visual-editor.js").read_text(encoding="utf-8")
        intuitive = (APP_DIR / "static" / "display" / "theme-editor-controls.js").read_text(encoding="utf-8")
        help_ui = (APP_DIR / "static" / "settings" / "theme-editor-help.js").read_text(encoding="utf-8")
        policy = (APP_DIR / "static" / "display" / "theme-editor-data-policy.js").read_text(encoding="utf-8")
        stability = (APP_DIR / "static" / "settings" / "theme-stability.js").read_text(encoding="utf-8")

        self.assertIn("theme_editor.install(app, self.repos, public_endpoints)", platform)
        self.assertIn("stats_core.bootstrap", server_entry)
        self.assertNotIn("theme_editor.install", server_entry)
        self.assertIn("/static/display/theme-transforms.js", display)
        self.assertIn("/static/display/theme-editor-preview.js", display)
        self.assertIn("/static/display/theme-editor-data-policy.js", display)
        self.assertLess(display.index("theme-editor-preview.js"), display.index("theme-editor-data-policy.js"))
        self.assertLess(display.index("theme-editor-data-policy.js"), display.index("tv-preview.js"))
        self.assertIn("/static/settings/theme-visual-editor.js", settings)
        self.assertIn("/static/settings/theme-stability.js", settings)
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

        self.assertIn("XMLHttpRequest", policy)
        self.assertIn("assignedRows", policy)
        self.assertIn("Number(row?.assigned_team_id||0)>0", policy)
        self.assertIn("return responseFrom(real.data", policy)
        self.assertIn("return previousFetch(input,init)", policy)
        self.assertIn("getRefresh=async function", policy)
        self.assertIn("MOCK PREVIEW · no assigned reps yet", policy)
        self.assertIn("te-mock-bg", policy)
        self.assertIn("#teamDesignOverlay #tdNewSample{display:none!important}", stability)
        self.assertIn("Real team stats are used when members exist", stability)

        self.assertIn("/static/display/theme-editor-controls.js", display)
        self.assertIn("/static/settings/theme-editor-help.js", settings)
        self.assertIn("Double-click to add", intuitive)
        self.assertIn("Replace Image", intuitive)
        self.assertIn('content:"↻"', intuitive)
        self.assertIn("stats.themeEditor.coach.v123.dismissed", intuitive)
        self.assertIn("Move your mouse over artwork", intuitive)
        self.assertIn("tdThemeHelpButton", help_ui)
        self.assertIn("Editing:", help_ui)
        self.assertIn("scrollIntoView", help_ui)
        self.assertIn("Show canvas guide", help_ui)

    def test_theme_colors_use_in_app_picker_and_always_apply(self):
        settings = (APP_DIR / "templates" / "settings.html").read_text(encoding="utf-8")
        display = (APP_DIR / "templates" / "display.html").read_text(encoding="utf-8")
        editor = (APP_DIR / "static" / "settings" / "theme-color-editor.js").read_text(encoding="utf-8")
        runtime = (APP_DIR / "static" / "display" / "theme-colors.js").read_text(encoding="utf-8")

        self.assertIn("/static/settings/theme-color-editor.js", settings)
        self.assertIn("/static/display/theme-colors.js", display)
        self.assertIn("Frame & Borders", editor)
        self.assertIn("Main Accent", editor)
        self.assertIn("Shadow / Depth", editor)
        self.assertIn("Background Glow", editor)
        self.assertIn("Rows & Panels", editor)
        self.assertIn("Champion Highlight", editor)
        self.assertIn('id="tcpHue" type="range"', editor)
        self.assertIn('id="tcpSat" type="range"', editor)
        self.assertIn('id="tcpLight" type="range"', editor)
        self.assertIn('id="tcpHex" class="tcp-hex" type="text"', editor)
        self.assertNotIn('id="tcpHex" class="tcp-hex" type="color"', editor)
        self.assertIn("event.stopImmediatePropagation()", editor)
        self.assertIn("paintThemeColor", editor)
        self.assertIn("Save & Apply Design", editor)
        self.assertIn("enabled:true", editor)
        self.assertIn("ensureActiveSoon", editor)
        self.assertIn("var(--bt-panel)", runtime)
        self.assertIn("var(--bt-dark)", runtime)
        self.assertIn("var(--bt-secondary)", runtime)


if __name__ == "__main__":
    unittest.main()
