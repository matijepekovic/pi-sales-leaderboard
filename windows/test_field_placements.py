"""Field-placement contracts use real period APIs, never positional matching."""
from __future__ import annotations

import copy
import shutil
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from stats_core.errors import ValidationError
from stats_core.services.data_periods import normalize_timeframe, resolve_timeframe, timeframe_intervals
from stats_core.services.field_placements import evaluate_field_placements, normalize_field_variants
from stats_core.services.widget_timelines import build_timeline


class PublicFields:
    """Only the public Fields interface; no repositories or vendor contracts."""
    def __init__(self):
        self.calls = []
        self.metadata = [{"id": "name", "key": "name", "label": "Name", "type": "text", "kind": "report"},
                         {"id": "net", "key": "net", "label": "Net", "type": "number", "kind": "report"},
                         {"id": "rate", "key": "rate", "label": "Rate", "type": "percent", "kind": "report"}]
        self.current = [{"name": "Alex", "net": 5, "rate": .5, "__row_key": "alex"},
                        {"name": "Blair", "net": 8, "rate": .8, "__row_key": "blair"}]
        self.historical = [{"name": "Blair", "net": 80, "__row_key": "blair"},
                           {"name": "Alex", "net": 50, "__row_key": "alex"},
                           {"name": "Casey", "net": 30, "__row_key": "casey"}]

    def resolve(self, field_ids):
        return [copy.deepcopy(field) for field in self.metadata if field["id"] in field_ids]

    def evaluate(self, field_ids, context):
        self.calls.append(copy.deepcopy(context))
        rows = self.historical if context.get("timeframe") else self.current
        return {"fields": self.resolve(field_ids), "rows": copy.deepcopy(rows)}


