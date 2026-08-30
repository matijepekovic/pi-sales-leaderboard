#!/usr/bin/env python3
"""Architecture smoke tests for the Windows runtime."""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from stats_core.bootstrap import create_app  # noqa: E402


ROOT_LEVEL_LEGACY_FILES = (
    "applied_theme_assets_v116.py",
    "keyboard_controls_v111.py",
    "keyboard_controls_v112.py",
    "product_controls_v115.py",
    "product_source_v115.py",
    "production_gates.py",
    "production_versioning.py",
    "pull_policy_v108.py",
    "qr_controls_v110.py",
    "remote_qr.py",
    "remote_qr_v109.py",
    "starter_theme_assets_v119.py",
    "starter_theme_v119.py",
    "tableau_scheduler.py",
    "temporary_date_v113.py",
    "theme_asset_apply_v127.py",
    "themes.py",
    "update_signing_public_key.py",
    "windows_https.py",
    "windows_runtime.py",
    "windows_tableau_login.py",
    "windows_tableau_login_v124.py",
    "windows_theme_editor.py",
    "windows_theme_editor_v122.py",
    "windows_update.py",
    "windows_update_diagnostics.py",
    "windows_update_status.py",
    "windows_update_status_v128.py",
)


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
            self.assertEqual(
                type(getattr(self.runtime, attr)).__name__,
                class_name,
                attr,
            )

    def test_repositories_are_domain_package_not_single_facade(self):
        self.assertFalse((APP / "stats_core" / "repositories.py").exists())
        package = APP / "stats_core" / "repositories"
        for filename in (
            "reps.py",
            "organization.py",
            "settings.py",
            "products.py",
            "themes.py",
            "asset_library.py",
            "applied_assets.py",
            "meta.py",
        ):
            self.assertTrue((package / filename).is_file(), filename)
        self.assertEqual(type(self.runtime.repos.themes).__name__, "ThemeRepository")
        self.assertEqual(
            type(self.runtime.repos.asset_library).__name__,
            "AssetLibraryRepository",
        )
        self.assertEqual(
            type(self.runtime.repos.applied_assets).__name__,
            "AppliedAssetRepository",
        )

    def test_every_existing_screen_is_registered(self):
        expected = {
            "whole_office",
            "per_team",
            "team_vs_team",
            "all_teams",
            "product_close",
        }
        self.assertEqual(set(self.runtime.screens._screens), expected)

    def test_core_routes_are_owned_and_available(self):
        routes = {rule.rule for rule in self.app.url_map.iter_rules()}
        required = {
            "/",
            "/settings",
            "/health",
            "/api/system/version",
            "/api/config",
            "/api/leaderboard",
            "/api/team-builder/save",
            "/api/source/refresh",
            "/api/product-close",
            "/api/temporary-date-override",
            "/api/keyboard-controls",
            "/api/tv/restart",
            "/api/themes",
            "/api/asset-library",
            "/api/windows/update/check",
            "/api/windows/update/diagnostics",
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
            "mode",
            "mode_label",
            "metrics",
            "rows",
            "office_summary",
            "sort_metric",
            "metric_types",
            "metric_labels",
            "theme_state",
            "preview",
        ):
            self.assertIn(key, payload)

    def test_root_level_legacy_files_do_not_exist(self):
        remaining = [
            name for name in ROOT_LEVEL_LEGACY_FILES if (APP / name).exists()
        ]
        self.assertEqual(remaining, [])

    def test_stats_core_import_is_platform_neutral(self):
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(APP)!r})\n"
            "import stats_core\n"
            "forbidden = [name for name in sys.modules "
            "if name == 'stats_core.platform.windows' "
            "or name == 'stats_core.windows' "
            "or name.startswith('stats_core.windows.') "
            "or name.startswith('windows_') "
            "or name == 'remote_qr']\n"
            "assert not forbidden, forbidden\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_theme_and_preview_are_not_monkey_patched(self):
        bootstrap = (APP / "stats_core" / "bootstrap.py").read_text(
            encoding="utf-8"
        )
        theme_service = (APP / "stats_core" / "theme" / "service.py").read_text(
            encoding="utf-8"
        )
        snapshot = (APP / "stats_core" / "services" / "snapshot.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("tableau_scheduler.configure", bootstrap)
        self.assertNotIn("app.view_functions[", theme_service)
        self.assertNotIn("source_picker.preview_rows", snapshot)
        self.assertIn("self.preview.rows()", snapshot)

    def test_windows_helpers_do_not_bypass_repositories(self):
        for filename in ("tableau_login.py", "theme_editor.py"):
            text = (APP / "stats_core" / "windows" / filename).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("import database", text, filename)
            self.assertNotIn("from database", text, filename)

        platform = (APP / "stats_core" / "platform" / "windows.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("tableau_login.install(app, self.repos.settings)", platform)
        self.assertIn("theme_editor.install(app, self.repos, public_endpoints)", platform)

    def test_frontend_runtime_ownership_is_explicit(self):
        display = (APP / "templates" / "display.html").read_text(encoding="utf-8")
        settings = (APP / "templates" / "settings.html").read_text(encoding="utf-8")
        formatting = (APP / "static" / "runtime" / "formatting.js").read_text(
            encoding="utf-8"
        )
        team_builder = (
            APP / "static" / "settings" / "team-builder-workflow.js"
        ).read_text(encoding="utf-8")
        self.assertIn("Theme runtime", display)
        self.assertIn("Display + layout runtime", display)
        self.assertIn("Controls runtime", display)
        self.assertIn("Product runtime", display)
        self.assertIn("/static/display/keyboard-controls.js", display)
        self.assertIn("/static/runtime/formatting.js", display)
        self.assertIn("minimumFractionDigits: 2", formatting)
        self.assertIn("Tableau/data settings", settings)
        self.assertIn("Windows theme workspace", settings)
        self.assertIn("/static/settings/controls.js", settings)
        self.assertIn("/static/settings/team-builder-workflow.js", settings)
        self.assertIn("renderLeaderFromMembers", team_builder)

    def test_frontend_has_no_versioned_patch_files(self):
        for retired in (
            "display_v35_base.html",
            "display_v36_base.html",
            "settings_v34_base.html",
        ):
            self.assertFalse((APP / "templates" / retired).exists(), retired)

        versioned_static = sorted(
            path.name
            for path in (APP / "static").glob("*.js")
            if re.search(r"-v\d+\.js$", path.name)
        )
        self.assertEqual(versioned_static, [])

        for template_name in ("display.html", "settings.html"):
            text = (APP / "templates" / template_name).read_text(encoding="utf-8")
            self.assertIsNone(
                re.search(r"/static/[^\"']*[-_]v\d+", text),
                template_name,
            )
            self.assertIsNone(
                re.search(r"(?:display|settings)_v\d+_base", text),
                template_name,
            )

    def test_tableau_sources_have_stable_names(self):
        sources = APP / "sources"
        self.assertTrue((sources / "tableau_base.py").is_file())
        self.assertFalse((sources / "tableau_v36_base.py").exists())
        self.assertFalse((sources / "tableau_v37_base.py").exists())

        violations = []
        for path in APP.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "tableau_v36_base" in text or "tableau_v37_base" in text:
                violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_server_entry_contains_no_feature_install_chain(self):
        text = (ROOT / "windows" / "server_entry.py").read_text(encoding="utf-8")
        self.assertIn("stats_core.bootstrap", text)
        for token in (
            "qr_controls_v110",
            "starter_theme_v119",
            "windows_runtime.install",
            "tableau_login.install",
            "theme_editor.install",
            "update_status.install",
        ):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
