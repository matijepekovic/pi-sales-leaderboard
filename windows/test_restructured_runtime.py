#!/usr/bin/env python3
"""Architecture smoke tests for the Phase 4 Windows runtime."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))
os.environ["STATS_WINDOWS_BUILD"] = "1"

from stats_core.bootstrap import create_app  # noqa: E402


class RestructuredRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app("windows", start_background=False)
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()
        cls.runtime = cls.app.extensions["stats_runtime"]

    def test_runtime_has_explicit_domain_owners(self):
        expected = {
            "platform": "WindowsPlatform",
            "leaderboard": "LeaderboardService",
            "organization": "OrganizationService",
            "source": "SourceService",
            "scheduler": "SchedulerService",
            "entitlement": "EntitlementService",
            "pull_policy": "RepPullPolicy",
            "rep_refresh": "RepRefreshService",
            "product_refresh": "ProductRefreshService",
            "preview": "PreviewService",
            "snapshots": "DataSnapshotService",
            "screens": "ScreenRegistry",
            "theme": "ThemeService",
            "controls": "ControlsService",
            "auth": "AuthService",
        }
        for attr, class_name in expected.items():
            self.assertEqual(type(getattr(self.runtime, attr)).__name__, class_name, attr)

    def test_repositories_are_domain_package_not_single_facade(self):
        self.assertFalse((APP / "stats_core" / "repositories.py").exists())
        package = APP / "stats_core" / "repositories"
        for filename in (
            "reps.py", "organization.py", "settings.py", "products.py",
            "themes.py", "asset_library.py", "applied_assets.py", "meta.py",
        ):
            self.assertTrue((package / filename).is_file(), filename)
        self.assertEqual(type(self.runtime.repos.themes).__name__, "ThemeRepository")
        self.assertEqual(type(self.runtime.repos.asset_library).__name__, "AssetLibraryRepository")
        self.assertEqual(type(self.runtime.repos.applied_assets).__name__, "AppliedAssetRepository")

    def test_every_existing_screen_is_registered(self):
        expected = {"whole_office", "per_team", "team_vs_team", "all_teams", "product_close"}
        actual = set(self.runtime.screens._screens)
        self.assertEqual(actual, expected)

    def test_core_routes_are_owned_and_available(self):
        routes = {rule.rule for rule in self.app.url_map.iter_rules()}
        required = {
            "/", "/settings", "/health", "/api/system/version",
            "/api/config", "/api/leaderboard", "/api/team-builder/save",
            "/api/source/refresh", "/api/product-close",
            "/api/temporary-date-override", "/api/keyboard-controls",
            "/api/tv/restart", "/api/themes", "/api/asset-library",
            "/api/windows/update/check", "/api/windows/update/diagnostics",
        }
        self.assertTrue(required.issubset(routes), required - routes)

    def test_health_version_config_and_leaderboard_contracts(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.get_json()["ok"])

        version = self.client.get("/api/system/version")
        self.assertEqual(version.status_code, 200)
        self.assertRegex(version.get_json()["version"], r"^\d+\.\d+\.\d+$")

        config = self.client.get("/api/config")
        self.assertEqual(config.status_code, 200)
        config_json = config.get_json()
        self.assertIn("settings", config_json)
        self.assertIn("feature_access", config_json["settings"])
        self.assertEqual(
            {row["key"] for row in config_json["modes"]},
            {"whole_office", "per_team", "team_vs_team", "all_teams"},
        )

        board = self.client.get("/api/leaderboard?mode=whole_office")
        self.assertEqual(board.status_code, 200)
        payload = board.get_json()
        for key in (
            "mode", "mode_label", "metrics", "rows", "office_summary",
            "sort_metric", "metric_types", "metric_labels", "theme_state", "preview",
        ):
            self.assertIn(key, payload)

    def test_old_patch_stack_is_not_loaded(self):
        forbidden = {
            "qr_controls_v110", "keyboard_controls_v112", "product_controls_v115",
            "temporary_date_v113", "pull_policy_v108", "production_gates",
            "production_versioning", "windows_runtime", "themes",
            "applied_theme_assets_v116", "starter_theme_v119",
            "starter_theme_assets_v119", "theme_asset_apply_v127",
            "product_source_v115", "tableau_scheduler",
        }
        loaded = forbidden.intersection(sys.modules)
        self.assertFalse(loaded, f"Legacy patch modules loaded: {sorted(loaded)}")

    def test_theme_and_preview_are_not_monkey_patched(self):
        bootstrap = (APP / "stats_core" / "bootstrap.py").read_text(encoding="utf-8")
        theme_service = (APP / "stats_core" / "theme" / "service.py").read_text(encoding="utf-8")
        snapshot = (APP / "stats_core" / "services" / "snapshot.py").read_text(encoding="utf-8")
        self.assertNotIn("tableau_scheduler.configure", bootstrap)
        self.assertNotIn("app.view_functions[", theme_service)
        self.assertNotIn("source_picker.preview_rows", snapshot)
        self.assertIn("self.preview.rows()", snapshot)

    def test_frontend_runtime_ownership_is_explicit(self):
        display = (APP / "templates" / "display.html").read_text(encoding="utf-8")
        settings = (APP / "templates" / "settings.html").read_text(encoding="utf-8")
        formatting = (APP / "static" / "runtime" / "formatting.js").read_text(encoding="utf-8")
        team_builder = (APP / "static" / "settings" / "team-builder-workflow.js").read_text(encoding="utf-8")
        self.assertIn("Theme runtime", display)
        self.assertIn("Display + layout runtime", display)
        self.assertIn("Controls runtime", display)
        self.assertIn("Product runtime", display)
        self.assertIn("/static/runtime/formatting.js", display)
        self.assertIn("minimumFractionDigits: 2", formatting)
        self.assertIn("Tableau/data settings", settings)
        self.assertIn("Windows theme workspace", settings)
        self.assertIn("/static/settings/team-builder-workflow.js", settings)
        self.assertIn("renderLeaderFromMembers", team_builder)

    def test_server_entry_contains_no_feature_install_chain(self):
        text = (ROOT / "windows" / "server_entry.py").read_text(encoding="utf-8")
        self.assertIn("stats_core.bootstrap", text)
        for token in (
            "qr_controls_v110", "windows_runtime.install",
            "windows_update_status_v128.install", "windows_theme_editor_v122.install",
            "windows_tableau_login_v124.install", "starter_theme_v119",
        ):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
