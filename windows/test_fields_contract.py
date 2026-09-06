#!/usr/bin/env python3
"""Central Fields domain, API, and Screen-consumer contract tests."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))


class FieldContractTests(unittest.TestCase):
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
            "name": "Field Contract Source",
            "adapter": "tableau",
            "connection": {
                "server": "https://example.invalid",
                "site": "test",
                "pat_name": "token",
            },
        }).get_json()["source"]
        report_response = cls.client.post("/api/data/reports", json={
            "source_id": source["id"],
            "name": "Field Contract Report",
            "source_config": {"workbook": "Workbook", "sheet": "View"},
        })
        cls.report_id = report_response.get_json()["report"]["id"]
        cls.runtime.repos.report_data.replace(
            cls.report_id,
            [
                {"key": "Rep", "label": "Rep Name", "type": "text"},
                {"key": "Revenue", "label": "Revenue", "type": "currency"},
                {"key": "Sold", "label": "Sold Leads", "type": "number"},
            ],
            [
                {"Rep": "Alex", "Revenue": 120, "Sold": 2},
                {"Rep": "Blair", "Revenue": 200, "Sold": 2},
            ],
            {"status": "2 rows"},
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_report_fields_are_global_and_currency_is_not_a_display_type(self):
        fields = self.client.get(f"/api/fields/{self.report_id}").get_json()["fields"]
        revenue = next(field for field in fields if field["key"] == "Revenue")
        self.assertEqual(revenue["type"], "number")
        self.assertEqual(revenue["source_type"], "number")
        self.assertEqual(revenue["source_data_type"], "currency")

        changed = self.client.put(f"/api/fields/{self.report_id}/Revenue", json={
            "kind": "report",
            "label": "Close Rate",
            "type": "percent",
            "decimals": 1,
        })
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.get_json()["field"]["decimals"], 1)
        report = self.runtime.reports.get(self.report_id)
        self.assertIn("field_overrides", report)
        self.assertNotIn("display_values", report)

        rejected = self.client.put(f"/api/fields/{self.report_id}/Revenue", json={
            "kind": "report",
            "label": "Revenue",
            "type": "currency",
            "decimals": 2,
        })
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("Text, Number, or Percentage", rejected.get_json()["error"])

    def test_calculated_group_and_rank_fields_materialize_in_screen_order(self):
        calculated = self.client.post(f"/api/fields/{self.report_id}", json={
            "kind": "calculated",
            "label": "Average Sale",
            "type": "number",
            "decimals": 0,
            "formula": "[Revenue] / [Sold Leads]",
        })
        self.assertEqual(calculated.status_code, 200)
        calculated_key = calculated.get_json()["field"]["key"]

        group_type = self.client.post("/api/group-types", json={
            "name": "Teams",
            "report_id": self.report_id,
            "member_key_field": "Rep",
            "member_label_field": "Rep",
        })
        self.assertEqual(group_type.status_code, 200)
        type_id = group_type.get_json()["group_type"]["id"]
        group = self.client.post("/api/groups", json={
            "type_id": type_id,
            "name": "North Team",
            "member_keys": ["Blair"],
            "leader_title": "Manager",
            "leader_member_key": "Blair",
        })
        self.assertEqual(group.status_code, 200)

        group_field = self.client.post(f"/api/fields/{self.report_id}", json={
            "kind": "group",
            "label": "Team",
            "group_type_id": type_id,
            "property": "group_name",
        })
        self.assertEqual(group_field.status_code, 200)
        group_key = group_field.get_json()["field"]["key"]

        rank = self.client.put(
            f"/api/fields/{self.report_id}/__stats_rank",
            json={
                "kind": "table",
                "label": "Place",
                "group_type_id": type_id,
                "first_place_asset": "medallion",
            },
        )
        self.assertEqual(rank.status_code, 200)

        columns = ["__stats_rank", "Rep", calculated_key, group_key]
        ids = dict(zip(columns, self.runtime.fields.ids_for_report(self.report_id, columns)))
        widget_response = self.client.post("/api/widgets", json={
            "name": "Field Contract Widget", "kind": "table", "field_ids": list(ids.values()),
        })
        self.assertEqual(widget_response.status_code, 200, widget_response.get_json())
        widget = widget_response.get_json()["widget"]
        preview = self.client.post("/api/screens/preview", json={
            "name": "Field Contract Screen",
            "widgets": [{
                "widget_id": widget["id"],
                "ranking": [{"field_id": ids[calculated_key], "direction": "desc"}],
            }],
            "theme_mode": "inherited",
            "theme_group_type_id": type_id,
        })
        self.assertEqual(preview.status_code, 200)
        section = preview.get_json()["payload"]["sections"][0]
        self.assertEqual([field["kind"] for field in section["fields"]], [
            "table", "report", "calculated", "group",
        ])
        self.assertEqual(section["rows"][0][ids["Rep"]], "Blair")
        self.assertEqual(section["rows"][0][ids[calculated_key]], 100)
        self.assertEqual(section["rows"][0][ids[group_key]], "North Team")
        self.assertEqual(section["rows"][0][ids["__stats_rank"]], 1)
        self.assertIn("/static/theme-packs/starter/medallion.svg", section["rows"][0]["__field_assets"][ids["__stats_rank"]])
        self.assertEqual(section["rows"][1][ids["__stats_rank"]], 2)

    def test_calculated_fields_divide_and_reject_remainder_formulas(self):
        calculated = self.client.post(f"/api/fields/{self.report_id}", json={
            "kind": "calculated",
            "label": "Average Revenue",
            "type": "number",
            "decimals": 2,
            "formula": "[Revenue] ÷ [Sold Leads]",
        })
        self.assertEqual(calculated.status_code, 200)
        field_key = calculated.get_json()["field"]["key"]
        catalog = self.client.get(f"/api/fields/{self.report_id}").get_json()
        self.assertEqual([row[field_key] for row in catalog["sample_rows"]], [60.0, 100.0])

        remainder = self.client.post(f"/api/fields/{self.report_id}", json={
            "kind": "calculated",
            "label": "Wrong Average",
            "type": "number",
            "formula": "[Revenue] % [Sold Leads]",
        })
        self.assertEqual(remainder.status_code, 400)
        self.assertIn("Use Report fields", remainder.get_json()["error"])

        ui = (APP / "static" / "settings" / "fields.js").read_text(encoding="utf-8")
        self.assertIn('data-formula-token', ui)
        self.assertIn('[" ÷ ","÷"]', ui)

    def test_fields_has_one_http_owner_and_screens_use_the_service(self):
        data_web = (APP / "stats_core" / "web" / "data.py").read_text(encoding="utf-8")
        fields_web = (APP / "stats_core" / "web" / "fields.py").read_text(encoding="utf-8")
        screens = (APP / "stats_core" / "services" / "screens.py").read_text(encoding="utf-8")
        self.assertNotIn("display-values", data_web)
        self.assertNotIn("update_report_field", data_web)
        self.assertIn('/api/fields/<report_id>/<field_key>', fields_web)
        widgets = (APP / "stats_core" / "services" / "widgets.py").read_text(encoding="utf-8")
        self.assertIn("self.widgets.render", screens)
        self.assertNotIn("self.reports", screens)
        self.assertIn("self.fields.evaluate", widgets)
        self.assertIn("self.fields.rank", widgets)

    def test_draft_formula_preview_uses_cached_rows_without_saving(self):
        before = self.runtime.repos.fields.list(self.report_id)
        version = self.runtime.repos.meta.get("settings_version")
        incoming = {"label": "Preview average", "formula": "[Revenue] ÷ [Sold]",
                    "type": "number", "decimals": 2}
        response = self.client.post(f"/api/fields/{self.report_id}/preview", json=incoming)
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()["payload"]
        key = payload["field"]["key"]
        self.assertEqual([row[key] for row in payload["rows"]], [60, 100])
        self.assertEqual(payload["total_rows"], 2)
        self.assertEqual(self.runtime.repos.fields.list(self.report_id), before)
        self.assertEqual(self.runtime.repos.meta.get("settings_version"), version)
        saved = self.runtime.fields.save_calculated(self.report_id, incoming)
        rows = self.runtime.fields.materialize(self.report_id, self.runtime.reports.rows(self.report_id))
        self.assertEqual([row[saved["key"]] for row in rows], [row[key] for row in payload["rows"]])

    def test_draft_formula_rejects_invalid_syntax_and_exposes_division_by_zero(self):
        for formula in ("[Revenue] % [Sold]", "[Missing] + 1", "[Revenue] /", "__import__('os')"):
            response = self.client.post(f"/api/fields/{self.report_id}/preview", json={
                "label": "Bad draft", "type": "number", "formula": formula})
            self.assertEqual(response.status_code, 400, response.get_json())
        response = self.client.post(f"/api/fields/{self.report_id}/preview", json={
            "label": "Undefined", "type": "percent", "percent_input_scale": "fraction", "formula": "[Sold] / 0"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["payload"]
        self.assertEqual(payload["unavailable_rows"], 2)
        self.assertTrue(all(row[payload["field"]["key"]] is None for row in payload["rows"]))


if __name__ == "__main__":
    unittest.main()
