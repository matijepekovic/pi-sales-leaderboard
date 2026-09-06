#!/usr/bin/env python3
"""End-to-end Screen composition against real application domain wiring."""
from __future__ import annotations

import copy
import io
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


class ScreenWidgetContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["STATS_DATA_DIR"] = self.temp.name
        from stats_core.bootstrap import create_app
        self.app = create_app("windows", start_background=False)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.runtime = self.app.extensions["stats_runtime"]
        source = self.post("/api/data/sources", {"name": "Fixture source", "adapter": "tableau", "connection": {
            "server": "https://example.invalid", "site": "fixture", "pat_name": "fixture"}}, "source")
        report = self.post("/api/data/reports", {"name": "Fixture report", "source_id": source["id"],
            "source_config": {"workbook": "Book", "sheet": "Sheet"}}, "report")
        self.report_id = report["id"]
        self.source_fields = [
            {"key": key, "label": key, "type": "text" if key == "Name" else "percent" if key == "Rate" else "number"}
            for key in ("Name", "Net", "Cancelled", "Rate", "Sold")]
        self.source_rows = [
            {"Name": "Alex", "Net": 1000, "Cancelled": 10, "Rate": 0.30, "Sold": 5},
            {"Name": "Blair", "Net": 600, "Cancelled": 20, "Rate": 0.50, "Sold": 4},
            {"Name": "Casey", "Net": 600, "Cancelled": 15, "Rate": 0.50, "Sold": 3},
            {"Name": "Devon", "Net": 100, "Cancelled": 15, "Rate": 0.50, "Sold": 7},
        ]
        self.runtime.repos.report_data.replace(self.report_id, self.source_fields, self.source_rows, {"status": "4 rows"})
        self.ids = dict(zip(["Name", "Net", "Cancelled", "Rate", "Sold", "__stats_rank"],
                            self.runtime.fields.ids_for_report(self.report_id, ["Name", "Net", "Cancelled", "Rate", "Sold", "__stats_rank"])))
        definition = self.post("/api/group-types", {"name": "Teams", "report_id": self.report_id, "member_key_field": "Name", "member_label_field": "Name"}, "group_type")
        self.type_id = definition["id"]
        self.north = self.post("/api/groups", {"name": "North", "type_id": self.type_id, "member_keys": ["Alex"],
            "roles": [{"name": "Manager", "member_key": "Alex"}]}, "group")
        self.south = self.post("/api/groups", {"name": "South", "type_id": self.type_id, "member_keys": ["Blair", "Casey", "Devon"],
            "roles": [{"name": "Captain", "member_key": "Blair"}, {"name": "Deputy", "member_key": "Casey"}]}, "group")
        self.table = self.widget("Leaderboard", "table", ["Name", "Net", "Cancelled", "Rate", "__stats_rank"])

    def post(self, url, data, key=None):
        response = self.client.post(url, json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()[key] if key else response.get_json()

    def put(self, url, data):
        response = self.client.put(url, json=data)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def widget(self, name, kind, keys):
        data = {"name": name, "kind": kind, "field_ids": [self.ids[key] for key in keys]}
        if kind != "table":
            data["chart"] = {"dimension_field_id": "", "measure_field_ids": [self.ids[key] for key in keys], "aggregation": "sum"}
        return self.post("/api/widgets", data, "widget")

    def screen(self, **overrides):
        return {"name": "Office Screen", "widgets": [{"id": "leaderboard", "widget_id": self.table["id"],
                "ranking": [{"field_id": self.ids["Net"], "direction": "desc"}]}],
                "theme_mode": "inherited", "theme_group_type_id": self.type_id, **overrides}

    def preview(self, definition):
        return self.post("/api/screens/preview", definition, "payload")

    @staticmethod
    def png(red, green, blue):
        def chunk(name, value):
            return struct.pack(">I", len(value)) + name + value + struct.pack(">I", zlib.crc32(name + value) & 0xffffffff)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes([0, red, green, blue]))) + chunk(b"IEND", b"")

    def upload(self, slot, color):
        response = self.client.post(f"/api/asset-library/{slot}", data={"asset": (io.BytesIO(self.png(*color)), f"{slot}.png")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["id"]

    def test_combined_and_separate_group_charts_share_one_definition(self):
        chart = self.widget("Net versus cancelled", "pie", ["Net", "Cancelled"])
        instance = {"id": "chart", "widget_id": chart["id"], "group_ids": [self.north["id"], self.south["id"]],
                    "group_mode": "combine", "layout": {"x": 10, "y": 20, "width": 80, "height": 60}}
        combined = self.preview(self.screen(widgets=[instance]))
        self.assertEqual(len(combined["sections"]), 1)
        self.assertEqual(combined["sections"][0]["chart"]["series"][0]["values"], [2300, 60])
        separate = self.preview(self.screen(widgets=[{**instance, "group_mode": "separate"}]))
        self.assertEqual(len(separate["sections"]), 2)
        self.assertEqual([item["chart"]["series"][0]["values"] for item in separate["sections"]], [[1000, 10], [1300, 50]])
        self.assertEqual([item["layout"]["x"] for item in separate["sections"]], [10, 50])
        self.assertEqual([item["layout"]["width"] for item in separate["sections"]], [40, 40])
        self.assertTrue(all(item["widget_id"] == chart["id"] for item in separate["sections"]))

    def test_winning_identity_uses_leading_member_not_group_total(self):
        payload = self.preview(self.screen())
        self.assertEqual(payload["sections"][0]["rows"][0][self.ids["Name"]], "Alex")
        self.assertEqual(payload["inherited_theme_group_id"], self.north["id"])
        # South has the higher aggregate, but Alex is the highest individual.
        self.assertGreater(sum(row["Net"] for row in self.source_rows if row["Name"] != "Alex"), self.source_rows[0]["Net"])

    def test_three_ranking_priorities_and_designated_winner_widget(self):
        ranking = [{"field_id": self.ids["Rate"], "direction": "desc"},
                   {"field_id": self.ids["Net"], "direction": "desc"},
                   {"field_id": self.ids["Cancelled"], "direction": "asc"}]
        first = {"id": "net", "widget_id": self.table["id"], "ranking": [{"field_id": self.ids["Net"], "direction": "desc"}]}
        second = {"id": "rate", "widget_id": self.table["id"], "ranking": ranking}
        payload = self.preview(self.screen(widgets=[first, second], winner_widget_id="rate"))
        self.assertEqual([row[self.ids["Name"]] for row in payload["sections"][1]["rows"]], ["Casey", "Blair", "Devon", "Alex"])
        self.assertEqual([row[self.ids["__stats_rank"]] for row in payload["sections"][1]["rows"]], [1, 2, 3, 4])
        self.assertEqual(payload["inherited_theme_group_id"], self.south["id"])

    def test_row_assets_follow_rows_while_screen_assets_follow_winner(self):
        north_logo, south_logo = self.upload("logo_small", (255, 0, 0)), self.upload("logo_small", (0, 0, 255))
        north_hero, south_hero = self.upload("hero", (255, 120, 0)), self.upload("hero", (0, 120, 255))
        for group, logo, hero in ((self.north, north_logo, north_hero), (self.south, south_logo, south_hero)):
            self.put(f"/api/groups/{group['id']}/appearance", {"asset_bindings": {"logo_small": logo, "hero": hero}})
        asset = self.post(f"/api/fields/{self.report_id}", {"kind": "group", "label": "Team logo", "group_type_id": self.type_id, "property": "asset:logo_small"}, "field")
        asset_id = self.runtime.fields.ids_for_report(self.report_id, [asset["key"]])[0]
        self.put(f"/api/widgets/{self.table['id']}", {**self.table, "field_ids": [*self.table["field_ids"], asset_id]})
        payload = self.preview(self.screen())
        self.assertTrue(payload["sections"][0]["rows"][0][asset_id].endswith(north_logo[5:]))
        self.assertTrue(payload["sections"][0]["rows"][1][asset_id].endswith(south_logo[5:]))
        self.assertTrue(payload["theme"]["assets"]["hero"].endswith(north_hero[5:]))

    def test_manual_fit_survives_group_branding_without_rewriting_presets(self):
        self.put(f"/api/groups/{self.north['id']}/appearance", {"style": {"colors": {"primary": "#ff0000"}},
            "widget_styles": {self.table["id"]: {"font_size": 30, "padding": 12}}})
        before = self.runtime.groups.appearance(self.north["id"])
        instance = {"id": "table", "widget_id": self.table["id"], "layout": {"x": 5, "y": 12, "width": 90, "height": 80},
                    "fit": {"rows": 7, "font_size": 42, "padding": 0}}
        saved = self.post("/api/screens", self.screen(widgets=[instance], theme_mode="group", theme_group_id=self.north["id"]), "screen")
        payload = self.client.get(f"/api/screens/{saved['id']}/preview").get_json()["payload"]
        self.assertEqual(payload["sections"][0]["fit"], {"rows": 7, "font_size": 42, "padding": 0})
        self.assertEqual(payload["theme"]["colors"]["primary"], "#ff0000")
        self.assertEqual(payload["sections"][0]["layout"], instance["layout"])
        self.assertEqual(self.runtime.groups.appearance(self.north["id"]), before)
        invalid = self.screen(widgets=[{**instance, "fit": {"rows": 7, "colors": {"primary": "#00ff00"}}}])
        self.assertEqual(self.client.post("/api/screens", json=invalid).status_code, 400)

    def test_instance_period_beats_screen_period_and_save_never_pulls(self):
        outer = self
        class Adapter:
            def __init__(self): self.calls = []
            def report_value(self, report): return "fixture"
            def with_secret(self, settings, secret): return settings
            def table(self, settings, source, report):
                self.calls.append(copy.deepcopy(report))
                start, end = report["runtime"]["date_start"], report["runtime"]["date_end"]
                return {"fields": outer.source_fields, "rows": [{**outer.source_rows[0], "Net": 200 if start == "2026-01-01" else 300}], "start": start, "end": end}
        adapter = Adapter()
        self.runtime.reports.adapters["tableau"] = adapter
        screen_period = {"preset": "custom", "start_date": "2026-01-01", "end_date": "2026-06-30"}
        instance_period = {"preset": "custom", "start_date": "2026-07-01", "end_date": "2026-07-31"}
        default = copy.deepcopy(self.runtime.repos.report_data.read(self.report_id))
        report = copy.deepcopy(self.runtime.reports.get(self.report_id))
        saved = self.post("/api/screens", self.screen(timeframe=screen_period, widgets=[
            {"id": "whole", "widget_id": self.table["id"]},
            {"id": "specific", "widget_id": self.table["id"], "timeframe": instance_period}]), "screen")
        self.assertEqual(adapter.calls, [])
        rendered = self.client.get(f"/api/screens/{saved['id']}/preview")
        self.assertEqual(rendered.status_code, 200, rendered.get_json())
        payload = rendered.get_json()["payload"]
        self.assertEqual([section["rows"][0][self.ids["Net"]] for section in payload["sections"]], [200, 300])
        self.assertEqual(len(adapter.calls), 2)
        unchanged = self.preview(self.screen())
        self.assertEqual(unchanged["sections"][0]["rows"][0][self.ids["Net"]], 1000)
        self.assertEqual(len(adapter.calls), 2)
        self.assertEqual(self.runtime.reports.get(self.report_id), report)
        self.assertEqual(self.runtime.repos.report_data.read(self.report_id), default)

    def test_field_versions_are_named_instance_local_and_save_never_pulls(self):
        outer = self
        class Adapter:
            def __init__(self): self.calls = []
            def report_value(self, report): return "fixture"
            def with_secret(self, settings, secret): return settings
            def table(self, settings, source, report):
                self.calls.append(copy.deepcopy(report))
                start, end = report["runtime"]["date_start"], report["runtime"]["date_end"]
                # Reverse source order to prove matching is not positional.
                return {"fields": outer.source_fields,
                        "rows": [{**row, "Net": row["Net"] * 10} for row in reversed(outer.source_rows)],
                        "start": start, "end": end}
        adapter = Adapter()
        self.runtime.reports.adapters["tableau"] = adapter
        variant = {"id": "placement-year-net", "field_id": self.ids["Net"], "label": "Last year Net",
                   "timeframe": {"preset": "custom", "start_date": "2024-01-01", "end_date": "2024-12-31"}}
        before_widget = copy.deepcopy(self.runtime.widgets.get(self.table["id"]))
        before_fields = copy.deepcopy(self.runtime.fields.fields(self.report_id))
        before_snapshot = copy.deepcopy(self.runtime.repos.report_data.read(self.report_id))
        saved = self.post("/api/screens", self.screen(widgets=[
            {"id": "comparison", "widget_id": self.table["id"], "field_variants": [variant], "identity_field_id": self.ids["Name"]},
            {"id": "untouched", "widget_id": self.table["id"]}]), "screen")
        self.assertEqual(adapter.calls, [])
        self.assertEqual(saved["widgets"][0]["field_variants"], [variant])
        response = self.client.get(f"/api/screens/{saved['id']}/preview")
        self.assertEqual(response.status_code, 200, response.get_json())
        comparison, untouched = response.get_json()["payload"]["sections"]
        self.assertEqual([(row[self.ids["Name"]], row[self.ids["Net"]], row[variant["id"]]) for row in comparison["rows"]],
                         [("Alex", 1000, 10000), ("Blair", 600, 6000), ("Casey", 600, 6000), ("Devon", 100, 1000)])
        self.assertEqual(comparison["fields"][-1]["label"], "Last year Net")
        self.assertTrue(comparison["fields"][-1]["instance_only"])
        self.assertNotIn(variant["id"], untouched["rows"][0])
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(self.runtime.widgets.get(self.table["id"]), before_widget)
        self.assertEqual(self.runtime.fields.fields(self.report_id), before_fields)
        self.assertEqual(self.runtime.repos.report_data.read(self.report_id), before_snapshot)
        self.assertIn(saved["name"], self.runtime.screens.field_references(self.ids["Name"]))

    def test_invalid_field_placement_and_widget_changes_do_not_pull(self):
        class Adapter:
            def __init__(self): self.calls = []
            def report_value(self, report): return "fixture"
            def with_secret(self, settings, secret): return settings
            def table(self, *args):
                self.calls.append(args)
                raise AssertionError("Validation must not contact Data")
        adapter = Adapter()
        self.runtime.reports.adapters["tableau"] = adapter
        variant = {"id": "placement-year-net", "field_id": self.ids["Net"], "label": "Last year Net",
                   "timeframe": {"preset": "previous_year"}}
        for invalid in ({**variant, "label": "Net"}, {**variant, "label": ""},
                        {**variant, "id": self.ids["Net"]}, {**variant, "timeframe": {"preset": "invented"}}):
            response = self.client.post("/api/screens", json=self.screen(widgets=[{
                "widget_id": self.table["id"], "field_variants": [invalid], "identity_field_id": self.ids["Name"]}]))
            self.assertEqual(response.status_code, 400, response.get_json())
        saved = self.post("/api/screens", self.screen(widgets=[{
            "widget_id": self.table["id"], "field_variants": [variant], "identity_field_id": self.ids["Name"]}]), "screen")
        response = self.client.put(f"/api/widgets/{self.table['id']}", json={**self.table, "field_ids": [self.ids["Name"]]})
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(self.runtime.screens.get(saved["id"]), saved)
        self.assertEqual(adapter.calls, [])

    def test_custom_ratio_uses_both_inputs_from_its_own_period(self):
        outer = self
        class Adapter:
            def __init__(self): self.calls = []
            def report_value(self, report): return "fixture"
            def with_secret(self, settings, secret): return settings
            def table(self, settings, source, report):
                self.calls.append(copy.deepcopy(report))
                return {"fields": outer.source_fields,
                        "rows": [{**row, "Net": row["Net"] * 10, "Sold": row["Sold"] * 2} for row in reversed(outer.source_rows)],
                        "start": report["runtime"]["date_start"], "end": report["runtime"]["date_end"]}
        adapter = Adapter()
        self.runtime.reports.adapters["tableau"] = adapter
        chart = self.post("/api/widgets", {"name": "Average deal", "kind": "bar", "field_ids": [self.ids[key] for key in ("Name", "Net", "Sold")],
            "chart": {"measure_field_ids": [self.ids["Net"]], "dimension_field_id": self.ids["Name"],
                      "aggregation": "ratio", "denominator_field_id": self.ids["Sold"], "result_type": "number"}}, "widget")
        variant = {"id": "placement-average-deal", "field_id": self.ids["Net"], "label": "Last year average deal", "timeframe": {"preset": "previous_year"}}
        saved = self.post("/api/screens", self.screen(widgets=[{"widget_id": chart["id"], "field_variants": [variant], "identity_field_id": self.ids["Name"]}]), "screen")
        self.assertEqual(adapter.calls, [])
        response = self.client.get(f"/api/screens/{saved['id']}/preview")
        self.assertEqual(response.status_code, 200, response.get_json())
        section = response.get_json()["payload"]["sections"][0]
        base, custom = section["chart"]["series"]
        self.assertEqual(base["values"][0], 200)
        self.assertEqual(custom["values"][0], 1000)
        self.assertEqual(custom["denominators"][0], 10)
        self.assertEqual(section["rows"][0][self.ids["Sold"]], 5)
        self.assertEqual(section["rows"][0]["placement-average-deal:denominator"], 10)
        self.assertEqual(section["calculation_fields"][0]["source_field_id"], self.ids["Sold"])
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(self.runtime.widgets.get(chart["id"]), chart)

    def test_timeline_has_real_periods_stable_individuals_zero_cells_and_gaps(self):
        outer = self
        class Adapter:
            def __init__(self): self.calls = []
            def report_value(self, report): return "fixture"
            def with_secret(self, settings, secret): return settings
            def table(self, settings, source, report):
                self.calls.append(copy.deepcopy(report))
                month = report["runtime"]["date_start"][5:7]
                values = {"01": [("Alex", 10), ("Blair", 20)], "02": [("Blair", None)], "03": [("Blair", 40), ("Alex", 30)]}[month]
                rows = [{**outer.source_rows[0], "Name": name, "Net": value} for name, value in values]
                return {"fields": outer.source_fields, "rows": rows, "start": report["runtime"]["date_start"], "end": report["runtime"]["date_end"]}
        adapter = Adapter()
        self.runtime.reports.adapters["tableau"] = adapter
        chart = self.post("/api/widgets", {"name": "Net history", "kind": "line", "field_ids": [self.ids["Name"], self.ids["Net"]],
            "chart": {"measure_field_ids": [self.ids["Net"]], "dimension_field_id": self.ids["Name"], "aggregation": "none"}}, "widget")
        variant = {"id": "placement-net-history", "field_id": self.ids["Net"], "label": "Net by month", "aggregation": "none",
                   "timeframe": {"preset": "custom", "start_date": "2024-01-01", "end_date": "2024-03-31"}, "interval": {"unit": "month", "count": 1}}
        saved = self.post("/api/screens", self.screen(widgets=[{"widget_id": chart["id"], "field_variants": [variant], "identity_field_id": self.ids["Name"]}]), "screen")
        self.assertEqual(adapter.calls, [])
        response = self.client.get(f"/api/screens/{saved['id']}/preview")
        self.assertEqual(response.status_code, 200, response.get_json())
        section = response.get_json()["payload"]["sections"][0]
        timeline = section["chart"]["panels"][1]["chart"]
        alex, blair = timeline["series"]
        self.assertEqual(alex["values"], [10, None, 30])
        self.assertEqual(blair["values"], [20, 0, 40])
        self.assertEqual(alex["row_indices"], [[0], [], [1]])
        self.assertEqual(blair["row_indices"], [[1], [0], [0]])
        self.assertEqual(timeline["periods"][1], {"start_date": "2024-02-01", "end_date": "2024-02-29"})
        self.assertTrue(timeline["timeline"])
        self.assertEqual(timeline["point_details"][1]["rows"][0][self.ids["Net"]], 0)
        self.assertNotIn(variant["id"], [field["id"] for field in section["fields"]])
        self.assertNotIn(variant["id"], section["rows"][0])
        self.assertEqual(len(adapter.calls), 3)
        for aggregation, expected in (("sum", [30, 0, 70]), ("average", [15, 0, 35])):
            saved["widgets"][0]["field_variants"][0]["aggregation"] = aggregation
            saved["widgets"][0]["identity_field_id"] = ""
            preview = self.preview(saved)
            self.assertEqual(preview["sections"][0]["chart"]["panels"][1]["chart"]["series"][0]["values"], expected)
            self.assertEqual(preview["sections"][0]["chart"]["panels"][1]["chart"]["series"][0]["row_indices"], [[0, 1], [0], [0, 1]])
        self.assertEqual(len(adapter.calls), 3, "The Data cache reuses exact period requests")
        self.assertEqual(self.runtime.repos.report_data.read(self.report_id)["rows"], self.source_rows)

    def test_dependencies_block_field_widget_group_theme_and_report_deletion(self):
        calculated = self.post(f"/api/fields/{self.report_id}", {"kind": "calculated", "label": "Average net", "formula": "[Net] / [Sold]"}, "field")
        calculated_id = self.runtime.fields.ids_for_report(self.report_id, [calculated["key"]])[0]
        widget = self.post("/api/widgets", {"name": "Average Widget", "kind": "table", "field_ids": [calculated_id]}, "widget")
        custom = self.post("/api/themes", {"name": "North custom", "base": "starter"}, "definition")
        self.put(f"/api/groups/{self.north['id']}/appearance", {"theme_id": custom["id"]})
        saved = self.post("/api/screens", self.screen(widgets=[{"widget_id": widget["id"], "group_ids": [self.north["id"]]}],
                          theme_mode="group", theme_group_id=self.north["id"]), "screen")
        for path in (f"/api/fields/{self.report_id}/{calculated['key']}", f"/api/widgets/{widget['id']}",
                     f"/api/groups/{self.north['id']}", f"/api/themes/{custom['id']}", f"/api/data/reports/{self.report_id}"):
            with self.subTest(path=path):
                response = self.client.delete(path)
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertIn("used", response.get_json()["error"].lower())
        self.assertEqual(self.client.delete(f"/api/screens/{saved['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/widgets/{widget['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/fields/{self.report_id}/{calculated['key']}").status_code, 200)

    def test_invalid_geometry_and_source_selection_are_rejected(self):
        for extra in ({"reports": [self.report_id]}, {"source_id": "source"}, {"report_id": self.report_id}):
            with self.subTest(extra=extra):
                self.assertEqual(self.client.post("/api/screens", json=self.screen(**extra)).status_code, 400)
        for invalid in ({"x": 50, "y": 0, "width": 60, "height": 80}, {"x": 0, "y": 0, "width": -1, "height": 80},
                        {"x": 0, "y": 0, "width": 100, "height": float("nan")}):
            with self.subTest(layout=invalid):
                self.assertEqual(self.client.post("/api/screens", json=self.screen(widgets=[{"widget_id": self.table["id"], "layout": invalid}])).status_code, 400)
        self.assertEqual(self.client.post("/api/screens", json=self.screen(widgets=[{"widget_id": self.table["id"], "fit": {"rows": 0}}])).status_code, 400)

    def test_widget_change_preserves_screen_dependencies_and_hidden_ranking(self):
        original_report = self.runtime.reports.get(self.report_id)
        other = self.post("/api/data/reports", {"name": "Other dataset", "source_id": original_report["source_id"],
            "source_config": {"workbook": "Other", "sheet": "Other"}}, "report")
        self.runtime.repos.report_data.replace(other["id"], self.source_fields, self.source_rows, {})
        other_ids = self.runtime.fields.ids_for_report(other["id"], ["Name", "Net"])
        saved = self.post("/api/screens", self.screen(widgets=[{"id": "ranked", "widget_id": self.table["id"],
            "group_ids": [self.north["id"], self.south["id"]],
            "ranking": [{"field_id": self.ids["Net"], "direction": "desc"}]}]), "screen")
        hidden = self.put(f"/api/widgets/{self.table['id']}", {**self.table, "field_ids": [self.ids["Name"]]})["widget"]
        preview = self.client.get(f"/api/screens/{saved['id']}/preview")
        self.assertEqual(preview.status_code, 200, preview.get_json())
        section = preview.get_json()["payload"]["sections"][0]
        self.assertEqual([field["id"] for field in section["fields"]], [self.ids["Name"]])
        self.assertEqual(section["rows"][0][self.ids["Name"]], "Alex")
        self.assertNotIn(self.ids["Net"], section["rows"][0])

        class NoPullAdapter:
            def __init__(self): self.calls = 0
            def report_value(self, report): return "fixture"
            def with_secret(self, settings, secret): return settings
            def table(self, *args):
                self.calls += 1
                raise AssertionError("Definition validation must not fetch data")
        adapter = NoPullAdapter()
        self.runtime.reports.adapters["tableau"] = adapter
        saved = self.put(f"/api/screens/{saved['id']}", {**saved, "timeframe": {
            "preset": "custom", "start_date": "2026-01-01", "end_date": "2026-07-31"}})["screen"]
        previous_snapshot = copy.deepcopy(self.runtime.repos.report_data.read(self.report_id))
        rejected = self.client.put(f"/api/widgets/{self.table['id']}", json={**hidden, "field_ids": other_ids})
        self.assertEqual(rejected.status_code, 400, rejected.get_json())
        self.assertEqual(self.runtime.widgets.get(self.table["id"]), hidden)
        self.assertEqual(self.runtime.screens.get(saved["id"]), saved)
        self.assertEqual(self.runtime.repos.report_data.read(self.report_id), previous_snapshot)
        self.assertEqual(adapter.calls, 0)


if __name__ == "__main__":
    unittest.main()