class FieldPlacementTests(unittest.TestCase):
    def setUp(self):
        self.fields = PublicFields()
        self.ids = ["name", "net"]
        self.variant = {"id": "placement-net-ytd", "field_id": "net", "label": "YTD Net",
                        "timeframe": {"preset": "year_to_date"}}

    def test_validation_never_reads_rows_and_preserves_global_fields(self):
        before = copy.deepcopy(self.fields.metadata)
        original = copy.deepcopy(self.variant)
        result = normalize_field_variants(self.ids, [self.variant], self.fields)
        self.assertEqual(result, [original])
        self.assertEqual(self.fields.calls, [])
        self.assertEqual(self.fields.metadata, before)
        self.assertEqual(self.variant, original)

    def test_original_and_custom_periods_match_identity_not_row_order(self):
        result = evaluate_field_placements(self.fields, self.ids, {"identity_field_id": "name", "field_variants": [self.variant]})
        self.assertEqual([(row["name"], row["net"], row[self.variant["id"]]) for row in result["rows"]],
                         [("Alex", 5, 50), ("Blair", 8, 80), ("Casey", 0, 30)])
        self.assertEqual([field["label"] for field in result["fields"]], ["Name", "Net", "YTD Net"])
        self.assertTrue(result["fields"][-1]["instance_only"])
        self.assertEqual(result["fields"][-1]["source_field_id"], "net")
        self.assertNotIn("field_variants", self.fields.calls[-1])
        self.assertEqual(self.fields.calls[-1]["timeframe"], {"preset": "year_to_date"})

    def test_missing_period_member_keeps_current_row_with_zero_custom_cell(self):
        self.fields.historical = [self.fields.historical[0]]
        result = evaluate_field_placements(self.fields, self.ids, {"field_variants": [self.variant]})
        self.assertEqual(result["rows"][0]["net"], 5)
        self.assertEqual(result["rows"][0][self.variant["id"]], 0)

    def test_missing_or_duplicated_identity_never_zips_records(self):
        for mutation in (lambda rows: [row.pop("__row_key") for row in rows],
                         lambda rows: rows[1].update(__row_key=rows[0]["__row_key"])):
            self.fields = PublicFields()
            mutation(self.fields.current)
            with self.assertRaises(ValidationError):
                evaluate_field_placements(self.fields, self.ids, {"field_variants": [self.variant]})
            self.assertEqual(len(self.fields.calls), 1)

    def test_row_aliases_support_confirmed_cross_report_keys(self):
        self.fields.historical[1]["__row_key"] = "other-report-alex"
        self.fields.historical[1]["__row_keys"] = ["alex", "other-report-alex"]
        result = evaluate_field_placements(self.fields, self.ids, {"field_variants": [self.variant]})
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual(result["rows"][0][self.variant["id"]], 50)

    def test_blank_matching_values_stay_as_unmatched_rows_not_positional_matches(self):
        self.fields.current[0].pop("__row_key")
        self.fields.current[0]["name"] = ""
        self.fields.historical[1].pop("__row_key")
        self.fields.historical[1]["name"] = ""
        result = evaluate_field_placements(self.fields, self.ids, {"identity_field_id": "name", "field_variants": [self.variant]})
        unnamed = [row for row in result["rows"] if row["name"] == ""]
        self.assertEqual([(row["net"], row[self.variant["id"]]) for row in unnamed], [(5, 0), (0, 50)])

    def test_invalid_custom_calculation_remains_invalid_not_blank_zero(self):
        self.fields.historical[1]["net"] = None
        self.fields.historical[1]["__invalid_fields"] = ["net"]
        result = evaluate_field_placements(self.fields, self.ids, {"field_variants": [self.variant]})
        self.assertIsNone(result["rows"][0][self.variant["id"]])
        self.assertIn(self.variant["id"], result["rows"][0]["__invalid_fields"])

    def test_duplicate_placements_names_and_original_names_are_rejected(self):
        for variants in ([self.variant, {**self.variant, "label": "Another name"}],
                         [self.variant, {**self.variant, "id": "placement-other"}],
                         [{**self.variant, "label": "net"}],
                         [{**self.variant, "id": "net"}],
                         [{**self.variant, "field_id": "missing"}],
                         [{**self.variant, "label": ""}],
                         [{**self.variant, "field_id": "name"}]):
            with self.subTest(variants=variants), self.assertRaises(ValidationError):
                normalize_field_variants(self.ids, variants, self.fields)
        self.assertEqual(self.fields.calls, [])

    def test_same_source_can_have_many_distinct_local_versions(self):
        variants = [self.variant, {**self.variant, "id": "placement-last-year", "label": "Last year Net",
                                  "timeframe": {"preset": "previous_year"}}]
        result = evaluate_field_placements(self.fields, self.ids, {"field_variants": variants})
        self.assertEqual(len(result["fields"]), 4)
        self.assertEqual(result["rows"][0]["net"], 5)
        self.assertEqual(result["rows"][0]["placement-last-year"], 50)

    def test_timeline_pulls_each_bin_without_repeating_default_snapshot(self):
        variant = {**self.variant, "timeframe": {"preset": "custom", "start_date": "2024-01-15", "end_date": "2024-03-02"},
                   "interval": {"unit": "month", "count": 1}, "aggregation": "average"}
        result = evaluate_field_placements(self.fields, self.ids, {"field_variants": [variant], "group_ids": ["north"]})
        timeline = result["timelines"][0]
        self.assertEqual(timeline["aggregation"], "average")
        self.assertEqual([(point["start_date"], point["end_date"]) for point in timeline["points"]],
                         [("2024-01-15", "2024-01-31"), ("2024-02-01", "2024-02-29"), ("2024-03-01", "2024-03-02")])
        self.assertEqual(len(self.fields.calls), 4)
        self.assertTrue(all(call["group_ids"] == ["north"] for call in self.fields.calls))
        self.assertTrue(all(point["rows"][0]["net"] == 80 for point in timeline["points"]))
        self.assertNotIn(variant["id"], result["rows"][0])

    def test_timeline_needs_explicit_calculation_and_does_not_sum_rates(self):
        variant = {**self.variant, "interval": {"unit": "month", "count": 1}}
        with self.assertRaisesRegex(ValidationError, "Choose what each"):
            normalize_field_variants(self.ids, [variant], self.fields)
        with self.assertRaisesRegex(ValidationError, "Percentages"):
            normalize_field_variants(["rate"], [{**variant, "field_id": "rate", "aggregation": "sum"}], self.fields)

    @unittest.skipUnless(shutil.which("node"), "Node is required for Screen controls")
    def test_screen_controls_keep_period_versions_local(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "windows/test_screen_field_placements.js")],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DataPeriodIntervalTests(unittest.TestCase):
    def test_standard_windows_and_rolling_offsets(self):
        today = date(2024, 3, 15)
        self.assertEqual(resolve_timeframe({"preset": "previous_month"}, today), ("2024-02-01", "2024-02-29"))
        self.assertEqual(resolve_timeframe({"preset": "previous_quarter"}, today), ("2023-10-01", "2023-12-31"))
        self.assertEqual(resolve_timeframe({"preset": "rolling", "unit": "day", "count": 7, "offset": 7}, today), ("2024-03-02", "2024-03-08"))
        self.assertEqual(resolve_timeframe({"preset": "rolling", "unit": "month", "count": 1}, date(2024, 3, 31)), ("2024-03-01", "2024-03-31"))
        rolling = {"preset": "rolling", "unit": "month", "count": 3, "offset": 3}
        self.assertEqual(normalize_timeframe(rolling), rolling)

    def test_custom_cadences_are_ordered_nonoverlapping_and_clip_future(self):
        bins = timeframe_intervals({"preset": "custom", "start_date": "2024-01-03", "end_date": "2024-02-05"},
                                  {"unit": "week", "count": 2}, date(2024, 1, 24))
        self.assertEqual([(point["start_date"], point["end_date"]) for point in bins],
                         [("2024-01-03", "2024-01-14"), ("2024-01-15", "2024-01-24")])

    def test_invalid_counts_units_and_large_pull_fanout_are_rejected(self):
        for request in ({"preset": "rolling", "unit": "day", "count": 0},
                        {"preset": "rolling", "unit": "day", "count": True},
                        {"preset": "rolling", "unit": "hour", "count": 1},
                        {"preset": "rolling", "unit": "year", "count": 20}):
            with self.assertRaises(ValidationError):
                resolve_timeframe(request)
        with self.assertRaisesRegex(ValidationError, "120 points"):
            timeframe_intervals({"preset": "custom", "start_date": "2024-01-01", "end_date": "2024-12-31"},
                                {"unit": "day", "count": 1})


