#!/usr/bin/env python3
"""Architecture smoke tests for the restructured Windows runtime."""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
os.environ["STATS_WINDOWS_BUILD"] = "1"

from stats_core.bootstrap import create_app  # noqa: E402


class RestructuredRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app("windows", start_background=False)
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()

    def test_runtime_is_composed_by_stats_core(self):
        runtime = self.app.extensions.get("stats_runtime")
        self.assertIsNotNone(runtime)
        self.assertEqual(type(runtime.platform).__name__, "WindowsPlatform")
        self.assertEqual(type(runtime.leaderboard).__name__, "LeaderboardService")
        self.assertEqual(type(runtime.organization).__name__, "OrganizationService")
        self.assertEqual(type(runtime.source).__name__, "SourceService")
        self.assertEqual(type(runtime.scheduler).__name__, "SchedulerService")

    def test_core_routes_are_owned_and_available(self):
        routes = {rule.rule for rule in self.app.url_map.iter_rules()}
        required = {
            "/", "/settings", "/health", "/api/system/version",
            "/api/config", "/api/leaderboard", "/api/team-builder/save",
            "/api/source/refresh", "/api/product-close",
            "/api/temporary-date-override", "/api/keyboard-controls",
            "/api/tv/restart", "/api/windows/update/check",
            "/api/windows/update/diagnostics",
        }
        self.assertTrue(required.issubset(routes), required - routes)

    def test_health_and_version(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.get_json()["ok"])

        version = self.client.get("/api/system/version")
        self.assertEqual(version.status_code, 200)
        value = version.get_json()["version"]
        self.assertRegex(value, r"^\d+\.\d+\.\d+$")

    def test_old_patch_stack_is_not_part_of_active_composition(self):
        forbidden = {
            "qr_controls_v110",
            "keyboard_controls_v112",
            "product_controls_v115",
            "temporary_date_v113",
            "pull_policy_v108",
            "production_gates",
            "production_versioning",
            "windows_runtime",
        }
        loaded = forbidden.intersection(sys.modules)
        self.assertFalse(loaded, f"Legacy patch modules loaded: {sorted(loaded)}")

    def test_server_entry_contains_no_feature_install_chain(self):
        text = (ROOT / "windows" / "server_entry.py").read_text(encoding="utf-8")
        self.assertIn("stats_core.bootstrap", text)
        for token in (
            "qr_controls_v110", "windows_runtime.install",
            "windows_update_status_v128.install", "windows_theme_editor_v122.install",
            "windows_tableau_login_v124.install",
        ):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
