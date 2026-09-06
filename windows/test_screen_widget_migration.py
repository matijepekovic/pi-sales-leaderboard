#!/usr/bin/env python3
"""Stored Screen migration preserves definitions and reuses Widget presets."""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


class FixtureFields:
    def __init__(self):
        self.definitions = [
            {"id": "field-name", "key": "Name", "label": "Name", "kind": "report", "type": "text"},
            {"id": "field-net", "key": "Net", "label": "Net", "kind": "report", "type": "number"},
            {"id": "field-office", "key": "Office", "label": "Office", "kind": "report", "type": "text"},
            {"id": "field-rank", "key": "__stats_rank", "label": "Rank", "kind": "table", "type": "number"},
        ]

    def fields(self, report_id):
        if report_id != "report":
            from stats_core.errors import ValidationError
            raise ValidationError("Report not found.")
        return copy.deepcopy(self.definitions)

    def ids_for_report(self, report_id, keys):
        from stats_core.errors import ValidationError
        lookup = {field["key"]: field["id"] for field in self.fields(report_id)}
        if any(key not in lookup for key in keys):
            raise ValidationError("Field is unavailable")
        return [lookup[key] for key in keys]

    def resolve(self, field_ids):
        from stats_core.errors import ValidationError
        lookup = {field["id"]: field for field in self.definitions}
        if any(field_id not in lookup for field_id in field_ids):
            raise ValidationError("Field is unavailable")
        return [lookup[field_id] for field_id in field_ids]


class FixtureLookup:
    def __init__(self, items):
        self.items = {item["id"]: item for item in items}

    def get(self, resource_id):
        from stats_core.errors import ValidationError
        if resource_id not in self.items:
            raise ValidationError(f"Missing resource {resource_id}")
        return copy.deepcopy(self.items[resource_id])

    def get_type(self, type_id):
        return {"id": type_id, "report_id": "report"}


class ScreenWidgetMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["STATS_DATA_DIR"] = self.temp.name
        from stats_core.repositories import Repositories
        from stats_core.repositories.widgets import WidgetRepository
        from stats_core.services.widgets import WidgetService
        from stats_core.services.screen_migration import ScreenMigration
        self.repos = Repositories(data_root=self.temp.name)
        self.fields = FixtureFields()
        self.widget_repo = WidgetRepository()
        self.widgets = WidgetService(self.widget_repo, self.fields, self.repos.meta)
        self.presets = FixtureLookup([{"id": "preset", "report_id": "report", "name": "Leaderboard", "columns": ["__stats_rank", "Name", "Net"], "sort_field": "Net", "sort_direction": "desc"}])
        self.groups = FixtureLookup([{"id": "north", "type_id": "teams"}, {"id": "south", "type_id": "teams"}])
        self.filters = FixtureLookup([
            {"id": "office-filter", "rules": [{"report_id": "report", "field": "Office", "operator": "equals", "value": "Olympia"}]},
            {"id": "other-filter", "rules": [{"report_id": "report", "field": "Office", "operator": "equals", "value": "Tacoma"}]},
        ])
        self.migration = ScreenMigration(self.repos.screens, self.widgets, self.fields, self.groups, self.presets, self.filters, {"content": {"x": 10, "y": 20, "width": 80, "height": 70}})

    @staticmethod
    def screen(screen_id, group_id="north", filter_ids=None):
        return {"id": screen_id, "name": screen_id.title(), "reports": [], "group_ids": [group_id],
                "tables": [{"group_id": group_id, "preset_id": "preset", "columns": ["Office"]}],
                "filter_ids": filter_ids or [], "theme_mode": "inherited", "theme_group_type_id": "teams"}

    def test_linked_presets_reuse_widget_and_sort_moves_to_instances(self):
        originals = [self.screen("screen-a"), self.screen("screen-b", "south")]
        self.repos.screens.save_all(originals)
        result = self.migration.run()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["migrated"], ["screen-a", "screen-b"])
        self.assertEqual(len(self.widget_repo.list()), 1)
        widget = self.widget_repo.list()[0]
        self.assertEqual(widget["field_ids"], ["field-rank", "field-name", "field-net"])
        self.assertNotIn("report_id", widget)
        self.assertNotIn("sort_field", widget)
        for original in originals:
            screen = self.repos.screens.get(original["id"])
            instance = screen["widgets"][0]
            self.assertEqual(instance["widget_id"], widget["id"])
            self.assertEqual(instance["group_ids"], original["group_ids"])
            self.assertEqual(instance["ranking"], [{"field_id": "field-net", "direction": "desc"}])
            self.assertEqual(instance["layout"], {"x": 10, "y": 20, "width": 80, "height": 70})
            self.assertEqual(instance["fit"]["rows"], 10)
            self.assertEqual(screen["winner_widget_id"], instance["id"])
            self.assertEqual(screen["theme_group_type_id"], "teams")
            self.assertEqual(self.repos.screens.read_legacy_backup(original["id"]), original)
            self.assertTrue({"reports", "group_ids", "tables", "filter_ids"}.isdisjoint(screen))

    def test_filter_meaning_is_preserved_and_different_filters_do_not_share(self):
        originals = [self.screen("a", filter_ids=["office-filter"]),
                     self.screen("b", "south", ["office-filter"]),
                     self.screen("c", "south", ["other-filter"])]
        self.repos.screens.save_all(originals)
        self.assertFalse(self.migration.run()["errors"])
        self.assertEqual(len(self.widget_repo.list()), 2)
        a = self.repos.screens.get("a")["widgets"][0]["widget_id"]
        b = self.repos.screens.get("b")["widgets"][0]["widget_id"]
        c = self.repos.screens.get("c")["widgets"][0]["widget_id"]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(self.widgets.get(a)["filters"], [{"field_id": "field-office", "operator": "equals", "value": "Olympia"}])

    def test_missing_field_preserves_entire_screen_without_partial_widgets(self):
        original = {"id": "broken", "name": "Broken", "reports": ["report"], "tables": [
            {"report_id": "report", "columns": ["Name", "Net"]},
            {"report_id": "report", "columns": ["deleted-field"]},
        ]}
        self.repos.screens.save(original)
        result = self.migration.run()
        self.assertEqual(result["migrated"], [])
        self.assertIn("unavailable", result["errors"][0]["error"])
        self.assertEqual(self.repos.screens.get("broken"), original)
        self.assertEqual(self.widget_repo.list(), [])

    def test_retry_reuses_deterministic_ids_and_keeps_first_backup(self):
        original = self.screen("a")
        self.repos.screens.save(original)
        converted, definitions = self.migration._plan(original)
        self.repos.screens.backup_legacy(original)
        self.widgets.save(definitions[0])
        self.assertEqual(self.migration.run()["migrated"], ["a"])
        self.assertEqual(len(self.widget_repo.list()), 1)
        self.assertEqual(self.repos.screens.get("a"), converted)
        self.repos.screens.backup_legacy({**original, "name": "Different"})
        self.assertEqual(self.repos.screens.read_legacy_backup("a"), original)
        self.assertEqual(self.migration.run(), {"migrated": [], "errors": []})

    def test_already_converted_screens_are_never_rewritten(self):
        current = {"id": "current", "name": "Current", "widgets": [], "custom_future_setting": True}
        self.repos.screens.save(current)
        self.assertEqual(self.migration.run(), {"migrated": [], "errors": []})
        self.assertEqual(self.repos.screens.get("current"), current)
        self.assertIsNone(self.repos.screens.read_legacy_backup("current"))

    def test_reports_without_saved_tables_expand_to_full_fields_and_valid_geometry(self):
        original = {"id": "all", "name": "All", "reports": ["report"], "tables": [], "theme_mode": "custom", "theme_id": "theme-a"}
        self.repos.screens.save(original)
        self.assertFalse(self.migration.run()["errors"])
        converted = self.repos.screens.get("all")
        self.assertEqual(self.widgets.get(converted["widgets"][0]["widget_id"])["field_ids"], ["field-name", "field-net", "field-office", "field-rank"])
        self.assertEqual(converted["theme_id"], "theme-a")
        self.assertEqual(converted["canvas"], {"width": 1920, "height": 1080})

    def test_theme_asset_slots_become_owned_screen_placements(self):
        original = self.screen("artwork")
        legacy = {"content": {"x": 20, "y": 10, "width": 75, "height": 80}, "asset_slots": [
            {"key": "hero", "x": 0, "y": 0, "width": 18, "height": 100, "fit": "cover"},
            {"key": "logo_small", "x": 80, "y": 0, "width": 15, "height": 10, "fit": "contain"},
        ]}
        self.migration.layout_defaults = copy.deepcopy(legacy)
        self.migration.asset_keys = lambda: ["hero", "logo_small"]
        self.repos.screens.save(original)
        self.assertEqual(self.migration.run()["errors"], [])
        converted = self.repos.screens.get("artwork")
        self.assertEqual(converted["widgets"][0]["layout"], legacy["content"])
        self.assertEqual([{key: value for key, value in item.items() if key != "id"} for item in converted["assets"]], legacy["asset_slots"])
        repeated, _definitions = self.migration._plan(original)
        self.assertEqual([item["id"] for item in repeated["assets"]], [item["id"] for item in converted["assets"]])
        self.migration.layout_defaults["asset_slots"][0]["width"] = 5
        self.assertEqual(self.repos.screens.get("artwork")["assets"][0]["width"], 18)
        self.assertEqual(self.repos.screens.read_legacy_backup("artwork"), original)

    def test_invalid_legacy_assets_preserve_original_without_partial_conversion(self):
        original = self.screen("bad-assets")
        self.migration.layout_defaults = {"asset_slots": [{"key": "hero", "x": 99, "width": 20}]}
        self.migration.asset_keys = ["hero"]
        self.repos.screens.save(original)
        result = self.migration.run()
        self.assertEqual(result["migrated"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(self.repos.screens.get("bad-assets"), original)
        self.assertEqual(self.widget_repo.list(), [])


if __name__ == "__main__":
    unittest.main()