class WidgetTimelineIdentityTests(unittest.TestCase):
    def timeline(self, rows_by_period, aggregation="none"):
        fields = PublicFields().resolve(["name", "net"])
        return {"field_id": "placement-history", "source_field_id": "net", "field": fields[1], "label": "Net history",
                "aggregation": aggregation, "timeframe": {"preset": "previous_year"}, "interval": {"unit": "month", "count": 1},
                "points": [{"label": str(index), "start_date": f"2024-0{index + 1}-01", "end_date": f"2024-0{index + 1}-28",
                            "fields": fields, "rows": rows} for index, rows in enumerate(rows_by_period)]}

    def test_missing_identity_observations_are_preserved_but_never_connected(self):
        timeline = self.timeline([[{"name": "", "net": 10}], [{"name": "", "net": 20}]])
        result = build_timeline(timeline, {}, "name")
        self.assertEqual([series["values"] for series in result["series"]], [[10, None], [None, 20]])
        self.assertEqual([series["row_indices"] for series in result["series"]], [[[0], []], [[], [0]]])
        self.assertIn("2 observations", result["notice"])

    def test_duplicate_identity_is_not_collapsed_and_invalid_calculation_is_not_zero(self):
        timeline = self.timeline([[{"name": "Alex", "net": 10, "__row_key": "alex"}, {"name": "Alex", "net": 20, "__row_key": "alex"}]])
        with self.assertRaisesRegex(ValidationError, "repeats"):
            build_timeline(timeline, {}, "name")
        timeline = self.timeline([[{"name": "Alex", "net": None, "__invalid_fields": ["net"]}], [], [{"name": "Alex", "net": ""}]], "average")
        result = build_timeline(timeline, {})
        self.assertEqual(result["series"][0]["values"], [None, None, 0])
        self.assertEqual(result["series"][0]["sample_counts"], [0, 0, 1])
        self.assertIn("unavailable", result["series"][0]["reasons"][0])


if __name__ == "__main__":
    unittest.main()
