"""Reusable Fields matching and blank-cell policy, with isolated snapshots only."""
from __future__ import annotations

import ast
import copy
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


class FieldMatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {"STATS_DATA_DIR": self.temp.name})
        environment.start()
        self.addCleanup(environment.stop)
        from flask import Flask
        from stats_core.repositories import Repositories
        from stats_core.services.fields import FieldService
        from stats_core.services.groups import GroupService
        from stats_core.services.reports import ReportService
        from stats_core.theme.service import ThemeService
        from stats_core.web.fields import blueprint

        self.repos = Repositories(data_root=self.temp.name)
        self.repos.data_catalog.save({"sources": [{"id": "fixture", "adapter": "fixture"}],
            "reports": [{"id": key, "name": key.title(), "source_id": "fixture", "runtime": {}} for key in ("sales", "goals", "offices")]})
        self.columns = [{"key": "ID", "label": "ID", "type": "text"},
                        {"key": "Name", "label": "Name", "type": "text"},
                        {"key": "Amount", "label": "Amount", "type": "number"},
                        {"key": "Count", "label": "Count", "type": "number"},
                        {"key": "Rate", "label": "Rate", "type": "percent"}]
        self.replace("sales", [{"ID": "A", "Name": "Alex", "Amount": 100, "Count": 2},
                               {"ID": "B", "Name": "Blair", "Amount": 200, "Count": 4}])
        self.replace("goals", [{"ID": "A", "Name": "Alex", "Amount": 500},
                               {"ID": "C", "Name": "Casey", "Amount": 700}])
        self.replace("offices", [{"ID": "A", "Name": "North", "Amount": 900},
                                 {"ID": "D", "Name": "South", "Amount": 800}])
        self.reports = ReportService(self.repos, {"fixture": SimpleNamespace(report_value=lambda report: "")})
        self.themes = ThemeService(self.repos)
        self.groups = GroupService(self.repos, self.reports, self.themes)
        self.dependents = {}
        self.fields = FieldService(self.repos, self.reports, self.groups, self.themes,
                                   dependencies=lambda field_id: self.dependents.get(field_id, []))
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(blueprint(self.fields))
        self.client = self.app.test_client()

    def replace(self, report_id, rows):
        self.repos.report_data.replace(report_id, self.columns, rows, {"status": "Fixture"})

    def fid(self, report_id, key):
        return self.fields.field_id(report_id, key)

    def matching(self, left="sales", right="goals", **extra):
        return {"name": "Members", "left_field_id": self.fid(left, "ID"),
                "right_field_id": self.fid(right, "ID"), **extra}

    def test_preview_and_compatibility_are_read_only_and_never_guess(self):
        field_ids = [self.fid("sales", "Amount"), self.fid("goals", "Amount")]
        before = copy.deepcopy(self.repos.report_data.read("sales"))
        version = self.repos.meta.get("settings_version")
        response = self.client.post("/api/fields/compatibility", json={"field_ids": field_ids}).get_json()
        self.assertEqual(response["status"], "matching_required")
        self.assertFalse(response["compatible"])
        preview = self.client.post("/api/fields/matches/preview", json=self.matching()).get_json()
        self.assertEqual(preview["counts"]["matched_rows"], 1)
        self.assertEqual(preview["counts"]["left_only_rows"], 1)
        self.assertEqual(preview["counts"]["right_only_rows"], 1)
        self.assertEqual(len(preview["rows"]), 3)
        self.assertEqual(self.fields.matching_rules(), [])
        self.assertEqual(self.repos.meta.get("settings_version"), version)
        self.assertEqual(self.repos.report_data.read("sales"), before)

    def test_explicit_rule_reused_by_different_selections_with_outer_rows_and_zeros(self):
        saved = self.client.post("/api/fields/matches", json=self.matching())
        self.assertEqual(saved.status_code, 200, saved.get_json())
        rule = saved.get_json()["rule"]
        ids = [self.fid("sales", "Name"), self.fid("sales", "Amount"), self.fid("goals", "Name"), self.fid("goals", "Amount")]
        payload = self.fields.evaluate(ids)
        self.assertEqual([[row.get(field_id) for field_id in ids] for row in payload["rows"]], [
            ["Alex", 100, "Alex", 500], ["Blair", 200, None, 0], [None, 0, "Casey", 700]])
        self.assertEqual(payload["matching"]["rule_ids"], [rule["id"]])
        self.assertTrue(self.fields.compatibility(ids)["compatible"])
        other_selection = self.fields.evaluate([self.fid("goals", "Amount"), self.fid("sales", "Count")])
        self.assertEqual(len(other_selection["rows"]), 3)
        self.assertTrue(all(row.get("__row_key") for row in payload["rows"]))
        self.assertNotIn("report_id", str(payload))
        self.assertNotIn("source_id", str(payload))

    def test_matching_is_exact_no_casefold_or_blank_cross_product(self):
        self.replace("sales", [{"ID": "Alex", "Amount": 1}, {"ID": "", "Amount": 2}, {"ID": None, "Amount": 3}])
        self.replace("goals", [{"ID": "alex", "Amount": 4}, {"ID": " ", "Amount": 5}])
        preview = self.fields.preview_matching(self.matching())
        self.assertEqual(preview["counts"]["matched_rows"], 0)
        self.assertEqual(len(preview["rows"]), 5)
        self.fields.save_matching(self.matching())
        payload = self.fields.evaluate([self.fid("sales", "Amount"), self.fid("goals", "Amount")])
        self.assertEqual(len(payload["rows"]), 5)
        self.assertEqual(sum(row[self.fid("sales", "Amount")] for row in payload["rows"]), 6)
        self.assertEqual(sum(row[self.fid("goals", "Amount")] for row in payload["rows"]), 9)

    def test_numeric_identity_does_not_round_distinct_large_ids_into_a_match(self):
        from stats_core.services.field_matching import match_key
        self.assertNotEqual(match_key(9007199254740992, "number"), match_key(9007199254740993, "number"))
        self.assertEqual(match_key(1, "number"), match_key("1.00", "number"))
        self.assertEqual(match_key("-0", "number"), match_key(0, "number"))

    def test_repeated_keys_block_save_and_future_evaluation_without_multiplying(self):
        rule = self.fields.save_matching(self.matching())
        self.replace("goals", [{"ID": "A", "Amount": 5}, {"ID": "A", "Amount": 6}])
        from stats_core.errors import ValidationError
        with self.assertRaisesRegex(ValidationError, "repeat"):
            self.fields.preview_matching({**self.matching(), "id": rule["id"]}, rule["id"])
        ids = [self.fid("sales", "Amount"), self.fid("goals", "Amount")]
        with self.assertRaisesRegex(ValidationError, "repeat"):
            self.fields.evaluate(ids)
        self.assertEqual(self.fields.compatibility(ids)["status"], "ambiguous_rows")
        self.assertEqual(len(self.fields.matching_rules()), 1)

    def test_transitive_saved_matches_keep_every_row_and_prevent_ambiguous_paths(self):
        first = self.fields.save_matching(self.matching())
        second = self.fields.save_matching(self.matching("goals", "offices"))
        ids = [self.fid("sales", "Amount"), self.fid("offices", "Amount")]
        payload = self.fields.evaluate(ids)
        self.assertEqual(len(payload["rows"]), 4)
        self.assertEqual(payload["matching"]["rule_ids"], [first["id"], second["id"]])
        from stats_core.errors import ValidationError
        with self.assertRaisesRegex(ValidationError, "already have"):
            self.fields.save_matching(self.matching("sales", "offices"))

    def test_deletion_and_retargeting_guard_consumers_and_protect_field_types(self):
        rule = self.fields.save_matching(self.matching())
        for report_id in ("sales", "goals"):
            self.dependents[self.fid(report_id, "Amount")] = ["Comparison Widget"]
        deletion = self.client.delete(f"/api/fields/matches/{rule['id']}")
        self.assertEqual(deletion.status_code, 400)
        self.assertIn("Comparison Widget", deletion.get_json()["error"])
        renamed = self.client.put(f"/api/fields/matches/{rule['id']}", json=self.matching(name="Renamed"))
        self.assertEqual(renamed.status_code, 200, renamed.get_json())
        changed = self.client.put(f"/api/fields/matches/{rule['id']}", json=self.matching(left_field_id=self.fid("sales", "Name")))
        self.assertEqual(changed.status_code, 400)
        self.assertEqual(self.fields.matching_field_references(self.fid("sales", "ID")), ["row match 'Renamed'"])
        type_change = self.client.put("/api/fields/sales/ID", json={"kind": "report", "label": "ID", "type": "number"})
        self.assertEqual(type_change.status_code, 400)
        self.dependents.clear()
        self.assertEqual(self.client.delete(f"/api/fields/matches/{rule['id']}").status_code, 200)

    def _screen_consumers(self):
        from stats_core.services.widgets import WidgetService
        from stats_core.services.screens import ScreenService
        widgets = WidgetService(self.repos.widgets, self.fields, self.repos.meta)
        screens = ScreenService(self.repos.screens, widgets, self.groups, self.themes, self.repos.meta)
        self.fields.matching_consumers = lambda: [*widgets.field_consumers(), *screens.field_consumers()]
        return widgets, screens

    def test_match_deletion_checks_full_screen_query_with_ranking_outside_widget_fields(self):
        rule = self.fields.save_matching(self.matching())
        widgets, screens = self._screen_consumers()
        widget = widgets.save({"name": "Sales only", "kind": "table", "field_ids": [self.fid("sales", "Amount")]})
        screen = screens.save({"name": "Office", "widgets": [{"widget_id": widget["id"],
            "ranking": [{"field_id": self.fid("goals", "Amount"), "direction": "desc"}],
            "identity_field_id": self.fid("sales", "ID")}], "assets": []})
        self.assertEqual(screens.field_references(self.fid("sales", "ID")), ["Office"])
        consumer = screens.field_consumers()[0]
        self.assertEqual(set(consumer["field_ids"]), {self.fid("sales", "Amount"), self.fid("goals", "Amount"), self.fid("sales", "ID")})
        from stats_core.errors import ValidationError
        with self.assertRaisesRegex(ValidationError, "Office"):
            self.fields.delete_matching(rule["id"])
        screens.delete(screen["id"])
        self.fields.delete_matching(rule["id"])

    def test_unrelated_widget_instances_do_not_form_a_false_matching_dependency(self):
        rule = self.fields.save_matching(self.matching())
        widgets, screens = self._screen_consumers()
        left = widgets.save({"name": "Sales only", "kind": "table", "field_ids": [self.fid("sales", "Amount")]})
        right = widgets.save({"name": "Goals only", "kind": "table", "field_ids": [self.fid("goals", "Amount")]})
        screens.save({"name": "Separate panels", "widgets": [{"widget_id": left["id"]}, {"widget_id": right["id"]}], "assets": []})
        self.assertEqual(len(screens.field_consumers()), 2)
        self.fields.delete_matching(rule["id"])
        self.assertEqual(self.fields.matching_rules(), [])

    def test_numeric_blanks_are_zero_but_invalid_and_zero_division_remain_unavailable(self):
        self.replace("sales", [
            {"ID": "A", "Name": "", "Amount": None, "Rate": " ", "Count": 2},
            {"ID": "B", "Name": None, "Amount": " ", "Rate": "", "Count": 0},
            {"ID": "C", "Amount": "bad", "Count": 1, "Rate": "Infinity"},
        ])
        calculated = self.fields.save_calculated("sales", {"label": "Average", "formula": "[Amount] / [Count]", "type": "number"})
        ids = [self.fid("sales", key) for key in ("Name", "Amount", "Rate", calculated["key"])]
        payload = self.fields.evaluate(ids)
        self.assertEqual([row[ids[1]] for row in payload["rows"]], [0, 0, None])
        self.assertEqual([row[ids[2]] for row in payload["rows"]], [0, 0, None])
        self.assertEqual([row[ids[3]] for row in payload["rows"]], [0, None, None])
        self.assertEqual([row[ids[0]] for row in payload["rows"]], ["", None, None])
        self.assertIn(ids[3], payload["rows"][1]["__invalid_fields"])
        self.assertIn(ids[1], payload["rows"][2]["__invalid_fields"])
        self.assertIsNone(self.reports.rows("sales")[0]["Amount"])
        self.assertEqual(payload["fields"][3]["formula"], "[Amount] / [Count]")

    def test_explicit_identity_is_stable_across_ordering_and_period_source_calls(self):
        ids = [self.fid("sales", "Amount")]
        default = self.fields.evaluate(ids)
        self.assertTrue(all("__row_key" not in row for row in default["rows"]))
        context = {"identity_field_id": self.fid("sales", "ID")}
        baseline = self.fields.evaluate(ids, context)
        calls = []
        def rows_for_period(report_id, timeframe):
            calls.append((report_id, timeframe))
            return list(reversed(self.reports.rows(report_id)))
        self.fields.period_rows = rows_for_period
        period = {"kind": "year_to_date"}
        reversed_rows = self.fields.evaluate(ids, {**context, "timeframe": period})
        self.assertEqual(calls, [("sales", period)])
        self.assertEqual([row["__row_key"] for row in baseline["rows"]], list(reversed([row["__row_key"] for row in reversed_rows["rows"]])))
        self.assertEqual(len(self.fields.identity_fields(ids)), 4)
        self.replace("sales", [{"ID": "A", "Amount": 1}, {"ID": "A", "Amount": 2}])
        from stats_core.errors import ValidationError
        with self.assertRaisesRegex(ValidationError, "repeat"):
            self.fields.evaluate(ids, context)

    def test_unmatched_retained_values_are_not_replaced_by_zero_and_scope_is_applied_after_matching(self):
        self.fields.save_matching(self.matching())
        kind = self.groups.save_type({"name": "Teams", "report_id": "sales", "member_key_field": "ID", "member_label_field": "Name"})
        group = self.groups.save({"type_id": kind["id"], "name": "West", "member_keys": ["B"], "leader_member_key": "B", "leader_title": "Lead"})
        payload = self.fields.evaluate([self.fid("sales", "Amount"), self.fid("goals", "Amount")], {"group_ids": [group["id"]]})
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0][self.fid("sales", "Amount")], 200)
        self.assertEqual(payload["rows"][0][self.fid("goals", "Amount")], 0)

    def test_matching_responsibility_stays_in_fields_and_persistence_stays_in_repository(self):
        source = (ROOT / "app/stats_core/services/field_matching.py").read_text(encoding="utf-8")
        imports = [node.module or "" for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(any(name in module for name in ("repositories", "storage", "tableau", "screens", "widgets")) for module in imports))
        field_source = (ROOT / "app/stats_core/services/fields.py").read_text(encoding="utf-8")
        self.assertNotIn("con.execute", field_source)
        widget_source = (ROOT / "app/stats_core/services/widgets.py").read_text(encoding="utf-8")
        self.assertNotIn("full_outer", widget_source)
        self.assertNotIn("relationship_path", widget_source)
        frontend = (ROOT / "app/static/settings/fields.js").read_text(encoding="utf-8")
        self.assertIn("StatsFields=Object.freeze({openMatching})", frontend)
        self.assertIn('"/api/fields/matches/preview"', frontend)


if __name__ == "__main__":
    unittest.main()
