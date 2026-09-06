#!/usr/bin/env python3
"""Widget behavior and the Fields-only architecture boundary."""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


class WidgetContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["STATS_DATA_DIR"] = self.temp.name
        from flask import Flask
        from stats_core.repositories import Repositories
        from stats_core.repositories.widgets import WidgetRepository
        from stats_core.services.fields import FieldService
        from stats_core.services.groups import GroupService
        from stats_core.services.reports import ReportService
        from stats_core.services.widgets import WidgetService
        from stats_core.theme.service import ThemeService
        from stats_core.web import fields as fields_web, widgets as widgets_web

        self.repos = Repositories(data_root=self.temp.name)
        self.repos.data_catalog.save({"sources": [{"id": "source", "adapter": "fixture"}], "reports": [
            {"id": "report", "name": "Sales", "source_id": "source", "runtime": {}},
            {"id": "other", "name": "Other", "source_id": "source", "runtime": {}},
        ]})
        self.repos.report_data.replace("report", [
            {"key": "Name", "label": "Name", "type": "text"},
            {"key": "Net", "label": "Net", "type": "number"},
            {"key": "Cancelled", "label": "Cancelled", "type": "number"},
            {"key": "Rate", "label": "Rate", "type": "percent"},
        ], [
            {"Name": "Alex", "Net": 100, "Cancelled": 20, "Rate": "25%"},
            {"Name": "Blair", "Net": 100, "Cancelled": 30, "Rate": 0.50},
            {"Name": "Casey", "Net": 500, "Cancelled": 0, "Rate": 0.10},
            {"Name": "Devon", "Net": None, "Cancelled": 10, "Rate": None},
        ], {"status": "4 rows"})
        self.repos.report_data.replace("other", [{"key": "Net", "label": "Net", "type": "number"}], [{"Net": 1}], {})
        self.reports = ReportService(self.repos, {"fixture": SimpleNamespace(report_value=lambda report: "")})
        self.theme = ThemeService(self.repos)
        self.groups = GroupService(self.repos, self.reports, self.theme)
        self.repository = WidgetRepository()
        self.fields = FieldService(self.repos, self.reports, self.groups, self.theme, dependencies=self.repository.field_dependents)
        self.widgets = WidgetService(self.repository, self.fields, self.repos.meta, dependencies=lambda widget_id: self.widget_dependents)
        self.widget_dependents = []
        self.ids = dict(zip(["Name", "Net", "Cancelled", "Rate", "__stats_rank"], self.fields.ids_for_report("report", ["Name", "Net", "Cancelled", "Rate", "__stats_rank"])))
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True)
        self.app.register_blueprint(fields_web.blueprint(self.fields))
        self.app.register_blueprint(widgets_web.blueprint(self.widgets))
        self.client = self.app.test_client()

    def definition(self, **overrides):
        return {"name": "Leaderboard", "kind": "table", "field_ids": [self.ids["Name"], self.ids["Net"]], "filters": [], **overrides}

    def group(self, name, members, type_id=None):
        definition = self.groups.get_type(type_id) if type_id else self.groups.save_type({"name": "Teams", "report_id": "report", "member_key_field": "Name", "member_label_field": "Name"})
        return self.groups.save({"type_id": definition["id"], "name": name, "member_keys": members, "leader_member_key": members[0], "leader_title": "Lead"})

    def test_chart_order_survives_save_and_reopen_without_reordering_table_rows(self):
        widget = self.widgets.save(self.definition(kind="line", chart={
            "dimension_field_id": self.ids["Net"], "measure_field_ids": [self.ids["Net"]],
            "aggregation": "none", "category_order": "number",
        }, filters=[{"field_id": self.ids["Net"], "operator": "greater_than", "value": 0}]))
        reopened = self.widgets.get(widget["id"])
        self.assertEqual(reopened["chart"]["category_order"], "number")
        payload = self.widgets.preview(reopened)
        self.assertEqual([row[self.ids["Name"]] for row in payload["rows"]], ["Alex", "Blair", "Casey"])
        self.assertEqual(payload["chart"]["series"][0]["row_indices"], [[0], [1], [2]])
        # Unsupported order modes fail at the public contract boundary.
        response = self.client.post("/api/widgets/preview", json={"widget": {
            **reopened, "chart": {**reopened["chart"], "category_order": "guess"},
        }})
        self.assertEqual(response.status_code, 400)

    def test_crud_uses_field_ids_and_survives_global_display_edits(self):
        catalog = self.client.get("/api/fields/catalog").get_json()
        self.assertTrue(catalog["ok"])
        self.assertEqual(len(catalog["reports"]), 2)
        created = self.client.post("/api/widgets", json=self.definition())
        self.assertEqual(created.status_code, 200, created.get_json())
        widget = created.get_json()["widget"]
        original_id = self.ids["Net"]
        self.fields.update_report_field("report", "Net", {"label": "Net Sales", "type": "percent", "decimals": 1})
        self.assertEqual(self.fields.ids_for_report("report", ["Net"]), [original_id])
        rendered = self.widgets.render(widget["id"])
        self.assertEqual(rendered["fields"][1]["label"], "Net Sales")
        self.assertEqual(rendered["fields"][1]["type"], "percent")
        self.assertEqual(rendered["rows"][0][original_id], 100)
        self.assertNotIn("report_id", str(widget))
        self.assertNotIn("report_id", str(rendered))
        self.assertNotIn("source_label", str(rendered))
        self.assertEqual(self.client.get(f"/api/widgets/{widget['id']}").get_json()["widget"], widget)
        self.assertEqual(len(self.client.get("/api/widgets").get_json()["widgets"]), 1)
        updated = self.client.put(f"/api/widgets/{widget['id']}", json={**widget, "name": "Renamed"})
        self.assertEqual(updated.get_json()["widget"]["name"], "Renamed")
        self.assertEqual(self.client.delete(f"/api/widgets/{widget['id']}").status_code, 200)

    def test_scope_filter_priority_then_rank_and_group_context(self):
        north = self.group("North", ["Alex", "Blair", "Devon"])
        self.group("South", ["Casey"], north["type_id"])
        definition = self.definition(field_ids=[self.ids["__stats_rank"], self.ids["Name"], self.ids["Net"]], filters=[
            {"field_id": self.ids["Cancelled"], "operator": "greater_or_equal", "value": 20},
        ])
        payload = self.widgets.preview(definition, {"group_ids": [north["id"]], "ranking": [
            {"field_id": self.ids["Net"], "direction": "desc"},
            {"field_id": self.ids["Cancelled"], "direction": "desc"},
        ]})
        self.assertEqual([row[self.ids["Name"]] for row in payload["rows"]], ["Blair", "Alex"])
        self.assertEqual([row[self.ids["__stats_rank"]] for row in payload["rows"]], [1, 2])
        self.assertEqual(payload["rows"][0]["__group_ids"][north["type_id"]], north["id"])
        self.assertNotIn(self.ids["Cancelled"], payload["rows"][0])

    def test_assets_resolve_from_each_rows_group(self):
        north = self.group("North", ["Alex", "Blair"])
        south = self.group("South", ["Casey"], north["type_id"])
        asset = self.fields.save_group("report", {"label": "Logo", "group_type_id": north["type_id"], "property": "asset:logo_small"})
        asset_id = self.fields.ids_for_report("report", [asset["key"]])[0]
        class RowThemes:
            def effective_group_theme(self, group_id):
                return {"assets": {"logo_small": f"/{group_id}/logo.svg", "medallion": f"/{group_id}/medallion.svg"}}
        from stats_core.services.fields import FieldService
        from stats_core.services.widgets import WidgetService
        fields = FieldService(self.repos, self.reports, self.groups, RowThemes())
        fields.save_rank("report", {"group_type_id": north["type_id"]})
        widgets = WidgetService(self.repository, fields, self.repos.meta)
        payload = widgets.preview(self.definition(field_ids=[self.ids["Name"], self.ids["__stats_rank"], asset_id]), {"ranking": [{"field_id": self.ids["Net"], "direction": "desc"}]})
        self.assertEqual(payload["rows"][0][asset_id], f"/{south['id']}/logo.svg")
        self.assertEqual(payload["rows"][1][asset_id], f"/{north['id']}/logo.svg")
        self.assertEqual(payload["rows"][0]["__field_assets"][self.ids["__stats_rank"]], f"/{south['id']}/medallion.svg")

    def test_charts_aggregate_raw_numeric_values_and_keep_zero(self):
        pie = self.definition(kind="pie", field_ids=[self.ids["Net"], self.ids["Cancelled"]], chart={"dimension_field_id": "", "measure_field_ids": [self.ids["Net"], self.ids["Cancelled"]], "aggregation": "sum"})
        payload = self.widgets.preview(pie)
        self.assertEqual(payload["chart"]["categories"], ["Net", "Cancelled"])
        self.assertEqual(payload["chart"]["value_field_ids"], [self.ids["Net"], self.ids["Cancelled"]])
        self.assertTrue(all(field_id.startswith("field-") for field_id in payload["chart"]["value_field_ids"]))
        self.assertEqual(payload["chart"]["series"][0]["values"], [700, 60])
        rates = self.definition(kind="bar", field_ids=[self.ids["Name"], self.ids["Rate"]], chart={"dimension_field_id": self.ids["Name"], "measure_field_ids": [self.ids["Rate"]], "aggregation": "average"})
        self.assertEqual(self.widgets.preview(rates)["chart"]["series"][0]["values"], [0.25, 0.5, 0.1, 0])
        zero = {**pie, "filters": [{"field_id": self.ids["Cancelled"], "operator": "equals", "value": 0}]}
        self.assertEqual(self.widgets.preview(zero)["chart"]["series"][0]["values"], [500, 0])

    def test_measure_comparison_chart_retains_each_global_field_format(self):
        self.fields.update_report_field("report", "Net", {"label": "Net sales", "type": "number", "decimals": 0})
        self.fields.update_report_field("report", "Cancelled", {"label": "Cancelled sales", "type": "number", "decimals": 3})
        chart = self.definition(kind="bar", field_ids=[self.ids["Net"], self.ids["Cancelled"]], chart={
            "dimension_field_id": "", "measure_field_ids": [self.ids["Cancelled"], self.ids["Net"]], "aggregation": "average"})
        payload = self.widgets.preview(chart)
        self.assertEqual(payload["chart"]["categories"], ["Cancelled sales", "Net sales"])
        self.assertEqual(payload["chart"]["value_field_ids"], [self.ids["Cancelled"], self.ids["Net"]])
        metadata = {field["id"]: field for field in payload["fields"]}
        formats = [metadata[field_id] for field_id in payload["chart"]["value_field_ids"]]
        self.assertEqual([(field["type"], field["decimals"]) for field in formats], [("number", 3), ("number", 0)])
        self.assertNotIn("report_id", str(payload))

    def test_legacy_rate_pie_renders_percentage_without_rewriting_saved_definition(self):
        legacy = self.definition(id="legacy-pie", kind="pie", field_ids=[self.ids["Rate"]], chart={
            "dimension_field_id": "", "measure_field_ids": [self.ids["Rate"]], "aggregation": "average"})
        self.repository.save(legacy)
        chart = self.widgets.render("legacy-pie")["chart"]
        self.assertEqual(chart["pie_mode"], "percentage")
        self.assertEqual(chart["percentage_scale"], "fraction")
        self.assertAlmostEqual(chart["fraction"], (0.25 + 0.5 + 0.1) / 4)
        self.assertEqual(chart["series"][0]["sample_counts"], [4])
        self.assertEqual(chart["source_row_count"], 4)
        self.assertIn("each row counts equally", chart["aggregation_label"])
        self.assertEqual(self.repository.get("legacy-pie"), legacy)

    def test_pie_mode_persists_and_invalid_chart_meaning_blocks_save_and_preview(self):
        from stats_core.errors import ValidationError
        base = self.definition(kind="pie", field_ids=[self.ids["Rate"]], chart={
            "dimension_field_id": "", "measure_field_ids": [self.ids["Rate"]], "aggregation": "average", "pie_mode": "percentage"})
        saved = self.widgets.save(base)
        self.assertEqual(self.repository.get(saved["id"])["chart"]["pie_mode"], "percentage")
        self.assertEqual(self.widgets.render(saved["id"])["chart"]["pie_mode"], "percentage")
        invalid = [
            ({**base, "chart": {**base["chart"], "pie_mode": "composition"}}, "Composition pie"),
            ({**base, "chart": {**base["chart"], "pie_mode": "unknown"}}, "Choose Percentage"),
            ({**base, "chart": {**base["chart"], "aggregation": "sum"}}, "cannot be summed"),
            ({**base, "kind": "bar", "field_ids": [self.ids["Rate"], self.ids["Net"]], "chart": {
                "dimension_field_id": "", "measure_field_ids": [self.ids["Rate"], self.ids["Net"]], "aggregation": "average"}}, "cannot share one chart scale"),
        ]
        for definition, message in invalid:
            for action in (self.widgets.save, self.widgets.preview):
                with self.subTest(definition=definition, action=action.__name__), self.assertRaisesRegex(ValidationError, message):
                    action(definition)
        self.assertEqual(len(self.repository.list()), 1)

    def test_percent_filters_and_ranking_use_the_same_units_as_charts(self):
        self.repos.report_data.replace("report", [
            {"key": "Name", "label": "Name", "type": "text"},
            {"key": "Rate", "label": "Rate", "type": "percent"},
        ], [{"Name": "Points", "Rate": 14.3}, {"Name": "Fraction", "Rate": .2}, {"Name": "Suffix", "Rate": "25%"}], {})
        table = self.definition(field_ids=[self.ids["Name"], self.ids["Rate"]], filters=[
            {"field_id": self.ids["Rate"], "operator": "greater_than", "value": "14.3%"}])
        payload = self.widgets.preview(table, {"ranking": [{"field_id": self.ids["Rate"], "direction": "desc"}]})
        self.assertEqual([row[self.ids["Name"]] for row in payload["rows"]], ["Suffix", "Fraction"])

    def test_percent_filter_input_is_independent_from_explicit_source_scale(self):
        from stats_core.services.widgets import WidgetService
        rule = {"field_id": "rate", "operator": "equals", "value": ".5%"}
        for scale, raw in [("points", .5), ("fraction", .005), ("auto", "0.5%")]:
            with self.subTest(scale=scale):
                metadata = {"rate": {"type": "percent", "percent_input_scale": scale}}
                self.assertTrue(WidgetService._matches({"rate": raw}, rule, metadata))
        # An existing numeric .5 comparison keeps its legacy meaning of 50%.
        metadata = {"rate": {"type": "percent", "percent_input_scale": "points"}}
        self.assertTrue(WidgetService._matches({"rate": 50}, {**rule, "value": .5}, metadata))

    def test_ratio_definition_persists_field_dependencies_and_uses_scoped_filtered_pairs(self):
        north = self.group("North", ["Alex", "Blair", "Devon"])
        definition = self.definition(kind="pie", field_ids=[self.ids["Net"], self.ids["Cancelled"]], chart={
            "dimension_field_id": "", "measure_field_ids": [self.ids["Cancelled"]],
            "denominator_field_id": self.ids["Net"], "aggregation": "ratio", "pie_mode": "percentage"})
        before = self.repos.report_data.read("report")
        saved = self.widgets.save(definition)
        self.assertEqual(saved["chart"]["denominator_field_id"], self.ids["Net"])
        self.assertEqual(self.repository.field_dependents(self.ids["Net"]), ["Leaderboard"])
        chart = self.widgets.render(saved["id"], {"group_ids": [north["id"]]})["chart"]
        self.assertEqual(chart["categories"], ["Cancelled / Net"])
        self.assertEqual(chart["fraction"], .3)
        self.assertEqual(chart["series"][0]["numerators"], [60])
        self.assertEqual(chart["series"][0]["denominators"], [200])
        self.assertEqual(chart["series"][0]["sample_counts"], [3])
        self.assertEqual(chart["source_row_count"], 3)
        filtered = {**saved, "filters": [{"field_id": self.ids["Cancelled"], "operator": "greater_than", "value": 20}]}
        chart = self.widgets.preview(filtered)["chart"]
        self.assertEqual(chart["fraction"], .3)
        self.assertEqual(chart["series"][0]["sample_counts"], [1])
        self.assertEqual(self.repos.report_data.read("report"), before)

    def test_ratio_schema_rejects_unselected_or_non_numeric_denominators(self):
        from stats_core.errors import ValidationError
        base = self.definition(kind="bar", field_ids=[self.ids["Net"], self.ids["Cancelled"]], chart={
            "dimension_field_id": "", "measure_field_ids": [self.ids["Cancelled"]],
            "denominator_field_id": self.ids["Net"], "aggregation": "ratio"})
        cases = [
            ({**base, "field_ids": [self.ids["Cancelled"]]}, "selected numeric denominator"),
            ({**base, "chart": {**base["chart"], "denominator_field_id": ""}}, "selected numeric denominator"),
            ({**base, "field_ids": [self.ids["Rate"], self.ids["Net"]], "chart": {**base["chart"], "measure_field_ids": [self.ids["Rate"]]}}, "numeric numerator"),
        ]
        for definition, error in cases:
            for action in (self.widgets.save, self.widgets.preview):
                with self.subTest(definition=definition, action=action.__name__), self.assertRaisesRegex(ValidationError, error):
                    action(definition)
        self.assertEqual(self.repository.list(), [])

    def test_independent_calculations_persist_and_preview_without_global_field_changes(self):
        before = self.repos.report_data.read("report")
        definition = self.definition(kind="bar", field_ids=[self.ids["Net"], self.ids["Cancelled"]], chart={
            "dimension_field_id": "", "measure_field_ids": [self.ids["Net"], self.ids["Cancelled"]],
            "aggregation": "none", "measure_settings": {
                self.ids["Net"]: {"aggregation": "sum"},
                self.ids["Cancelled"]: {"aggregation": "average"},
            }})
        saved = self.client.post("/api/widgets", json=definition).get_json()["widget"]
        self.assertEqual(saved["chart"]["measure_settings"], definition["chart"]["measure_settings"])
        payload = self.widgets.render(saved["id"])
        self.assertEqual(payload["chart"]["series"][0]["values"], [700, 15])
        self.assertEqual(payload["chart"]["aggregation"], "mixed")
        self.assertEqual(self.repos.report_data.read("report"), before)
        self.assertTrue(all(field["kind"] == "report" for field in payload["fields"]))

    def test_percentage_rows_are_distinct_panels_and_duplicate_labels_remain_distinct(self):
        self.repos.report_data.replace("report", [
            {"key": "Name", "label": "Name", "type": "text"},
            {"key": "Rate", "label": "Rate", "type": "percent"},
        ], [{"Name": "Same label", "Rate": .143}, {"Name": "Same label", "Rate": .25}], {})
        definition = self.definition(kind="pie", field_ids=[self.ids["Name"], self.ids["Rate"]], chart={
            "dimension_field_id": self.ids["Name"], "measure_field_ids": [self.ids["Rate"]], "aggregation": "none"})
        chart = self.widgets.preview(definition)["chart"]
        self.assertEqual(chart["layout"], "separate")
        self.assertEqual([panel["chart"]["fraction"] for panel in chart["panels"]], [.143, .25])
        self.assertEqual([panel["label"] for panel in chart["panels"]], ["Same label", "Same label"])

    def test_visual_changes_preserve_dormant_calculation_and_pie_options(self):
        original = self.definition(kind="pie", field_ids=[self.ids["Net"], self.ids["Cancelled"]], chart={
            "measure_field_ids": [self.ids["Cancelled"]], "aggregation": "ratio", "ratio_mode": "row_average",
            "denominator_field_id": self.ids["Net"], "result_type": "percent", "pie_mode": "percentage"})
        saved = self.widgets.save(original)
        for kind in ("bar", "table", "pie"):
            changed = self.widgets.save({**saved, "kind": kind}, saved["id"])
            self.assertEqual(changed["chart"], saved["chart"])
        numeric = {**saved, "kind": "bar", "chart": {**saved["chart"], "result_type": "number", "ratio_mode": "totals"}}
        chart = self.widgets.preview(numeric)["chart"]
        self.assertEqual(chart["series"][0]["value_format"]["type"], "number")
        self.assertNotIn("percentage_scale", chart)

    def test_invalid_calculated_results_are_not_normalized_to_source_blank_zero(self):
        calculated = self.fields.save_calculated("report", {"label": "Ratio", "formula": "[Cancelled] / [Net]", "type": "number"})
        field_id = self.fields.field_id("report", calculated["key"])
        definition = self.definition(kind="bar", field_ids=[self.ids["Name"], field_id], chart={
            "dimension_field_id": self.ids["Name"], "measure_field_ids": [field_id], "aggregation": "none"})
        payload = self.widgets.preview(definition)
        self.assertEqual(payload["chart"]["series"][0]["values"], [.2, .3, 0, None])
        self.assertIn("unavailable", payload["chart"]["series"][0]["reasons"][-1])

    def test_preview_does_not_save_and_unsupported_periods_fail(self):
        response = self.client.post("/api/widgets/preview", json={"widget": self.definition()})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.repository.list(), [])
        from stats_core.errors import ValidationError
        with self.assertRaisesRegex(ValidationError, "Custom timeframes"):
            self.widgets.preview(self.definition(), {"timeframe": {"preset": "year_to_date"}})
        with self.assertRaisesRegex(ValidationError, "Choose a standard"):
            self.widgets.preview(self.definition(), {"timeframe": {}})

    def test_table_preview_matches_saved_result_and_preserves_chart_settings(self):
        definition = self.definition(kind="table", chart={"measure_field_ids": [self.ids["Net"]],
            "measure_settings": {self.ids["Net"]: {"aggregation": "sum"}}, "layout": "separate"},
            filters=[{"field_id": self.ids["Name"], "operator": "equals", "value": "Alex"}])
        payload = self.widgets.preview(definition)
        self.assertEqual(payload["kind"], "table")
        self.assertNotIn("chart", payload)
        self.assertNotIn("calculation_preview", payload)
        self.assertEqual(self.repository.list(), [])
        saved = self.widgets.save(definition)
        self.assertEqual(saved["chart"]["measure_settings"][self.ids["Net"]], {"aggregation": "sum"})
        rendered = self.widgets.render(saved["id"])
        self.assertNotIn("calculation_preview", rendered)
        self.assertEqual(rendered["rows"], payload["rows"])

    def test_preview_request_schema_and_scope_reject_before_period_pull(self):
        for value in (["invalid"], 10, "invalid"):
            response = self.client.post("/api/widgets/preview", json=value)
            self.assertEqual(response.status_code, 400)
            self.assertIn("JSON object", response.get_json()["error"])
        response = self.client.post("/api/widgets/preview", json={"widget": self.definition(), "source_id": "invalid"})
        self.assertEqual(response.status_code, 400)
        from stats_core.errors import ValidationError
        from stats_core.services.fields import FieldService
        from stats_core.services.widgets import WidgetService
        calls = []
        fields = FieldService(self.repos, self.reports, self.groups, self.theme,
                              period_rows=lambda report_id, timeframe: calls.append(report_id) or [])
        widgets = WidgetService(self.repository, fields, self.repos.meta)
        with self.assertRaisesRegex(ValidationError, "Group not found"):
            widgets.preview(self.definition(), {"group_ids": ["missing"], "timeframe": {"preset": "year_to_date"}})
        self.assertEqual(calls, [])

    def test_requested_period_is_delegated_to_data_without_mutating_default(self):
        from stats_core.services.fields import FieldService
        from stats_core.services.widgets import WidgetService
        calls = []
        def period_rows(report_id, timeframe):
            calls.append((report_id, timeframe))
            return [{"Name": "Earlier member", "Net": 900}]
        fields = FieldService(self.repos, self.reports, self.groups, self.theme, period_rows=period_rows)
        widgets = WidgetService(self.repository, fields, self.repos.meta)
        payload = widgets.preview(self.definition(), {"timeframe": {"preset": "year_to_date"}})
        self.assertEqual(payload["rows"][0][self.ids["Net"]], 900)
        self.assertEqual(calls, [("report", {"preset": "year_to_date"})])
        self.assertEqual(self.reports.rows("report")[0]["Net"], 100)

    def test_invalid_bindings_and_unowned_settings_are_explicit_errors(self):
        from stats_core.errors import ValidationError
        for extra in ({"report_id": "report"}, {"source_id": "source"}, {"theme": {}}, {"layout": {}}, {"group_ids": []}):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValidationError, "does not own"):
                self.widgets.save(self.definition(**extra))
        with self.assertRaisesRegex(ValidationError, "do not share a dataset"):
            self.widgets.preview(self.definition(field_ids=[self.ids["Name"], *self.fields.ids_for_report("other", ["Net"])]))
        with self.assertRaisesRegex(ValidationError, "unavailable"):
            self.widgets.preview(self.definition(field_ids=["field-missing"]))
        with self.assertRaisesRegex(ValidationError, "Generated table"):
            self.widgets.preview(self.definition(filters=[{"field_id": self.ids["__stats_rank"], "operator": "equals", "value": 1}]))
        with self.assertRaisesRegex(ValidationError, "numeric value"):
            self.widgets.preview(self.definition(filters=[{"field_id": self.ids["Net"], "operator": "equals", "value": "not a number"}]))

    def test_dependency_deletions_block_until_consumer_is_removed(self):
        from stats_core.errors import ValidationError
        calculated = self.fields.save_calculated("report", {"label": "Difference", "formula": "[Net] - [Cancelled]"})
        field_id = self.fields.ids_for_report("report", [calculated["key"]])[0]
        widget = self.widgets.save(self.definition(field_ids=[field_id]))
        with self.assertRaisesRegex(ValidationError, "Leaderboard"):
            self.fields.delete("report", calculated["key"])
        self.widget_dependents = ["Office Screen"]
        with self.assertRaisesRegex(ValidationError, "Office Screen"):
            self.widgets.delete(widget["id"])
        self.widget_dependents = []
        self.widgets.delete(widget["id"])
        self.fields.delete("report", calculated["key"])

    def test_widget_architecture_has_only_fields_and_own_persistence(self):
        path = ROOT / "app/stats_core/services/widgets.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(any(name.startswith(("stats_core.repositories", "stats_core.storage", "stats_core.theme", "sources")) for name in imports))
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue({"evaluate", "resolve", "rank"}.issubset(attrs))
        self.assertTrue({"reports", "adapters", "connect", "execute", "themes", "screens"}.isdisjoint(attrs))


if __name__ == "__main__":
    unittest.main()
