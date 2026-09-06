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
    def widget_for(self, report_id, keys, filters=None):
        fields = self.client.get(f"/api/fields/{report_id}").get_json()["fields"]
        ids = {field["key"]: field["id"] for field in fields}
        response = self.client.post("/api/widgets", json={
            "name": "Report table", "kind": "table", "field_ids": [ids[key] for key in keys],
            "filters": [{**rule, "field_id": ids[rule["field_id"]]} for rule in (filters or [])],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["widget"], ids

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
            "report_updates": "ReportUpdateService",
            "filters": "FilterService",
            "groups": "GroupService",
            "fields": "FieldService",
            "table_presets": "TablePresetService",
            "widgets": "WidgetService",
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
            "/api/data/sources", "/api/data/sources/<source_id>/report-values",
            "/api/data/sources/<source_id>/report-columns",
            "/api/data/reports", "/api/data/reports/<report_id>/inspect",
            "/api/data/reports/<report_id>/duplicates",
            "/api/data/reports/<report_id>/deduplication",
            "/api/data/reports/<report_id>/retained-rows",
            "/api/group-types", "/api/group-types/<type_id>",
            "/api/group-types/<type_id>/rows", "/api/groups", "/api/groups/<group_id>",
            "/api/fields", "/api/fields/<report_id>", "/api/fields/<report_id>/<field_key>",
            "/api/table-presets", "/api/table-presets/<preset_id>",
            "/api/filters", "/api/filters/preview", "/api/screens", "/api/screens/preview",
            "/api/display", "/api/display/render", "/api/screen-themes/<screen_id>",
            "/api/group-themes/<group_id>", "/api/theme-manifest",
            "/api/asset-library", "/api/windows/update/check",
            "/api/widgets", "/api/widgets/preview", "/api/fields/catalog",
            "/api/themes", "/api/themes/<theme_id>", "/api/groups/<group_id>/appearance",
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
            "runtime": {"update_interval_minutes": 15},
        })
        self.assertEqual(report.status_code, 200)
        report_id = report.get_json()["report"]["id"]
        self.assertEqual(report.get_json()["report"]["runtime"]["update_interval_minutes"], 15)

        updated_report = self.client.put(f"/api/data/reports/{report_id}", json={
            "source_id": source_id,
            "name": "Sales Competition",
            "source_config": {"workbook": "Workbook", "sheet": "View", "filters": []},
            "runtime": {"update_interval_minutes": 30},
        })
        self.assertEqual(updated_report.status_code, 200)
        self.assertEqual(updated_report.get_json()["report"]["runtime"]["update_interval_minutes"], 30)

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

        customized = self.client.put(f"/api/fields/{report_id}/Revenue", json={
            "kind": "report",
            "label": "Close Rate",
            "type": "percent",
            "decimals": 1,
        })
        self.assertEqual(customized.status_code, 200)
        customized_field = customized.get_json()["field"]
        self.assertEqual(customized_field["label"], "Close Rate")
        self.assertEqual(customized_field["type"], "percent")
        self.assertEqual(customized_field["source_label"], "Revenue")
        self.assertEqual(customized_field["source_type"], "number")
        self.assertEqual(customized_field["source_data_type"], "currency")
        raw_revenue = next(field for field in self.runtime.repos.report_data.read(report_id)["fields"] if field["key"] == "Revenue")
        self.assertEqual(raw_revenue, {"key": "Revenue", "label": "Revenue", "type": "currency"})

        invalid_text_conversion = self.client.put(f"/api/fields/{report_id}/Office", json={
            "kind": "report",
            "label": "Branch",
            "type": "number",
        })
        self.assertEqual(invalid_text_conversion.status_code, 400)
        self.assertIn("must stay Text", invalid_text_conversion.get_json()["error"])

        inspection = self.client.get(f"/api/data/reports/{report_id}/inspect").get_json()
        self.assertEqual(inspection["total_rows"], 3)
        office = next(field for field in inspection["fields"] if field["key"] == "Office")
        self.assertEqual(office["sample_values"], ["Olympia", "Tacoma"])
        revenue = next(field for field in inspection["fields"] if field["key"] == "Revenue")
        self.assertEqual((revenue["label"], revenue["type"]), ("Close Rate", "percent"))

        # A later source refresh replaces the raw snapshot, but the Report-owned
        # display formatting must remain applied to the new data.
        self.runtime.repos.report_data.replace(
            report_id,
            [
                {"key": "Rep", "label": "Rep", "type": "text"},
                {"key": "Office", "label": "Office", "type": "text"},
                {"key": "Revenue", "label": "Revenue", "type": "currency"},
            ],
            [
                {"Rep": "D", "Office": "Olympia", "Revenue": 0.25},
            ],
            {"status": "1 row", "last_refresh": "later"},
        )
        refreshed_inspection = self.client.get(f"/api/data/reports/{report_id}/inspect").get_json()
        refreshed_revenue = next(field for field in refreshed_inspection["fields"] if field["key"] == "Revenue")
        self.assertEqual((refreshed_revenue["label"], refreshed_revenue["type"]), ("Close Rate", "percent"))
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

        widget, field_ids = self.widget_for(report_id, ["Revenue", "Rep"], [
            {"field_id": "Office", "operator": "equals", "value": "Olympia"},
        ])
        created_screen = self.client.post("/api/screens", json={
            "name": "Olympia Revenue",
            "widgets": [{
                "widget_id": widget["id"],
                "ranking": [{"field_id": field_ids["Revenue"], "direction": "desc"}],
                "fit": {"rows": 10},
            }],
            "theme_mode": "custom",
        })
        self.assertEqual(created_screen.status_code, 200)
        screen = created_screen.get_json()["screen"]
        self.assertEqual(screen["widgets"][0]["widget_id"], widget["id"])
        self.assertNotIn("filter_ids", screen)
        self.assertNotIn("reports", screen)
        self.assertNotIn("tables", screen)
        self.assertNotIn("display_filter_mappings", screen)
        self.assertNotIn("filter_values", screen)

        preview = self.client.get(f"/api/screens/{screen['id']}/preview").get_json()["payload"]
        self.assertEqual(preview["mode"], "screen")
        self.assertEqual([row[field_ids["Rep"]] for row in preview["sections"][0]["rows"]], ["C", "A"])
        self.assertEqual([field["key"] for field in preview["sections"][0]["fields"]], [field_ids["Revenue"], field_ids["Rep"]])
        preview_revenue = next(field for field in preview["sections"][0]["fields"] if field["key"] == field_ids["Revenue"])
        self.assertEqual((preview_revenue["label"], preview_revenue["type"]), ("Close Rate", "percent"))

        saved_display = self.client.put("/api/display", json={
            "active_screen_id": screen["id"],
            "rotation_enabled": False,
            "rotation_screen_ids": [],
            "rotation_seconds": 20,
        })
        self.assertEqual(saved_display.status_code, 200)
        rendered = self.client.get("/api/display/render").get_json()["payload"]
        self.assertEqual(rendered["screen_id"], screen["id"])
        self.assertEqual(len(rendered["sections"][0]["rows"]), 2)
        self.assertEqual(self.runtime.widgets.get(widget["id"])["filters"][0]["value"], "Olympia")
        self.assertIn("theme", rendered)

    def test_duplicate_cleanup_is_user_selected_and_persists_on_report(self):
        source = self.client.post("/api/data/sources", json={
            "name": "Duplicate Test Source",
            "adapter": "tableau",
            "connection": {"server": "https://dedupe.example.invalid", "site": "test", "pat_name": "dedupe-token"},
        }).get_json()["source"]
        report = self.client.post("/api/data/reports", json={
            "source_id": source["id"],
            "name": "Duplicate Test Report",
            "source_config": {"workbook": "Workbook", "sheet": "View", "filters": []},
        }).get_json()["report"]
        self.runtime.repos.report_data.replace(
            report["id"],
            [
                {"key": "Rep", "label": "Rep", "type": "text"},
                {"key": "Sales", "label": "Sales", "type": "number"},
            ],
            [
                {"Rep": "Alex", "Sales": 10},
                {"Rep": "Blair", "Sales": 20},
                {"Rep": "alex", "Sales": 30},
                {"Rep": "", "Sales": 40},
                {"Rep": "", "Sales": 50},
            ],
            {"status": "5 rows"},
        )

        checked = self.client.get(f"/api/data/reports/{report['id']}/duplicates?field=Rep")
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.get_json()["duplicate_rows"], 1)
        self.assertEqual(checked.get_json()["groups"], [{"value": "Alex", "count": 2}])

        removed = self.client.put(
            f"/api/data/reports/{report['id']}/deduplication",
            json={"field": "Rep", "keep": "last"},
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.get_json()["removed"], 1)
        rows = self.runtime.repos.report_data.read(report["id"])["rows"]
        self.assertEqual([row["Sales"] for row in rows], [20, 30, 40, 50])
        saved = self.client.get("/api/data/reports").get_json()["reports"]
        saved_report = next(item for item in saved if item["id"] == report["id"])
        self.assertEqual(saved_report["cleanup"], {"deduplicate_by": "Rep", "deduplicate_keep": "last"})

        cleared = self.client.delete(f"/api/data/reports/{report['id']}/deduplication")
        self.assertEqual(cleared.status_code, 200)
        saved = self.client.get("/api/data/reports").get_json()["reports"]
        self.assertNotIn("cleanup", next(item for item in saved if item["id"] == report["id"]))
        self.assertEqual(self.client.delete(f"/api/data/reports/{report['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/data/sources/{source['id']}").status_code, 200)

    def test_group_theme_preserves_identity_without_editing_screen_geometry(self):
        source = self.client.post("/api/data/sources", json={
            "name": "Group Test Source",
            "adapter": "tableau",
            "connection": {"server": "https://groups.example.invalid", "site": "test", "pat_name": "group-token"},
        }).get_json()["source"]
        report = self.client.post("/api/data/reports", json={
            "source_id": source["id"],
            "name": "Group Test Report",
            "source_config": {"workbook": "Workbook", "sheet": "View", "filters": []},
        }).get_json()["report"]
        self.runtime.repos.report_data.replace(report["id"], [
            {"key": "Rep", "label": "Rep", "type": "text"},
            {"key": "Sales", "label": "Sales", "type": "number"},
        ], [{"Rep": "Alex", "Sales": 10}, {"Rep": "Blair", "Sales": 20}], {"status": "2 rows"})
        group_type_response = self.client.post("/api/group-types", json={
            "name": "Teams",
        })
        self.assertEqual(group_type_response.status_code, 200)
        group_type = group_type_response.get_json()["group_type"]
        self.assertEqual(group_type["report_id"], "")
        draft_rows = self.client.get(
            f"/api/group-types/{group_type['id']}/rows?report_id={report['id']}"
        ).get_json()
        self.assertEqual([row["_stats_member_key"] for row in draft_rows["rows"]], ["Alex", "Blair"])
        alex = self.client.post("/api/groups", json={
            "type_id": group_type["id"], "name": "Alex Team", "member_keys": ["Alex"],
            "report_id": report["id"],
            "leader_title": "Manager", "leader_member_key": "Alex",
        }).get_json()["group"]
        self.assertEqual(alex["report_id"], report["id"])
        self.assertEqual(alex["leader_title"], "Manager")
        self.assertEqual(alex["leader_member_key"], "Alex")
        blair = self.client.post("/api/groups", json={
            "type_id": group_type["id"], "name": "Blair Team", "member_keys": ["Blair"],
        }).get_json()["group"]
        self.assertEqual(self.client.put(f"/api/groups/{blair['id']}", json={
            "type_id": group_type["id"], "name": "Blair Team", "member_keys": ["Blair", "Alex"],
        }).status_code, 200)
        moved = self.client.get("/api/groups").get_json()["groups"]
        self.assertEqual(next(item for item in moved if item["id"] == alex["id"])["member_keys"], [])
        team_rows = self.client.get(f"/api/group-types/{group_type['id']}/rows").get_json()["rows"]
        alex_row = next(row for row in team_rows if row["Rep"] == "Alex")
        self.assertEqual(alex_row["_stats_groups"], [{"id": blair["id"], "name": "Blair Team"}])
        self.assertEqual(self.client.put(f"/api/groups/{alex['id']}", json={
            "type_id": group_type["id"], "name": "Alex Team", "member_keys": ["Alex"],
        }).status_code, 200)
        office_type = self.client.post("/api/group-types", json={"name": "Offices"}).get_json()["group_type"]
        alex_office = self.client.post("/api/groups", json={
            "type_id": office_type["id"], "name": "Olympia", "member_keys": ["Alex"],
            "report_id": report["id"],
        }).get_json()["group"]
        self.assertEqual(alex_office["member_keys"], ["Alex"])
        across_types = self.client.get("/api/groups").get_json()["groups"]
        self.assertEqual(next(item for item in across_types if item["id"] == alex["id"])["member_keys"], ["Alex"])
        group_rows = self.client.get(f"/api/group-types/{group_type['id']}/rows").get_json()
        self.assertEqual([field["key"] for field in group_rows["fields"]], ["Rep", "Sales"])
        self.assertEqual(group_rows["rows"][0]["_stats_groups"][0]["name"], "Alex Team")

        theme_layout = {
            "auto_fit": True,
            "content": {"x": 20, "y": 0, "width": 80, "height": 100},
            "asset_slots": [{"key": "hero", "x": 0, "y": 0, "width": 20, "height": 100, "fit": "contain"}],
        }
        original_layout = self.runtime.theme.effective_group_theme(blair["id"])["layout"]
        group_theme = self.client.put(f"/api/group-themes/{blair['id']}", json={
            "base": "starter",
            "colors": {"primary": "#123456"},
            "layout": theme_layout,
        })
        self.assertEqual(group_theme.status_code, 200)
        self.assertEqual(group_theme.get_json()["theme"]["colors"]["primary"], "#123456")
        self.assertEqual(group_theme.get_json()["theme"]["layout"], original_layout)
        self.assertEqual(self.runtime.groups.appearance(blair["id"])["style"]["colors"]["primary"], "#123456")

        widget, field_ids = self.widget_for(report["id"], ["Rep", "Sales"])
        created = self.client.post("/api/screens", json={
            "name": "Team Competition",
            "widgets": [{"widget_id": widget["id"], "group_ids": [alex["id"], blair["id"]],
                         "ranking": [{"field_id": field_ids["Sales"], "direction": "desc"}]}],
            "theme_mode": "inherited",
            "theme_group_type_id": group_type["id"],
        })
        self.assertEqual(created.status_code, 200)
        screen = created.get_json()["screen"]
        self.assertNotIn("layout", screen)
        preview = self.client.get(f"/api/screens/{screen['id']}/preview").get_json()["payload"]
        self.assertEqual(preview["inherited_theme_group_id"], blair["id"])
        self.assertEqual(preview["sections"][0]["rows"][0][field_ids["Rep"]], "Blair")
        self.assertNotIn("layout", preview)
        self.assertEqual(preview["theme"]["layout"], original_layout)
        effective_theme = self.client.get(f"/api/display/render?screen_id={screen['id']}").get_json()["payload"]["theme"]
        self.assertEqual(effective_theme["mode"], "inherited")
        self.assertEqual(effective_theme["inherited_group_id"], blair["id"])
        self.assertEqual(effective_theme["colors"]["primary"], "#123456")

        shared_update = self.client.put(f"/api/screen-themes/{screen['id']}", json={
            "base": "starter",
            "layout": {
                "auto_fit": False,
                "content": {"x": 10, "y": 12, "width": 75, "height": 70},
                "asset_slots": [{"key": "logo_small", "x": 1, "y": 2, "width": 12, "height": 13}],
            },
        })
        self.assertEqual(shared_update.status_code, 200)
        shared_layout = shared_update.get_json()["theme"]["layout"]
        self.assertEqual(shared_layout, original_layout)
        group_after_shared_update = self.client.get(f"/api/group-themes/{blair['id']}").get_json()["theme"]
        self.assertEqual(group_after_shared_update["layout"], shared_layout)
        manifest = self.client.get("/api/theme-manifest").get_json()["manifest"]
        placeable = {item["key"] for item in manifest["assets"] if item["placeable"]}
        self.assertIn("logo_small", placeable)
        self.assertNotIn("background", placeable)

        group_screen_response = self.client.post("/api/screens", json={
            "name": "Alex Team Screen",
            "widgets": [{"widget_id": widget["id"], "group_ids": [alex["id"]]}],
            "theme_mode": "group", "theme_group_id": alex["id"],
        })
        self.assertEqual(group_screen_response.status_code, 200)
        group_screen = group_screen_response.get_json()["screen"]
        group_preview = self.client.get(f"/api/screens/{group_screen['id']}/preview").get_json()["payload"]
        self.assertEqual(group_preview["theme"]["group_id"], alex["id"])
        self.assertEqual([row[field_ids["Rep"]] for row in group_preview["sections"][0]["rows"]], ["Alex"])
        self.assertEqual(group_preview["sections"][0]["rows"][0][field_ids["Sales"]], 10)
        mixed_screen = self.client.post("/api/screens", json={
            "name": "Invalid Mixed Screen", "reports": [report["id"]], "group_ids": [alex["id"]],
            "tables": [], "theme_mode": "inherited",
        })
        self.assertEqual(mixed_screen.status_code, 400)
        self.assertIn("reusable Widgets", mixed_screen.get_json()["error"])

        blocked = self.client.delete(f"/api/groups/{blair['id']}")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("used by", blocked.get_json()["error"])
        self.assertEqual(self.client.delete(f"/api/screens/{screen['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/screens/{group_screen['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/groups/{alex['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/groups/{blair['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/groups/{alex_office['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/group-types/{group_type['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/group-types/{office_type['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/widgets/{widget['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/data/reports/{report['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/data/sources/{source['id']}").status_code, 200)

    def test_report_snapshot_keeps_missing_rows_until_window_moves_past_them(self):
        self.assertTrue(self.runtime.reports._runtime({})["keep_last_known_rows"])
        self.assertFalse(self.runtime.reports._runtime({"keep_last_known_rows": False})["keep_last_known_rows"])
        source = self.client.post("/api/data/sources", json={
            "name": "Retention Test Source",
            "adapter": "tableau",
            "connection": {"server": "https://retention.example.invalid", "site": "test", "pat_name": "token"},
        }).get_json()["source"]
        report = self.client.post("/api/data/reports", json={
            "source_id": source["id"],
            "name": "Retention Test Report",
            "source_config": {"workbook": "Workbook", "sheet": "View", "filters": []},
        }).get_json()["report"]
        fields = [
            {"key": "Rep", "label": "Name", "type": "text"},
            {"key": "Sales", "label": "Sales", "type": "number"},
        ]
        previous = {
            "fields": fields,
            "rows": [{"Rep": "Alex", "Sales": 10}, {"Rep": "Blair", "Sales": 20}],
            "meta": {"start": "2026-09-01", "end": "2026-09-30", "identity_field": "Rep"},
        }
        same_window, identity, retained = self.runtime.reports._merge_refresh_rows(
            previous, fields, [{"Rep": "Alex", "Sales": 15}], "2026-09-01", "2026-09-30"
        )
        self.assertEqual(identity, "Rep")
        self.assertEqual(same_window, [{"Rep": "Alex", "Sales": 15}, {"Rep": "Blair", "Sales": 20}])
        self.assertEqual(retained, ["Blair"])
        zero_is_an_update, _, _ = self.runtime.reports._merge_refresh_rows(
            previous, fields, [{"Rep": "Alex", "Sales": 0}], "2026-09-01", "2026-09-30"
        )
        self.assertEqual(zero_is_an_update[0], {"Rep": "Alex", "Sales": 0})

        wider_window, _, wider_retained = self.runtime.reports._merge_refresh_rows(
            previous, fields, [{"Rep": "Alex", "Sales": 100}], "2026-01-01", "2026-12-31"
        )
        self.assertEqual(wider_window[-1], {"Rep": "Blair", "Sales": 20})
        self.assertEqual(wider_retained, ["Blair"])

        next_month, _, next_retained = self.runtime.reports._merge_refresh_rows(
            previous, fields, [{"Rep": "Alex", "Sales": 5}], "2026-10-01", "2026-10-31"
        )
        self.assertEqual(next_month, [{"Rep": "Alex", "Sales": 5}])
        self.assertEqual(next_retained, [])

        self.runtime.repos.report_data.replace(report["id"], fields, same_window, {
            "status": "2 rows", "start": "2026-09-01", "end": "2026-09-30",
            "identity_field": "Rep", "retained_row_keys": ["Blair"],
        })
        inspection = self.client.get(f"/api/data/reports/{report['id']}/inspect").get_json()
        self.assertEqual(inspection["retention"]["saved_missing"], [{"identity": "Blair", "label": "Blair"}])
        removed = self.client.delete(
            f"/api/data/reports/{report['id']}/retained-rows", json={"identity": "Blair"}
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(self.runtime.reports.rows(report["id"]), [{"Rep": "Alex", "Sales": 15}])
        self.assertEqual(self.client.delete(f"/api/data/reports/{report['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/data/sources/{source['id']}").status_code, 200)

    def test_fields_widgets_and_screen_context_use_their_public_owners(self):
        data_ui = (APP / "static" / "settings" / "data.js").read_text(encoding="utf-8")
        fields_ui = (APP / "static" / "settings" / "fields.js").read_text(encoding="utf-8")
        screens_ui = (APP / "static" / "settings" / "screens.js").read_text(encoding="utf-8")
        widgets_ui = (APP / "static" / "settings" / "widgets.js").read_text(encoding="utf-8")
        groups_ui = (APP / "static" / "settings" / "groups.js").read_text(encoding="utf-8")
        settings = (APP / "templates" / "settings.html").read_text(encoding="utf-8")
        self.assertIn("Data Filters", data_ui)
        self.assertIn("Filter the data pulled", data_ui)
        self.assertIn("Display last known value", data_ui)
        self.assertIn("StatsFieldEditor", fields_ui)
        self.assertIn("/api/fields", fields_ui)
        self.assertIn("+ Calculated Field", fields_ui)
        self.assertIn("+ Group Field", fields_ui)
        self.assertIn("Rounding decimals", fields_ui)
        self.assertNotIn("currency", fields_ui.lower())
        self.assertIn("StatsFieldEditor", data_ui)
        self.assertIn("/api/fields/catalog", widgets_ui)
        self.assertIn("/api/widgets", screens_ui)
        self.assertIn("data-widget-drag", widgets_ui)
        self.assertIn("remove-field", widgets_ui)
        self.assertNotIn("/api/data/reports", screens_ui)
        self.assertNotIn("/api/data/reports", widgets_ui)
        theme_ui = (APP / "static" / "settings" / "theme.js").read_text(encoding="utf-8")
        self.assertNotIn("StatsThemeLayoutEditor", screens_ui)
        self.assertNotIn("data-theme-layout-auto-fit", screens_ui)
        self.assertNotIn("StatsThemeLayoutEditor", theme_ui)
        self.assertIn("StatsWidgetRenderer", theme_ui)
        self.assertIn("Save Group Style", theme_ui)
        self.assertIn("data-screen-fit", screens_ui)
        self.assertIn("data-instance-group", screens_ui)
        self.assertIn("theme_group_type_id", screens_ui)
        self.assertIn("Every column", groups_ui)
        self.assertIn("data-member-key", groups_ui)
        self.assertIn("/api/group-types", groups_ui)
        self.assertIn("Look for duplicates", data_ui)
        self.assertIn("apply-deduplication", data_ui)
        self.assertIn("settingsFields", settings)
        self.assertIn("settingsFieldsHost", settings)
        self.assertNotIn("settingsDisplayValues", settings)
        self.assertNotIn("/api/filters", fields_ui)
        self.assertNotIn("/api/filters", screens_ui)
        self.assertNotIn("settingsFilters", settings)
        self.assertFalse((APP / "static" / "settings" / "filters.js").exists())

    def test_source_report_choices_are_vendor_neutral(self):
        source_service = (APP / "stats_core" / "services" / "source.py").read_text(encoding="utf-8")
        report_service = (APP / "stats_core" / "services" / "reports.py").read_text(encoding="utf-8")
        data_web = (APP / "stats_core" / "web" / "data.py").read_text(encoding="utf-8")
        data_ui = (APP / "static" / "settings" / "data.js").read_text(encoding="utf-8")
        adapter = (APP / "sources" / "tableau_adapter.py").read_text(encoding="utf-8")

        self.assertIn("report_values_for", source_service)
        self.assertNotIn("workbooks_for", source_service)
        self.assertNotIn("all_views_for", source_service)
        self.assertNotIn("views_for", source_service)
        self.assertNotIn("workbook", report_service.lower())
        self.assertIn("/report-values", data_web)
        self.assertNotIn("/workbooks", data_web)
        self.assertIn("/report-values", data_ui)
        self.assertNotIn("Reload Workbooks", data_ui)
        self.assertNotIn('data-report="workbook"', data_ui)
        self.assertNotIn('data-report="sheet"', data_ui)
        self.assertNotIn('data-report="source_id"', data_ui)
        self.assertIn("def report_values", adapter)
        self.assertIn("def configure_report_value", adapter)

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
        for script in ("runtime.js", "shell.js", "overview.js", "data.js", "fields.js", "widgets.js", "theme.js", "groups.js", "screens.js", "display.js", "software.js"):
            self.assertIn(f"/static/settings/{script}", settings)
        self.assertIn("/static/runtime/widget-renderer.js", settings)
        self.assertIn("/static/runtime/widget-renderer.js", display)
        self.assertFalse((APP / "static" / "settings" / "display-values.js").exists())
        self.assertNotIn('/static/settings/filters.js', settings)
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

    def test_module_boundaries_do_not_read_other_domain_storage(self):
        theme = (APP / "stats_core" / "theme" / "service.py").read_text(encoding="utf-8")
        screens = (APP / "stats_core" / "services" / "screens.py").read_text(encoding="utf-8")
        groups = (APP / "stats_core" / "services" / "groups.py").read_text(encoding="utf-8")
        for forbidden in ("repos.screens", "repos.groups"):
            self.assertNotIn(forbidden, theme)
        for forbidden in ("self.reports", "self.filters", "self.fields", "repos.report_data", "repos.fields", "repos.filters"):
            self.assertNotIn(forbidden, screens)
        self.assertNotIn("repos.screens", groups)

    def test_public_asset_files_do_not_unlock_editor_apis(self):
        import io
        asset = self.client.post("/api/asset-library/logo_small", data={
            "asset": (io.BytesIO(b"isolated-test-artwork"), "logo.png"),
        })
        self.assertEqual(asset.status_code, 200, asset.get_json())
        item = asset.get_json()
        changed = self.client.post("/api/auth/pin", json={"new_pin": "4927"})
        self.assertEqual(changed.status_code, 200)
        try:
            anonymous = self.app.test_client()
            picture = anonymous.get(item["url"])
            try:
                self.assertEqual(picture.status_code, 200)
                self.assertEqual(picture.data, b"isolated-test-artwork")
            finally:
                picture.close()
            self.assertEqual(anonymous.get("/api/themes").status_code, 401)
            self.assertEqual(anonymous.get("/api/groups").status_code, 401)
            self.assertEqual(anonymous.delete(item["url"]).status_code, 401)
        finally:
            self.client.post("/api/auth/pin", json={"new_pin": ""})
            self.client.delete(item["url"])

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
