#!/usr/bin/env python3
"""Contracts for searchable, source-neutral Report browsing."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from sources.tableau_adapter import TableauAdapter  # noqa: E402


class FakeConnector:
    def __init__(self):
        self.signed_out = False

    def signin(self):
        return "https://tableau.example/api/3.29", "token", "site"

    def _request(self, url, token=None, timeout=60):
        assert "project.name" in url
        payload = {
            "views": {
                "view": [
                    {
                        "name": "Monthly Leaderboard",
                        "contentUrl": "sales/monthly",
                        "project": {"name": "Sales"},
                    },
                    {
                        "name": "Unsorted Report",
                        "contentUrl": "misc/report",
                    },
                ]
            }
        }
        return 200, json.dumps(payload).encode()

    @staticmethod
    def _view_list(payload):
        rows = payload.get("views", {}).get("view", [])
        return [rows] if isinstance(rows, dict) else rows

    def signout(self, base, token):
        self.signed_out = True


class FakeRuntime:
    def __init__(self, connector):
        self.connector = connector

    @staticmethod
    def normalized_settings(settings):
        return settings

    def source(self, settings):
        return self.connector


class ReportBrowsingContractTests(unittest.TestCase):
    def test_tableau_translates_projects_to_generic_groups(self):
        connector = FakeConnector()
        adapter = TableauAdapter(runtime=FakeRuntime(connector))
        values = adapter.report_values({}, {"connection": {}})

        self.assertEqual(values, [
            {"id": "misc/report", "label": "Unsorted Report", "group": "Other"},
            {"id": "sales/monthly", "label": "Monthly Leaderboard", "group": "Sales"},
        ])
        self.assertTrue(connector.signed_out)

    def test_stats_ui_uses_search_and_generic_groups_only(self):
        data_ui = (APP / "static" / "settings" / "data.js").read_text(encoding="utf-8")
        source_service = (APP / "stats_core" / "services" / "source.py").read_text(encoding="utf-8")
        adapter = (APP / "sources" / "tableau_adapter.py").read_text(encoding="utf-8")

        self.assertIn('id="reportSearch"', data_ui)
        self.assertIn("data-report-group", data_ui)
        self.assertIn('item.get("group")', source_service)
        self.assertIn("project.name", adapter)
        self.assertNotIn("project.name", source_service)
        self.assertNotIn("project", data_ui.lower())


if __name__ == "__main__":
    unittest.main()
