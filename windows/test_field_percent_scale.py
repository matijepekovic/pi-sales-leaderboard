"""Explicit percentage input meaning stays global without rewriting source rows."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


class FieldPercentScaleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {"STATS_DATA_DIR": self.temp.name})
        environment.start()
        self.addCleanup(environment.stop)
        from stats_core.bootstrap import create_app

        app = create_app("windows", start_background=False)
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.runtime = app.extensions["stats_runtime"]
        source = self.client.post("/api/data/sources", json={
            "name": "Percentage source", "adapter": "tableau",
            "connection": {"server": "https://example.invalid", "site": "test", "pat_name": "test"},
        }).get_json()["source"]
        self.report_id = self.client.post("/api/data/reports", json={
            "source_id": source["id"], "name": "Percentage report",
            "source_config": {"workbook": "Workbook", "sheet": "View"},
        }).get_json()["report"]["id"]
        self.runtime.repos.report_data.replace(self.report_id, [
            {"key": "Rate", "label": "Rate", "type": "percent"},
            {"key": "Name", "label": "Name", "type": "text"},
        ], [{"Name": "A", "Rate": .99}, {"Name": "B", "Rate": 1.01}], {"status": "2 rows"})
        self.snapshot = copy.deepcopy(self.runtime.repos.report_data.read(self.report_id))
        self.field_id = self.runtime.fields.ids_for_report(self.report_id, ["Rate"])[0]

    def update(self, **changes):
        return self.client.put(f"/api/fields/{self.report_id}/Rate", json={
            "kind": "report", "label": "Rate", "type": "percent", "decimals": 1, **changes,
        })

    def test_legacy_percentage_fields_default_to_auto_without_storage_changes(self):
        field = self.runtime.fields.resolve([self.field_id])[0]
        self.assertEqual(field["percent_input_scale"], "auto")
        self.assertNotIn("field_overrides", self.runtime.reports.get(self.report_id))
        self.assertEqual(self.runtime.repos.report_data.read(self.report_id), self.snapshot)

    def test_report_scale_is_saved_globally_and_forwarded_to_every_consumer(self):
        response = self.update(percent_input_scale="fraction")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["field"]["customized"])
        self.assertEqual(response.get_json()["field"]["percent_input_scale"], "fraction")
        stored = self.runtime.reports.get(self.report_id)["field_overrides"]["Rate"]
        self.assertEqual(stored["percent_input_scale"], "fraction")
        catalog = self.client.get(f"/api/fields/{self.report_id}").get_json()
        self.assertEqual(next(field for field in catalog["fields"] if field["key"] == "Rate")["percent_input_scale"], "fraction")
        payload = self.client.post("/api/widgets/preview", json={"widget": {
            "name": "Values", "kind": "table", "field_ids": [self.field_id],
        }}).get_json()["payload"]
        self.assertEqual(payload["fields"][0]["percent_input_scale"], "fraction")
        self.assertEqual([row[self.field_id] for row in payload["rows"]], [.99, 1.01])
        self.assertEqual(self.runtime.repos.report_data.read(self.report_id), self.snapshot)
        self.assertEqual(self.update(label="Renamed").get_json()["field"]["percent_input_scale"], "fraction")

    def test_points_reset_and_type_changes_preserve_existing_metadata_contract(self):
        self.assertEqual(self.update(percent_input_scale="points").get_json()["field"]["percent_input_scale"], "points")
        reset = self.update(percent_input_scale="auto").get_json()["field"]
        self.assertEqual(reset["percent_input_scale"], "auto")
        self.assertFalse(reset["customized"])
        self.assertNotIn("field_overrides", self.runtime.reports.get(self.report_id))
        self.update(percent_input_scale="fraction")
        changed = self.update(type="number", decimals=2).get_json()["field"]
        self.assertNotIn("percent_input_scale", changed)
        self.assertNotIn("percent_input_scale", self.runtime.reports.get(self.report_id)["field_overrides"]["Rate"])
        self.assertEqual(self.runtime.repos.report_data.read(self.report_id), self.snapshot)

    def test_invalid_percentage_scale_is_rejected_without_saving(self):
        before = copy.deepcopy(self.runtime.reports.get(self.report_id))
        response = self.update(percent_input_scale="guess-by-chart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Choose Automatic", response.get_json()["error"])
        self.assertEqual(self.runtime.reports.get(self.report_id), before)

    def test_calculated_fields_keep_explicit_scale_through_rename_and_evaluation(self):
        response = self.client.post(f"/api/fields/{self.report_id}", json={
            "kind": "calculated", "label": "Calculated rate", "formula": "[Rate]",
            "type": "percent", "decimals": 1, "percent_input_scale": "fraction",
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        key = response.get_json()["field"]["key"]
        renamed = self.client.put(f"/api/fields/{self.report_id}/{key}", json={
            "kind": "calculated", "label": "Renamed calculation",
        })
        self.assertEqual(renamed.get_json()["field"]["percent_input_scale"], "fraction")
        field_id = self.runtime.fields.ids_for_report(self.report_id, [key])[0]
        evaluated = self.runtime.fields.evaluate([field_id])
        self.assertEqual(evaluated["fields"][0]["percent_input_scale"], "fraction")
        self.assertEqual([row[field_id] for row in evaluated["rows"]], [.99, 1.01])
        bad = self.client.put(f"/api/fields/{self.report_id}/{key}", json={
            "kind": "calculated", "label": "Wrong", "percent_input_scale": "invalid",
        })
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.runtime.fields.field(self.report_id, key)["label"], "Renamed calculation")

    @unittest.skipUnless(shutil.which("node"), "Node is required for shared formatting behavior")
    def test_shared_percentage_formatting_and_editor(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "windows/test_field_percent_scale.js")], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
