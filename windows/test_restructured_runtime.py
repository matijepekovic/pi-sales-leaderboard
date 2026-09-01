#!/usr/bin/env python3
"""Architecture and runtime smoke tests for Stats production."""
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
            "reports": "ReportService",
            "filters": "FilterService",
            "screens": "ScreenService",
            "display": "DisplayService",
            "scheduler": "SchedulerService",
            "pull_policy": "RepPullPolicy",
            "rep_refresh": "RepRefreshService",
            "product_refresh": "ProductRefreshService",
            "preview": "PreviewService",
            "snapshots": "DataSnapshotService",
            "theme": "ThemeService",
            "controls": "ControlsService",
            "auth": "AuthService",
        }
        for attr, class_name in expected.items():
            self.assertEqual(type(getattr(self.runtime, attr)).__name__, class_name, attr)

    def test_repositories_own_persistence_boundaries(self):
        package = APP / "stats_core" / "repositories"
        required = {
            "reps.py", "organization.py", "settings.py", "products.py", "themes.py",
            "asset_library.py", "applied_assets.py", "meta.py", "data_catalog.py",
            "source_credentials.py", "report_data.py", "filters.py", "screens.py", "display.py",
        }
        self.assertTrue(required.issubset({p.name for p in package.iterdir()}))
        self.assertEqual(type(self.runtime.repos.data_catalog).__name__, "DataCatalogRepository")
        self.assertEqual(type(self.runtime.repos.source_credentials).__name__, "SourceCredentialRepository")
        self.assertEqual(type(self.runtime.repos.report_data).__name__, "ReportDataRepository")
        self.assertEqual(type(self.runtime.repos.filters).__name__, "FilterRepository")
        self.assertEqual(type(self.runtime.repos.screens).__name__, "ScreenRepository")
        self.assertEqual(type(self.runtime.repos.display).__name__, "DisplayRepository")

    def test_normalized_routes_replace_legacy_source_routes(self):
        routes = {rule.rule for rule in self.app.url_map.iter_rules()}
        required = {
            "/", "/settings", "/health", "/api/system/version", "/api/config",
            "/api/leaderboard", "/api/data/sources", "/api/data/reports",
            "/api/data/reports/<report_id>/inspect", "/api/filters",
            "/api/screens", "/api/screens/preview", "/api/display",
            "/api/product-close", "/api/temporary-date-override", "/api/themes",
            "/api/asset-library", "/api/windows/update/check",
        }
        self.assertTrue(required.issubset(routes), required - routes)
        self.assertNotIn("/api/source/refresh", routes)
        self.assertNotIn("/api/source/workbooks", routes)

    def test_boot_and_public_contracts(self):
        for path in ("/", "/settings", "/health", "/api/system/version", "/api/config", "/api/leaderboard"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
        config = self.client.get("/api/config").get_json()
        self.assertIn("screens", config)
        self.assertIn("display", config)
        board = self.client.get("/api/leaderboard").get_json()
        self.assertIn("mode", board)
        self.assertIn("theme_state", board)

    def test_source_report_filter_screen_display_crud_contract(self):
        sources = self.client.get("/api/data/sources").get_json()["sources"]
        self.assertTrue(sources)
        source_id = sources[0]["id"]

        created_report = self.client.post("/api/data/reports", json={
            "source_id": source_id,
            "name": "Architecture Test Report",
            "kind": "table",
            "source_config": {},
            "runtime": {},
        })
        self.assertEqual(created_report.status_code, 200)
        report_id = created_report.get_json()["report"]["id"]

        inspect = self.client.get("/api/data/reports/report-reps/inspect")
        self.assertEqual(inspect.status_code, 200)
        inspection = inspect.get_json()
        self.assertIn("sample_rows", inspection)
        self.assertTrue(any(field["key"] == "team" for field in inspection["fields"]))

        created_filter = self.client.post("/api/filters", json={"name": "Architecture Team"})
        self.assertEqual(created_filter.status_code, 200)
        filter_id = created_filter.get_json()["filter"]["id"]

        created_screen = self.client.post("/api/screens", json={
            "name": "Architecture Test Screen",
            "reports": ["report-reps", report_id],
            "filter_ids": [filter_id],
            "display_filter_mappings": [
                {"filter_id": filter_id, "report_id": "report-reps", "field": "team"},
            ],
            "filter_values": {filter_id: "All"},
            "tables": [
                {"report_id": "report-reps", "columns": ["rep_name", "team"], "limit": 25},
                {"report_id": report_id, "columns": [], "limit": 25},
            ],
            "theme_mode": "custom",
        })
        self.assertEqual(created_screen.status_code, 200)
        screen = created_screen.get_json()["screen"]
        screen_id = screen["id"]
        self.assertEqual(screen["filter_ids"], [filter_id])
        self.assertEqual(screen["display_filter_mappings"][0]["field"], "team")
        self.assertNotIn("filters", screen)

        preview = self.client.get(f"/api/screens/{screen_id}/preview")
        self.assertEqual(preview.status_code, 200)
        payload = preview.get_json()["payload"]
        self.assertEqual(payload["mode"], "custom_screen")
        self.assertEqual(payload["display_filters"][0]["name"], "Architecture Team")

        blocked = self.client.delete(f"/api/filters/{filter_id}")
        self.assertEqual(blocked.status_code, 400)

        display = self.client.put("/api/display", json={
            "active_screen_id": screen_id,
            "rotation_screen_ids": [screen_id, "builtin:whole_office"],
            "rotation_enabled": False,
            "rotation_seconds": 20,
        })
        self.assertEqual(display.status_code, 200)
        self.assertEqual(display.get_json()["display"]["active_screen_id"], screen_id)

        shown = self.client.get(f"/api/leaderboard?screen_id={screen_id}")
        self.assertEqual(shown.status_code, 200)
        self.assertEqual(shown.get_json()["screen_id"], screen_id)

        self.assertEqual(self.client.delete(f"/api/screens/{screen_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/filters/{filter_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/data/reports/{report_id}").status_code, 200)

    def test_display_filters_are_not_data_filters(self):
        filters_service = (APP / "stats_core" / "services" / "filters.py").read_text(encoding="utf-8")
        screens_service = (APP / "stats_core" / "services" / "screens.py").read_text(encoding="utf-8")
        reports_service = (APP / "stats_core" / "services" / "reports.py").read_text(encoding="utf-8")
        self.assertNotIn("source_config", filters_service)
        self.assertNotIn("adapter", filters_service.lower())
        self.assertIn("display_filter_mappings", screens_service)
        self.assertNotIn("source_config", screens_service)
        self.assertIn("inspect", reports_service)
        workspace = (APP / "static" / "settings" / "data-screen-display.js").read_text(encoding="utf-8")
        self.assertIn("Display Data — Match Filters", workspace)
        self.assertIn("Data Filters", workspace)
        self.assertIn("real pulled", workspace)

    def test_tableau_is_replaceable_adapter_only(self):
        bootstrap = (APP / "stats_core" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("from sources.tableau_adapter import TableauAdapter", bootstrap)
        self.assertFalse((APP / "stats_core" / "services" / "tableau.py").exists())
        self.assertFalse((APP / "stats_core" / "web" / "source.py").exists())
        self.assertFalse((APP / "stats_core" / "product" / "source.py").exists())
        self.assertFalse((APP / "stats_core" / "windows" / "tableau_login.py").exists())
        for root in (
            APP / "stats_core" / "services",
            APP / "stats_core" / "repositories",
            APP / "stats_core" / "screens",
            APP / "stats_core" / "theme",
            APP / "stats_core" / "web",
        ):
            violations = []
            for path in root.rglob("*.py"):
                text = path.read_text(encoding="utf-8").lower()
                if "sources.tableau" in text or "from sources import tableau" in text:
                    violations.append(str(path.relative_to(ROOT)))
            self.assertEqual(violations, [], root)
        organization = (APP / "stats_core" / "repositories" / "organization.py").read_text(encoding="utf-8")
        self.assertNotIn("tableau_team", organization)
        self.assertIn('row["source_team"]', organization)

    def test_obsolete_source_ui_and_patch_paths_are_deleted(self):
        retired = (
            APP / "static" / "settings" / "data-source.js",
            APP / "static" / "settings" / "tableau-team-members.js",
            APP / "static" / "settings" / "windows-tableau-login.js",
            APP / "static" / "settings" / "flow.js",
            APP / "static" / "settings" / "date-filter.js",
            APP / "static" / "settings" / "date-simple.js",
            APP / "static" / "settings" / "preview-scroll.js",
            APP / "static" / "settings" / "accordion.js",
            APP / "sources" / "tableau.py",
        )
        self.assertEqual([str(path.relative_to(ROOT)) for path in retired if path.exists()], [])

    def test_frontend_ownership_is_explicit(self):
        settings = (APP / "templates" / "settings.html").read_text(encoding="utf-8")
        display = (APP / "templates" / "display.html").read_text(encoding="utf-8")
        self.assertIn("Data, Screens, Display", settings)
        self.assertIn("/static/settings/data-screen-display.js", settings)
        self.assertNotIn("/static/settings/data-source.js", settings)
        self.assertIn("/static/display/custom-screen.js", display)
        workspace = (APP / "static" / "settings" / "data-screen-display.js").read_text(encoding="utf-8")
        for label in ("Sources", "Reports", "Filters", "Screens", "Display"):
            self.assertIn(label.lower(), workspace.lower())

    def test_stats_core_package_import_is_platform_neutral(self):
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(APP)!r})\n"
            "import stats_core\n"
            "forbidden=[name for name in sys.modules if name == 'stats_core.platform.windows' "
            "or name == 'stats_core.windows' or name.startswith('stats_core.windows.')]\n"
            "assert not forbidden, forbidden\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_no_versioned_patch_files_return(self):
        versioned = []
        for path in APP.rglob("*"):
            if path.is_file() and re.search(r"(?:^|[-_])v\d+(?:[-_.]|$)", path.name, re.I):
                versioned.append(str(path.relative_to(ROOT)))
        allowed_data_history = {"production-coming-eventually.js"}
        versioned = [path for path in versioned if Path(path).name not in allowed_data_history]
        self.assertEqual(versioned, [])


if __name__ == "__main__":
    unittest.main()
