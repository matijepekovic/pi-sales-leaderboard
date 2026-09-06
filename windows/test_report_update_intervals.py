#!/usr/bin/env python3
"""Saved Report automatic-update contract tests."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from stats_core.errors import ValidationError  # noqa: E402
from stats_core.services.report_updates import ReportUpdateService  # noqa: E402
from stats_core.services.reports import ReportService  # noqa: E402


class FakeReports:
    def __init__(self):
        self.refreshed = []

    def list(self):
        return [
            {"id": "manual", "runtime": {"update_interval_minutes": 0}, "last_refresh": ""},
            {"id": "due", "runtime": {"update_interval_minutes": 15}, "last_refresh": "2026-09-01 11:44:00"},
            {"id": "fresh", "runtime": {"update_interval_minutes": 15}, "last_refresh": "2026-09-01 11:50:00"},
            {"id": "new", "runtime": {"update_interval_minutes": 5}, "last_refresh": ""},
        ]

    def refresh(self, report_id):
        self.refreshed.append(report_id)
        if report_id == "due":
            raise RuntimeError("temporary source failure")
        return {"ok": True}


class ReportUpdateIntervalTests(unittest.TestCase):
    def test_only_due_saved_reports_run_and_failures_observe_the_interval(self):
        reports = FakeReports()
        updates = ReportUpdateService(reports)

        self.assertEqual(updates.run_due(datetime(2026, 9, 1, 12, 0)), ["due", "new"])
        self.assertEqual(updates.run_due(datetime(2026, 9, 1, 12, 1)), [])
        self.assertEqual(updates.run_due(datetime(2026, 9, 1, 12, 16)), ["due", "fresh", "new"])
        self.assertEqual(reports.refreshed, ["due", "new", "due", "fresh", "new"])

    def test_report_runtime_normalizes_and_validates_update_minutes(self):
        self.assertEqual(
            ReportService._runtime({"update_interval_minutes": "30"})["update_interval_minutes"],
            30,
        )
        with self.assertRaises(ValidationError):
            ReportService._runtime({"update_interval_minutes": -1})
        with self.assertRaises(ValidationError):
            ReportService._runtime({"update_interval_minutes": 10081})


if __name__ == "__main__":
    unittest.main()
