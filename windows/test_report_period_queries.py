#!/usr/bin/env python3
"""Isolated date-query snapshots, retention, and deletion dependencies."""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))


class FakePeriodAdapter:
    def __init__(self):
        self.calls = []
        self.rows = [{"Name": "Alex", "Net": 100}, {"Name": "Blair", "Net": 200}]
        self.fail = False
        self.wrong_period = False
        self.missing_field = False

    def with_secret(self, settings, secret):
        return settings

    def table(self, settings, source, report):
        self.calls.append(copy.deepcopy(report))
        if self.fail:
            raise RuntimeError("The provider is unavailable")
        fields = [{"key": "Name", "label": "Name", "type": "text"}]
        if not self.missing_field:
            fields.append({"key": "Net", "label": "Net", "type": "number"})
        return {"fields": fields, "rows": copy.deepcopy(self.rows),
                "start": "1900-01-01" if self.wrong_period else report["runtime"]["date_start"],
                "end": report["runtime"]["date_end"]}


class ReportPeriodQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["STATS_DATA_DIR"] = self.temp.name
        from stats_core.repositories import Repositories
        from stats_core.services.reports import ReportService
        self.repos = Repositories(data_root=self.temp.name)
        self.report = {"id": "report", "name": "Sales", "source_id": "source", "source_config": {"view": "a"},
                       "runtime": {"date_mode": "current_month", "keep_last_known_rows": True, "update_interval_minutes": 2}}
        self.repos.data_catalog.save({"sources": [{"id": "source", "adapter": "fake", "enabled": True}], "reports": [self.report]})
        self.default = self.repos.report_data.replace("report", [
            {"key": "Name", "label": "Name", "type": "text"},
            {"key": "Net", "label": "Net", "type": "number"},
        ], [{"Name": "Default member", "Net": 15}], {"start": "2026-09-01", "end": "2026-09-30"})
        self.adapter = FakePeriodAdapter()
        self.now = 1000
        self.dependencies = []
        self.reports = ReportService(self.repos, {"fake": self.adapter}, dependencies=lambda report_id: self.dependencies, clock=lambda: self.now)

    @staticmethod
    def custom(start="2026-01-01", end="2026-09-04"):
        return {"preset": "custom", "start_date": start, "end_date": end}

    def test_validates_and_normalizes_timeframes_before_provider_access(self):
        from stats_core.errors import ValidationError
        from stats_core.services.data_periods import resolve_timeframe
        self.assertEqual(resolve_timeframe({"preset": "current_month"}, date(2024, 2, 15)), ("2024-02-01", "2024-02-29"))
        self.assertEqual(resolve_timeframe({"preset": "year_to_date"}, date(2026, 9, 4)), ("2026-01-01", "2026-09-04"))
        for request in ({}, {"preset": "all_time"}, self.custom("broken"), self.custom("2026-12-01", "2026-01-01"), {"preset": "custom"}, {"preset": "current_month", "sql": "ignored"}):
            with self.subTest(request=request), self.assertRaises(ValidationError):
                self.reports.rows_for_period("report", request)
        self.assertEqual(self.adapter.calls, [])

    def test_period_fetch_is_isolated_and_cache_uses_update_interval(self):
        rows = self.reports.rows_for_period("report", self.custom())
        self.assertEqual(rows, self.adapter.rows)
        self.assertEqual(self.adapter.calls[0]["runtime"]["date_mode"], "custom")
        self.assertEqual(self.adapter.calls[0]["runtime"]["date_start"], "2026-01-01")
        self.assertEqual(self.adapter.calls[0]["runtime"]["date_end"], "2026-09-04")
        rows[0]["Net"] = 999
        self.now += 119
        self.assertEqual(self.reports.rows_for_period("report", self.custom())[0]["Net"], 100)
        self.assertEqual(len(self.adapter.calls), 1)
        self.now += 1
        self.reports.rows_for_period("report", self.custom())
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(self.reports.get("report"), self.report)
        self.assertEqual(self.repos.report_data.read("report"), self.default)

    def test_windows_and_changed_pull_configuration_have_distinct_snapshots(self):
        self.reports.rows_for_period("report", self.custom())
        self.reports.rows_for_period("report", self.custom("2026-09-01", "2026-09-30"))
        catalog = self.repos.data_catalog.get()
        catalog["reports"][0]["source_config"] = {"view": "b"}
        self.repos.data_catalog.save(catalog)
        self.adapter.rows = [{"Name": "Other view", "Net": 3}]
        changed = self.reports.rows_for_period("report", self.custom())
        self.assertEqual(changed, self.adapter.rows)
        self.assertEqual(len(self.adapter.calls), 3)
        self.assertEqual(len(self.repos.report_data.list_queries("report")), 3)

    def test_missing_rows_are_kept_within_period_and_present_zero_replaces(self):
        self.reports.rows_for_period("report", self.custom())
        self.now += 120
        self.adapter.rows = [{"Name": "Alex", "Net": 0}]
        rows = self.reports.rows_for_period("report", self.custom())
        self.assertEqual(rows, [{"Name": "Alex", "Net": 0}, {"Name": "Blair", "Net": 200}])
        self.now += 120
        self.adapter.rows = [{"Name": "Alex", "Net": 5}, {"Name": "Blair", "Net": 300}]
        rows = self.reports.rows_for_period("report", self.custom())
        self.assertEqual(rows[1]["Net"], 300)
        self.assertEqual(self.repos.report_data.list_queries("report")[0]["meta"]["retained_row_keys"], [])

    def test_expanding_window_retains_but_new_month_does_not(self):
        self.reports.rows_for_period("report", self.custom("2026-09-01", "2026-09-15"))
        self.adapter.rows = [{"Name": "Alex", "Net": 150}]
        expanded = self.reports.rows_for_period("report", self.custom("2026-09-01", "2026-09-30"))
        self.assertEqual([row["Name"] for row in expanded], ["Alex", "Blair"])
        next_month = self.reports.rows_for_period("report", self.custom("2026-10-01", "2026-10-31"))
        self.assertEqual([row["Name"] for row in next_month], ["Alex"])

    def test_disabled_retention_does_not_reuse_older_rows(self):
        self.reports.rows_for_period("report", self.custom())
        self.adapter.rows = []
        catalog = self.repos.data_catalog.get()
        catalog["reports"][0]["runtime"]["keep_last_known_rows"] = False
        self.repos.data_catalog.save(catalog)
        self.assertEqual(self.reports.rows_for_period("report", self.custom()), [])

    def test_failed_pull_preserves_old_snapshot_and_does_not_return_wrong_dates(self):
        from stats_core.errors import ValidationError
        self.reports.rows_for_period("report", self.custom())
        before = self.repos.report_data.list_queries("report")
        self.now += 120
        self.adapter.fail = True
        with self.assertRaisesRegex(RuntimeError, "provider is unavailable"):
            self.reports.rows_for_period("report", self.custom())
        self.assertEqual(self.repos.report_data.list_queries("report"), before)
        self.adapter.fail = False
        self.adapter.wrong_period = True
        with self.assertRaisesRegex(ValidationError, "different timeframe"):
            self.reports.rows_for_period("report", self.custom())
        self.adapter.wrong_period = False
        self.adapter.missing_field = True
        with self.assertRaisesRegex(ValidationError, "missing Field"):
            self.reports.rows_for_period("report", self.custom())
        self.assertEqual(self.repos.report_data.list_queries("report"), before)
        self.assertEqual(self.repos.report_data.read("report"), self.default)

    def test_manual_refresh_interval_still_has_minimum_cache_ttl(self):
        catalog = self.repos.data_catalog.get()
        catalog["reports"][0]["runtime"]["update_interval_minutes"] = 0
        self.repos.data_catalog.save(catalog)
        self.reports.rows_for_period("report", self.custom())
        self.now += 59
        self.reports.rows_for_period("report", self.custom())
        self.assertEqual(len(self.adapter.calls), 1)
        self.now += 1
        self.reports.rows_for_period("report", self.custom())
        self.assertEqual(len(self.adapter.calls), 2)

    def test_report_deletion_checks_dependencies_before_any_mutation(self):
        from stats_core.errors import ValidationError
        self.reports.rows_for_period("report", self.custom())
        self.dependencies = ["Net vs Cancelled Widget"]
        with self.assertRaisesRegex(ValidationError, "Net vs Cancelled Widget"):
            self.reports.delete("report")
        self.assertEqual(self.reports.get("report"), self.report)
        self.assertEqual(self.repos.report_data.read("report"), self.default)
        self.assertEqual(len(self.repos.report_data.list_queries("report")), 1)
        self.dependencies = []
        self.assertTrue(self.reports.delete("report"))
        self.assertEqual(self.repos.report_data.list_queries("report"), [])
        self.assertEqual(self.repos.report_data.read("report")["rows"], [])


if __name__ == "__main__":
    unittest.main()
