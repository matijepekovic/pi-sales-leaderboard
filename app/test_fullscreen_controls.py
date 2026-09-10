"""Run: python -m unittest discover -s app -p test_fullscreen_controls.py -v

Uses temporary homes and fake browser commands, never the real Pi session.
Route unit tests mock Flask's request/response boundary; no server is started.
"""
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from fullscreen_controls import FullscreenControl, install_routes

APP_DIR = Path(__file__).resolve().parent


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.control = FullscreenControl(self.data_dir)

    def test_default_is_fullscreen_without_writing_files(self):
        self.assertTrue(self.control.enabled)
        self.assertFalse(self.data_dir.exists())

    def test_exit_creates_pause_and_existing_watchdog_request(self):
        self.control.set_enabled(False)
        self.assertFalse(self.control.enabled)
        self.assertTrue(self.control.disabled_flag.is_file())
        self.assertTrue((self.data_dir / "restart-kiosk.request").is_file())

    def test_pause_survives_new_controller_and_consumed_request(self):
        self.control.set_enabled(False)
        self.control.restart_request.unlink()
        self.assertFalse(FullscreenControl(self.data_dir).enabled)

    def test_enable_clears_pause_and_requests_relaunch(self):
        self.control.set_enabled(False)
        self.control.restart_request.unlink()
        self.control.set_enabled(True)
        self.assertTrue(self.control.enabled)
        self.assertFalse(self.control.disabled_flag.exists())
        self.assertTrue(self.control.restart_request.exists())

    def test_repeated_commands_do_not_toggle_back(self):
        for enabled in (False, False, True, True, False, False):
            self.assertEqual(self.control.set_enabled(enabled), enabled)
            self.assertEqual(self.control.enabled, enabled)

    def test_invalid_boolean_does_not_change_mode(self):
        self.control.set_enabled(False)
        self.control.restart_request.unlink()
        for value in (None, "false", "true", 0, 1, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.control.set_enabled(value)
            self.assertFalse(self.control.enabled)
            self.assertFalse(self.control.restart_request.exists())

    def test_failed_request_restores_previous_mode(self):
        for previous in (True, False):
            self.control.set_enabled(previous)
            self.control.restart_request.unlink()
            with patch.object(self.control, "_request_restart", side_effect=OSError("read-only")):
                with self.assertRaises(OSError):
                    self.control.set_enabled(not previous)
            self.assertEqual(self.control.enabled, previous)
            self.assertFalse(self.control.restart_request.exists())

    def test_unrelated_persistent_files_are_untouched(self):
        self.data_dir.mkdir()
        settings = self.data_dir / "settings-sentinel"
        settings.write_text("keep these settings")
        self.control.set_enabled(False)
        self.control.set_enabled(True)
        self.assertEqual(settings.read_text(), "keep these settings")


class FakeResponse(dict):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {}


class FakeRequest:
    raw = b""

    def get_data(self):
        return self.raw

    def get_json(self, silent=False):
        try:
            return json.loads(self.raw)
        except (ValueError, TypeError):
            return None


class FakeApp:
    def __init__(self):
        self.extensions = {}
        self.view_functions = {"api_tv_fullscreen": lambda: "legacy F11"}
        self.rules = []
        self.logger = logging.getLogger("fullscreen-test")
        self.logger.addHandler(logging.NullHandler())
        self.logger.propagate = False

    def add_url_rule(self, path, endpoint, view_func, methods):
        self.rules.append((path, endpoint, methods))
        self.view_functions[endpoint] = view_func


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = FakeApp()
        self.request = FakeRequest()
        self.request.raw = b""
        flask_boundary = types.SimpleNamespace(jsonify=FakeResponse, request=self.request)
        mock_flask = patch.dict(sys.modules, {"flask": flask_boundary})
        mock_flask.start()
        self.addCleanup(mock_flask.stop)
        install_routes(self.app, self.temp.name)
        self.post = self.app.view_functions["api_tv_fullscreen"]
        self.get = self.app.view_functions["api_tv_fullscreen_status"]
        self.control = self.app.extensions["fullscreen_controls"]

    def test_status_is_read_only_and_uncached(self):
        response = self.get()
        self.assertTrue(response["force_fullscreen"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertFalse(self.control.restart_request.exists())

    def test_explicit_exit_and_enable(self):
        for enabled in (False, True):
            self.request.raw = json.dumps({"enabled": enabled}).encode()
            response = self.post()
            self.assertTrue(response["ok"])
            self.assertTrue(response["restart_requested"])
            self.assertEqual(response["force_fullscreen"], enabled)
            self.assertEqual(self.get()["force_fullscreen"], enabled)

    def test_legacy_bodyless_post_enables_without_old_handler(self):
        self.control.set_enabled(False)
        response = self.post()
        self.assertTrue(response["force_fullscreen"])

    def test_malformed_payloads_do_not_enable_paused_mode(self):
        self.control.set_enabled(False)
        for raw in (b'null', b'[]', b'true', b'{', b'"false"',
                    b'{"enabled":"false"}', b'{"enabled":null}',
                    b'{"enabled":0}', b'{"enabled":1}'):
            self.request.raw = raw
            with self.subTest(raw=raw):
                response, status = self.post()
                self.assertEqual(status, 400)
                self.assertFalse(response["ok"])
                self.assertFalse(self.control.enabled)

    def test_io_failure_is_not_reported_as_success(self):
        self.request.raw = b'{"enabled":false}'
        with patch.object(self.control, "_request_restart", side_effect=OSError("failed")):
            response, status = self.post()
        self.assertEqual(status, 500)
        self.assertFalse(response["ok"])
        self.assertTrue(self.control.enabled)

    def test_install_is_idempotent_and_keeps_existing_post_route(self):
        self.assertFalse(install_routes(self.app, self.temp.name))
        self.assertEqual(self.app.rules, [
            ("/api/tv/fullscreen", "api_tv_fullscreen_status", ["GET"])
        ])
        self.assertIs(self.app.view_functions["api_tv_fullscreen"], self.post)

    def test_registers_post_when_no_legacy_endpoint_exists(self):
        app = FakeApp()
        app.view_functions.clear()
        install_routes(app, self.temp.name)
        self.assertIn(("/api/tv/fullscreen", "api_tv_fullscreen", ["POST"]), app.rules)


@unittest.skipUnless(shutil.which("bash"), "Bash is needed for launcher tests")
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.log = self.home / "browser.json"
        self.data_dir = self.home / ".local/share/pi-tableau-leaderboard"
        self.control = FullscreenControl(self.data_dir)
        for name in ("mkdir", "rm"):
            (self.bin / name).symlink_to(shutil.which(name))
        for name in ("pkill", "sleep"):
            self.write_command(name, "#!/bin/sh\nexit 0\n")
        self.write_command("chromium", "#!" + sys.executable + "\n"
                           "import json,os,sys\n"
                           "from pathlib import Path\n"
                           "Path(os.environ['BROWSER_LOG']).write_text(json.dumps(sys.argv[1:]))\n")

    def write_command(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def launch(self):
        env = dict(os.environ, HOME=str(self.home), BROWSER_LOG=str(self.log),
                   PATH=str(self.bin))
        result = subprocess.run([shutil.which("bash"), str(APP_DIR / "kiosk_browser.sh")],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(self.log.read_text())

    def test_default_launch_uses_kiosk(self):
        args = self.launch()
        self.assertIn("--kiosk", args)
        self.assertIn("http://127.0.0.1:8765/", args)

    def test_paused_relaunches_stay_windowed_until_enabled(self):
        self.control.set_enabled(False)
        for _ in range(2):
            args = self.launch()
            self.assertNotIn("--kiosk", args)
            self.assertNotIn("--start-fullscreen", args)
            self.assertIn("--new-window", args)
            self.assertTrue(self.control.disabled_flag.exists())
        self.control.set_enabled(True)
        self.assertIn("--kiosk", self.launch())

    def test_both_modes_use_only_dedicated_profile(self):
        profile_arg = "--user-data-dir=" + str(self.data_dir / "chromium-kiosk-profile")
        for enabled in (False, True):
            self.control.set_enabled(enabled)
            self.assertIn(profile_arg, self.launch())

    def test_chromium_browser_fallback_honors_pause(self):
        (self.bin / "chromium").rename(self.bin / "chromium-browser")
        self.control.set_enabled(False)
        self.assertNotIn("--kiosk", self.launch())


if __name__ == "__main__":
    unittest.main()
