#!/usr/bin/env python3
"""Unsaved Report filter discovery contracts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from stats_core.services.reports import ReportService  # noqa: E402
from stats_core.services.source import SourceService  # noqa: E402


class FakeCatalog:
    def __init__(self):
        self.value = {
            "sources": [{
                "id": "source-a",
                "name": "Source A",
                "adapter": "fake",
                "enabled": True,
                "connection": {},
            }],
            "reports": [],
        }
        self.save_calls = 0

    def get(self):
        return {"sources": list(self.value["sources"]), "reports": list(self.value["reports"])}

    def source(self, source_id):
        return next((dict(row) for row in self.value["sources"] if row["id"] == source_id), None)

    def report(self, report_id):
        return next((dict(row) for row in self.value["reports"] if row["id"] == report_id), None)

    def save(self, value):
        self.save_calls += 1
        self.value = value


class FakeAdapter:
    def __init__(self):
        self.inspected_report = None

    @staticmethod
    def with_secret(settings, secret):
        return dict(settings or {})

    @staticmethod
    def configure_report_value(value, existing=None):
        workbook, sheet = str(value).split("/", 1)
        return {**dict(existing or {}), "workbook": workbook, "sheet": sheet}

    @staticmethod
    def candidate_overrides(body):
        return {}

    def columns(self, app_settings, source, report, overrides=None):
        self.inspected_report = dict(report)
        return {
            "filter_fields": [{"field": "Office", "values": ["Olympia"], "truncated": False}],
            "headers": ["Office", "Revenue"],
        }


class UnsavedReportFilterTests(unittest.TestCase):
    def test_candidate_columns_do_not_save_report(self):
        catalog = FakeCatalog()
        repos = SimpleNamespace(
            data_catalog=catalog,
            source_credentials=SimpleNamespace(get=lambda _source_id: "secret"),
            settings=SimpleNamespace(get=lambda: {}),
        )
        adapter = FakeAdapter()
        reports = ReportService(repos, {"fake": adapter})
        sources = SourceService(repos, reports, {"fake": adapter})

        result = sources.candidate_columns_for("source-a", {
            "name": "Unsaved Report",
            "source_value": "Workbook/View",
            "filters": [{"field": "Office", "value": "Olympia"}],
            "runtime": {"date_mode": "current_month"},
        })

        self.assertEqual(result["filter_fields"][0]["field"], "Office")
        self.assertEqual(adapter.inspected_report["source_config"]["workbook"], "Workbook")
        self.assertEqual(adapter.inspected_report["source_config"]["filters"][0]["value"], "Olympia")
        self.assertEqual(catalog.value["reports"], [])
        self.assertEqual(catalog.save_calls, 0)


if __name__ == "__main__":
    unittest.main()
