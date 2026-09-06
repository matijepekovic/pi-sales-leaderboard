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
        settings_css = (APP / "static" / "settings" / "shell.css").read_text(encoding="utf-8")
        source_service = (APP / "stats_core" / "services" / "source.py").read_text(encoding="utf-8")
        adapter = (APP / "sources" / "tableau_adapter.py").read_text(encoding="utf-8")

        self.assertIn('id="reportSearch"', data_ui)
        self.assertIn("/report-columns", data_ui)
        self.assertIn('placeholder="Field name"', data_ui)
        self.assertIn('report.source_value?"":"disabled"', data_ui)
        self.assertIn("data-report-group", data_ui)
        self.assertNotIn("data-report-group open", data_ui)
        self.assertIn("Saved Reports", data_ui)
        self.assertIn("Available Reports", data_ui)
        self.assertIn("data-available-reports", data_ui)
        self.assertIn('availableReportsOpen:false', data_ui)
        self.assertIn("data-report-update-interval", data_ui)
        self.assertIn("data-saved-report", data_ui)
        self.assertIn("data-report-inspection", data_ui)
        self.assertIn("data-report-editor", data_ui)
        self.assertIn("${reportInspection(report)}${reportEditor(report.id)}", data_ui)
        self.assertIn('const actions=editing?""', data_ui)
        self.assertIn("data-editing-report", data_ui)
        self.assertIn('group.querySelector("[data-editing-report]")', data_ui)
        self.assertIn('expanded?"Hide Data":"View Data"', data_ui)
        self.assertNotIn("${inspection()}", data_ui)
        self.assertNotIn("${sourceEditor()}${reportEditor()}", data_ui)
        self.assertIn("Press any column heading or value", data_ui)
        self.assertIn("data-inspection-field", data_ui)
        self.assertIn("editor.form(report.id,selectedField)", data_ui)
        self.assertIn("editor.formatValue(row[field.key],field.type,field.decimals,field.percent_input_scale)", data_ui)
        self.assertNotIn("editor.list(report.id,fields)", data_ui)
        self.assertIn("StatsFieldEditor", data_ui)
        self.assertNotIn('data-action="open-display-values"', data_ui)
        self.assertNotIn('<div class="field-key">Display Value</div>', data_ui)
        self.assertNotIn("field.sample_values", data_ui)
        self.assertIn("let loaded=false,loadPromise=null", data_ui)
        self.assertIn("if(loadPromise)return loadPromise", data_ui)
        self.assertIn("Your saved Reports are unaffected", data_ui)
        self.assertNotIn("catch(error){state.message=error.message;}\n    if(!quiet)render();", data_ui)
        self.assertIn('const customDates=rt.date_mode==="custom"', data_ui)
        self.assertIn('[data-report="date_mode"]\')?.addEventListener("change"', data_ui)
        self.assertIn("state.values.filter(item=>!reportForValue(item.id))", data_ui)
        self.assertNotIn("const unmatched=", data_ui)
        save_report = data_ui.split("async function saveReport(){", 1)[1].split("async function inspectReport", 1)[0]
        self.assertNotIn("/refresh", save_report)
        self.assertNotIn("loadColumnsForEditor", save_report)
        self.assertIn("state.editor=null", save_report)
        self.assertIn("state.columns=null", save_report)
        self.assertIn("Use Refresh now", save_report)
        self.assertIn('item.get("group")', source_service)
        self.assertIn("candidate_columns_for", source_service)
        self.assertIn("project.name", adapter)
        self.assertNotIn("project.name", source_service)
        self.assertNotIn("project", data_ui.lower())
        self.assertIn("#settingsDataHost [data-report-inspection]{min-width:0;max-width:100%}", settings_css)
        self.assertIn(".data-table table{border-collapse:collapse;width:max-content;min-width:100%", settings_css)


if __name__ == "__main__":
    unittest.main()
