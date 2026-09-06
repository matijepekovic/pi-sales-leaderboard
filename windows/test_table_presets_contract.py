#!/usr/bin/env python3
"""Reusable table-preset domain, API, and Screen-link contract tests."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))


class TablePresetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["STATS_DATA_DIR"] = cls.temp.name
        from stats_core.bootstrap import create_app

        cls.app = create_app("windows", start_background=False)
        cls.app.config.update(TESTING=True)
        cls.client = cls.app.test_client()
        cls.runtime = cls.app.extensions["stats_runtime"]

        source = cls.client.post("/api/data/sources", json={
            "name": "Preset Contract Source",
            "adapter": "tableau",
            "connection": {
                "server": "https://example.invalid",
                "site": "test",
                "pat_name": "token",
            },
        }).get_json()["source"]
        report = cls.client.post("/api/data/reports", json={
            "source_id": source["id"],
            "name": "Preset Contract Report",
            "source_config": {"workbook": "Workbook", "sheet": "View"},
        }).get_json()["report"]
        cls.report_id = report["id"]
        cls.runtime.repos.report_data.replace(
            cls.report_id,
            [
                {"key": "Rep", "label": "Rep", "type": "text"},
                {"key": "Sales", "label": "Sales", "type": "number"},
                {"key": "Office", "label": "Office", "type": "text"},
            ],
            [
                {"Rep": "Alex", "Sales": 100, "Office": "Olympia"},
                {"Rep": "Blair", "Sales": 200, "Office": "Olympia"},
                {"Rep": "Casey", "Sales": 300, "Office": "Tacoma"},
                {"Rep": "Devon", "Sales": 400, "Office": "Tacoma"},
            ],
            {"status": "4 rows"},
        )
        group_type = cls.client.post("/api/group-types", json={
            "name": "Teams",
            "report_id": cls.report_id,
            "member_key_field": "Rep",
            "member_label_field": "Rep",
        }).get_json()["group_type"]
        cls.group_ids = []
        for name, members in (("North", ["Alex", "Blair"]), ("South", ["Casey", "Devon"])):
            response = cls.client.post("/api/groups", json={
                "type_id": group_type["id"],
                "name": name,
                "member_keys": members,
                "leader_title": "Manager",
                "leader_member_key": members[0],
            })
            cls.group_ids.append(response.get_json()["group"]["id"])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_linked_group_tables_migrate_then_follow_one_widget(self):
        created = self.client.post("/api/table-presets", json={
            "report_id": self.report_id,
            "name": "Team Leaderboard",
            "columns": ["__stats_rank", "Rep", "Sales"],
            "sort_field": "Sales",
            "sort_direction": "desc",
        })
        self.assertEqual(created.status_code, 200)
        preset = created.get_json()["table_preset"]
        preset_id = preset["id"]

        listed = self.client.get(f"/api/table-presets?report_id={self.report_id}")
        self.assertEqual([item["id"] for item in listed.get_json()["table_presets"]], [preset_id])

        original = {
            "id": "legacy-linked-teams",
            "name": "All Team Screens",
            "group_ids": self.group_ids,
            "tables": [
                {"group_id": group_id, "preset_id": preset_id, "columns": ["Office"]}
                for group_id in self.group_ids
            ],
            "theme_mode": "inherited",
        }
        self.runtime.repos.screens.save(original)
        blocked_legacy = self.client.delete(f"/api/table-presets/{preset_id}")
        self.assertEqual(blocked_legacy.status_code, 400)
        self.assertIn("Detach it there first", blocked_legacy.get_json()["error"])
        from stats_core.services.screen_migration import ScreenMigration
        migration = ScreenMigration(self.runtime.repos.screens, self.runtime.widgets,
                                    self.runtime.fields, self.runtime.groups,
                                    self.runtime.table_presets, self.runtime.filters).run()
        self.assertEqual(migration["errors"], [])
        saved = self.runtime.screens.get(original["id"])
        widget_ids = [instance["widget_id"] for instance in saved["widgets"]]
        self.assertEqual(len(set(widget_ids)), 1)
        self.assertEqual(self.runtime.repos.screens.read_legacy_backup(original["id"]), original)
        ids = dict(zip(["__stats_rank", "Rep", "Sales", "Office"],
                       self.runtime.fields.ids_for_report(self.report_id, ["__stats_rank", "Rep", "Sales", "Office"])))

        initial = self.client.get(f"/api/screens/{saved['id']}/preview").get_json()["payload"]
        self.assertEqual([field["key"] for field in initial["sections"][0]["fields"]], [
            ids["__stats_rank"], ids["Rep"], ids["Sales"],
        ])
        self.assertEqual([row[ids["Rep"]] for row in initial["sections"][0]["rows"]], ["Blair", "Alex"])

        updated = self.client.put(f"/api/widgets/{widget_ids[0]}", json={
            "name": "Team Leaderboard",
            "kind": "table", "field_ids": [ids["Rep"], ids["Office"], ids["Sales"]],
        })
        self.assertEqual(updated.status_code, 200)

        propagated = self.client.get(f"/api/screens/{saved['id']}/preview").get_json()["payload"]
        self.assertEqual([field["key"] for field in propagated["sections"][0]["fields"]], [
            ids["Rep"], ids["Office"], ids["Sales"],
        ])
        self.assertEqual([row[ids["Rep"]] for row in propagated["sections"][0]["rows"]], ["Blair", "Alex"])
        self.assertEqual([row[ids["Rep"]] for row in propagated["sections"][1]["rows"]], ["Devon", "Casey"])

        blocked = self.client.delete(f"/api/widgets/{widget_ids[0]}")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("All Team Screens", blocked.get_json()["error"])

        detached = dict(saved)
        detached["widgets"] = [{**instance, "ranking": [{"field_id": ids["Sales"], "direction": "asc"}]} for instance in saved["widgets"]]
        response = self.client.put(f"/api/screens/{saved['id']}", json=detached)
        self.assertEqual(response.status_code, 200)
        reordered = self.client.get(f"/api/screens/{saved['id']}/preview").get_json()["payload"]
        self.assertEqual([row[ids["Rep"]] for row in reordered["sections"][0]["rows"]], ["Alex", "Blair"])
        self.assertEqual([row[ids["Rep"]] for row in reordered["sections"][1]["rows"]], ["Casey", "Devon"])
        # The legacy preset can be removed once migrated; Widgets are independent.
        self.assertEqual(self.client.delete(f"/api/table-presets/{preset_id}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/screens/{saved['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/widgets/{widget_ids[0]}").status_code, 200)

    def test_presets_are_report_owned_and_require_real_fields(self):
        missing_fields = self.client.post("/api/table-presets", json={
            "report_id": self.report_id,
            "name": "Empty",
            "columns": ["does-not-exist"],
        })
        self.assertEqual(missing_fields.status_code, 400)
        self.assertIn("at least one Field", missing_fields.get_json()["error"])

        created = self.client.post("/api/table-presets", json={
            "report_id": self.report_id,
            "name": "Locked to Report",
            "columns": ["Rep"],
        }).get_json()["table_preset"]
        moved = self.client.put(f"/api/table-presets/{created['id']}", json={
            "report_id": "another-report",
            "name": created["name"],
            "columns": ["Rep"],
        })
        self.assertEqual(moved.status_code, 400)
        self.assertIn("cannot be moved", moved.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
