#!/usr/bin/env python3
"""Architecture and runtime smoke tests for the Stats product core."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))


class RestructuredRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["STATS_DATA_DIR"] = cls.temp.name
        from stats_core.bootstrap import create_app
        cls.app = create_app("windows", start_background=False)
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()
        cls.runtime = cls.app.extensions["stats_runtime"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_runtime_has_only_current_product_owners(self):
        expected = {
            "platform": "WindowsPlatform",
            "source": "SourceService",
            "reports": "ReportService",
            "filters": "FilterService",
            "screens": "ScreenService",
            "display": "DisplayService",
            "theme": "ThemeService",
            "auth": "AuthService",
            "settings": "SettingsService",
            "version": "VersionService",
        }
        for attr, class_name in expected.items():
            self.assertEqual(type(getattr(self.runtime, attr)).__name__, class_name, attr)
        for retired in (
            "leaderboard", "organization", "products", "controls", "scheduler",
            "pull_policy", "rep_refresh", "product_refresh", "temporary_date",
            "preview", "snapshots", "tv",
        ):
            self.assertFalse(hasattr(self.runtime, retired), retired)

    def test_current_http_contract(self):
        routes = {rule.rule for rule in self.app.url_map.iter_rules()}
        required = {
            "/", "/settings", "/health", "/api/system/version", "/api/state",
            "/api/data/sources", "/api/data/reports", "/api/data/reports/<report_id>/inspect",
            "/api/filters", "/api/filters/preview", "/api/screens", "/api/screens/preview",
            "/api/display", "/api/display/render", "/api/screen-themes/<screen_id>",
            "/api/asset-library", "/api/windows/update/check",
        }
        self.assertTrue(required.issubset(routes), required - routes)
        for retired in (
            "/api/config", "/api/leaderboard", "/api/product-close",
            "/api/temporary-date-override", "/api/source/refresh",
        ):
            self.assertNotIn(retired, routes)

    def test_boot_pages_and_empty_display(self):
        for path in ("/", "/settings", "/health", "/api/system/version", "/api/state", "/api/display/render"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
        payload = self.client.get("/api/display/render").get_json()["payload"]
        self.assertEqual(payload["mode"], "empty")
        self.assertEqual(payload["sections"], [])

    def test_source_report_filter_screen_display_contract(self):
        source = self.client.post("/api/data/sources", json={
            "name": "Test Tableau",
            "adapter": "tableau",
            "connection": {"server": "https://example.invalid", "site": "test", "pat_name": "token"},
        })
        self.assertEqual(source.status_code, 200)
        source_id = source.get_json()["source"]["id"]

        report = self.client.post("/api/data/reports", json={
            "source_id": source_id,
            "name": "Sales Competition",
            "source_config": {"workbook": "Workbook", "sheet": "View", "filters": []},
            "runtime": {},
        })
        self.assertEqual(report.status_code, 200)
        report_id = report.get_json()["report"]["id"]

        self.runtime.repos.report_data.replace(
            report_id,
            [
                {"key": "Rep", "label": "Rep", "type": "text"},
                {"key": "Office", "label": "Office", "type": "text"},
                {"key": "Revenue", "label": "Revenue", "type": "currency"},
            ],
            [
                {"Rep": "A", "Office": "Olympia", "Revenue": 120},
                {"Rep": "B", "Office": "Tacoma", "Revenue": 200},
                {"Rep": "C", "Office": "Olympia", "Revenue": 180},
            ],
            {"status": "3 rows", "last_refresh": "test"},
        )

        inspection = self.client.get(f"/api/data/reports/{report_id}/inspect").get_json()
        self.assertEqual(inspection["total_rows"], 3)
        office = next(field for field in inspection["fields"] if field["key"] == "Office")
        self.assertEqual(office["sample_values"], ["Olympia", "Tacoma"])

        created_filter = self.client.post("/api/filters", json={
            "name": "Olympia",
            "rules": [{"report_id": report_id, "field": "Office", "operator": "equals", "value": "Olympia"}],
        })
        self.assertEqual(created_filter.status_code, 200)
        filter_id = created_filter.get_json()["filter"]["id"]

        tested = self.client.post("/api/filters/preview", json={
            "name": "Olympia",
            "rules": [{"report_id": report_id, "field": "Office", "operator": "equals", "value": "Olympia"}],
        })
        self.assertEqual(tested.status_code, 200)
        self.assertEqual(tested.get_json()["reports"][0]["matched_rows"], 2)

        created_screen = self.client.post("/api/screens", json={
            "name": "Olympia Revenue",
            "reports": [report_id],
            "filter_ids": [filter_id],
            "tables": [{
                "report_id": report_id,
                "columns": ["Rep", "Revenue"],
                "sort_field": "Revenue",
                "sort_direction": "desc",
                "limit": 10,
            }],
            "theme_mode": "custom",
        })
        self.assertEqual(created_screen.status_code, 200)
        screen = created_screen.get_json()["screen"]
        self.assertEqual(screen["filter_ids"], [filter_id])
        self.assertNotIn("display_filter_mappings", screen)
        self.assertNotIn("filter_values", screen)

        preview = self.client.get(f"/api/screens/{screen['id']}/preview").get_json()["payload"]
        self.assertEqual(preview["mode"], "screen")
        self.assertEqual([row["Rep"] for row in preview["sections"][0]["rows"]], ["C", "A"])

        saved_display = self.client.put("/api/display", json={
            "active_screen_id": screen["id"],
            "rotation_enabled": False,
            "rotation_screen_ids": [],
            "rotation_seconds": 20,
        })
        self.assertEqual(saved_display.status_code, 200)
        rendered = self.client.get("/api/display/render").get_json()["payload"]
        self.assertEqual(rendered["screen_id"], screen["id"])
        self.assertEqual(rendered["display_filters"][0]["name"], "Olympia")
        self.assertIn("theme", rendered)

    def test_filter_and_data_filter_boundaries_are_separate(self):
        filters_service = (APP / "stats_core" / "services" / "filters.py").read_text(encoding="utf-8")
        screens_service = (APP / "stats_core" / "services" / "screens.py").read_text(encoding="utf-8")
        self.assertNotIn("source_config", filters_service)
        self.assertNotIn("adapter", filters_service.lower())
        self.assertIn('"filter_ids"', screens_service)
        self.assertNotIn("display_filter_mappings", screens_service)
        self.assertNotIn("filter_values", screens_service)
        data_ui = (APP / "static" / "settings" / "data.js").read_text(encoding="utf-8")
        filter_ui = (APP / "static" / "settings" / "filters.js").read_text(encoding="utf-8")
        self.assertIn("Data Filters", data_ui)
        self.assertIn("actual pulled Report data", filter_ui)
        self.assertIn("/api/filters/preview", filter_ui)

    def test_tableau_is_replaceable_adapter_only(self):
        bootstrap = (APP / "stats_core" / "bootstrap.py").read_text(encoding="utf-8")
        self.assertIn("from sources.tableau_adapter import TableauAdapter", bootstrap)
        violations = []
        for root in (APP / "stats_core" / "services", APP / "stats_core" / "repositories", APP / "stats_core" / "theme", APP / "stats_core" / "web"):
            for path in root.rglob("*.py"):
                text = path.read_text(encoding="utf-8").lower()
                if "sources.tableau" in text or "from sources import tableau" in text:
                    violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_no_legacy_settings_or_display_shell(self):
        settings = (APP / "templates" / "settings.html").read_text(encoding="utf-8")
        display = (APP / "templates" / "display.html").read_text(encoding="utf-8")
        self.assertNotIn('settings/base.html', settings)
        self.assertNotIn('data-screen-display.js', settings)
        self.assertNotIn('windows-sidebar.js', settings)
        for script in ("runtime.js", "shell.js", "data.js", "filters.js", "screens.js", "display.js"):
            self.assertIn(f"/static/settings/{script}", settings)
        self.assertIn('/static/display/app.js', display)
        self.assertNotIn('custom-screen.js', display)
        self.assertFalse((APP / "static" / "settings" / "data-screen-display.js").exists())
        self.assertFalse((APP / "static" / "display" / "custom-screen.js").exists())

    def test_core_has_no_builtin_screen_contract(self):
        for path in (
            APP / "stats_core" / "services" / "screens.py",
            APP / "stats_core" / "services" / "display.py",
            APP / "stats_core" / "repositories" / "display.py",
            APP / "stats_core" / "repositories" / "data_catalog.py",
        ):
            self.assertNotIn("builtin:", path.read_text(encoding="utf-8"), str(path))

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
        self.assertEqual(versioned, [])


if __name__ == "__main__":
    unittest.main()
