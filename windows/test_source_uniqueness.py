#!/usr/bin/env python3
"""Contract tests for Source uniqueness while only one adapter instance is supported."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))


class SourceUniquenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_data_dir = os.environ.get("STATS_DATA_DIR")
        os.environ["STATS_DATA_DIR"] = self.temp.name
        from stats_core.bootstrap import create_app

        self.app = create_app("windows", start_background=False)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        if self.previous_data_dir is None:
            os.environ.pop("STATS_DATA_DIR", None)
        else:
            os.environ["STATS_DATA_DIR"] = self.previous_data_dir
        self.temp.cleanup()

    @staticmethod
    def tableau_payload(name):
        return {
            "name": name,
            "adapter": "tableau",
            "connection": {
                "server": "https://tableau.example",
                "site": "site",
                "pat_name": "token",
            },
        }

    def test_second_tableau_source_is_rejected(self):
        first = self.client.post("/api/data/sources", json=self.tableau_payload("Tableau"))
        self.assertEqual(first.status_code, 200)

        duplicate = self.client.post("/api/data/sources", json=self.tableau_payload("Another Tableau"))
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn("already configured", duplicate.get_json()["error"].lower())
        self.assertEqual(len(self.client.get("/api/data/sources").get_json()["sources"]), 1)

    def test_existing_tableau_source_can_still_be_edited(self):
        created = self.client.post("/api/data/sources", json=self.tableau_payload("Tableau"))
        source = created.get_json()["source"]
        payload = self.tableau_payload("Renamed Tableau")

        updated = self.client.put(f"/api/data/sources/{source['id']}", json=payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["source"]["name"], "Renamed Tableau")


if __name__ == "__main__":
    unittest.main()
