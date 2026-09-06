#!/usr/bin/env python3
"""Chart geometry must represent values, units, and available samples honestly."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from stats_core.errors import ValidationError
from stats_core.services.widget_charts import build_chart, validate_chart_meaning


class ChartAccuracyTests(unittest.TestCase):
    fields = {
        "name": {"id": "name", "label": "Name", "type": "text"},
        "rate": {"id": "rate", "label": "Close rate", "type": "percent"},
        "other_rate": {"id": "other_rate", "label": "Pitched rate", "type": "percent"},
        "net": {"id": "net", "label": "Net", "type": "number"},
        "cancelled": {"id": "cancelled", "label": "Cancelled", "type": "number"},
    }

    def definition(self, **overrides):
        return {"dimension_field_id": "", "measure_field_ids": ["rate"], "aggregation": "average", **overrides}

    def percentage(self, values):
        return build_chart("pie", self.definition(), [{"rate": value} for value in values], self.fields)

    def test_explicit_date_order_keeps_original_contributing_row_indices(self):
        rows = [{"name": "2026-09-03", "net": 30}, {"name": "2026-09-01", "net": 10},
                {"name": "2026-09-02", "net": 20}, {"name": "2026-09-01", "net": 2}]
        definition = self.definition(dimension_field_id="name", measure_field_ids=["net"], category_order="date")
        for aggregation, expected, indices in [
            ("none", [10, 2, 20, 30], [[1], [3], [2], [0]]),
            ("sum", [12, 20, 30], [[1, 3], [2], [0]]),
        ]:
            chart = build_chart("line", {**definition, "aggregation": aggregation}, rows, self.fields)
            self.assertEqual(chart["series"][0]["values"], expected)
            self.assertEqual(chart["series"][0]["row_indices"], indices)
            self.assertEqual(chart["category_order"], "date")
        self.assertEqual(rows[0]["name"], "2026-09-03", "Ordering a chart must not reorder the data table")

    def test_numeric_order_is_explicit_and_existing_charts_preserve_source_order(self):
        rows = [{"name": "10", "net": 100}, {"name": "2", "net": 20}, {"name": "1", "net": 10}]
        definition = self.definition(dimension_field_id="name", measure_field_ids=["net"], aggregation="none")
        self.assertEqual(build_chart("line", definition, rows, self.fields)["categories"], ["10", "2", "1"])
        chart = build_chart("line", {**definition, "category_order": "number"}, rows, self.fields)
        self.assertEqual(chart["categories"], ["1", "2", "10"])
        self.assertEqual(chart["series"][0]["row_indices"], [[2], [1], [0]])

    def test_ordering_rejects_missing_ambiguous_or_invalid_values(self):
        definition = self.definition(dimension_field_id="name", measure_field_ids=["net"])
        for value, order in [("09/03/2026", "date"), ("Sep", "date"), ("2026-02-30", "date"),
                             (None, "date"), ("", "number"), ("abc", "number")]:
            with self.subTest(value=value, order=order), self.assertRaises(ValidationError):
                build_chart("line", {**definition, "category_order": order}, [{"name": value, "net": 1}], self.fields)
        for invalid in [{"category_order": "alphabetical"}, {"category_order": "date", "dimension_field_id": ""}]:
            with self.assertRaises(ValidationError):
                build_chart("line", {**definition, **invalid}, [], self.fields)

    def test_numeric_order_respects_percentage_field_units(self):
        rows = [{"rate": .2, "net": 20}, {"rate": 10, "net": 10}, {"rate": "5%", "net": 5}]
        chart = build_chart("bar", self.definition(dimension_field_id="rate", measure_field_ids=["net"],
                                                  aggregation="none", category_order="number"), rows, self.fields)
        self.assertEqual(chart["series"][0]["values"], [5, 10, 20])
        self.assertEqual(chart["series"][0]["row_indices"], [[2], [1], [0]])

    def ratio(self, rows, *, kind="pie", **overrides):
        return build_chart(kind, self.definition(aggregation="ratio", measure_field_ids=["net"], denominator_field_id="cancelled", **overrides), rows, self.fields)

    def test_percentage_geometry_retains_rate_instead_of_normalizing_to_a_whole_circle(self):
        for raw, fraction in [(0, 0), (0.143, .143), (14.3, .143), ("14.3%", .143), (1, 1), (100, 1), ("100%", 1)]:
            with self.subTest(raw=raw):
                chart = self.percentage([raw])
                self.assertEqual(chart["pie_mode"], "percentage")
                self.assertEqual(chart["percentage_scale"], "fraction")
                self.assertAlmostEqual(chart["fraction"], fraction)
                self.assertEqual(chart["categories"], ["Close rate"])
                self.assertEqual(chart["value_field_ids"], ["rate"])
                self.assertEqual(chart["series"][0]["sample_counts"], [1])
                self.assertAlmostEqual(chart["series"][0]["values"][0], fraction)
                self.assertAlmostEqual(1 - chart["fraction"], 1 - fraction)

    def test_percentage_rejects_out_of_range_input_without_clamping_or_averaging_it_away(self):
        for values in [[-.143], [-14.3], ["-14.3%"], ["101%"], [101], ["-5%", "105%"]]:
            with self.subTest(values=values), self.assertRaisesRegex(ValidationError, "between 0% and 100%"):
                self.percentage(values)

    def test_absent_rows_stay_unavailable_but_blank_numeric_cells_are_zero(self):
        for values in [[]]:
            with self.subTest(values=values):
                chart = self.percentage(values)
                self.assertIsNone(chart["fraction"])
                self.assertEqual(chart["series"][0]["values"], [None])
                self.assertEqual(chart["series"][0]["sample_counts"], [0])
                self.assertEqual(chart["source_row_count"], len(values))
        for values in [[None], [None, ""], [0, None]]:
            chart = self.percentage(values)
            self.assertEqual(chart["fraction"], 0)
            self.assertEqual(chart["series"][0]["sample_counts"], [len(values)])
            self.assertEqual(chart["source_row_count"], len(values))

    def test_percent_normalization_happens_before_average_and_keeps_sample_context(self):
        chart = self.percentage([.143, 14.3, "14.3%", None])
        self.assertAlmostEqual(chart["fraction"], .143 * 3 / 4)
        self.assertEqual(chart["series"][0]["sample_counts"], [4])
        self.assertEqual(chart["source_row_count"], 4)
        self.assertIn("each row counts equally", chart["aggregation_label"])

    def test_bar_and_line_keep_explicit_values_above_one_hundred_percent(self):
        for kind in ("bar", "line"):
            chart = build_chart(kind, self.definition(dimension_field_id="name"), [
                {"name": "Above", "rate": "143%"}, {"name": "Negative", "rate": "-3%"},
                {"name": "Zero", "rate": 0}, {"name": "Missing", "rate": None}], self.fields)
            self.assertEqual(chart["percentage_scale"], "fraction")
            self.assertEqual(chart["series"][0]["values"], [1.43, -.03, 0, 0])
            self.assertEqual(chart["series"][0]["sample_counts"], [1, 1, 1, 1])
            self.assertNotIn("pie_mode", chart)

    def test_explicit_percent_input_scale_controls_source_values_not_suffixes(self):
        for scale, value, expected in [("fraction", .99, .99), ("fraction", 1.01, 1.01), ("points", 1, .01), ("points", .99, .0099), ("points", "101%", 1.01), ("fraction", "14.3%", .143)]:
            metadata = {**self.fields, "rate": {**self.fields["rate"], "percent_input_scale": scale}}
            with self.subTest(scale=scale, value=value):
                chart = build_chart("bar", self.definition(), [{"rate": value}], metadata)
                self.assertAlmostEqual(chart["series"][0]["values"][0], expected)
                self.assertEqual(chart["percentage_scale"], "fraction")
        metadata = {**self.fields, "rate": {**self.fields["rate"], "percent_input_scale": "fraction"}}
        with self.assertRaisesRegex(ValidationError, "between 0% and 100%"):
            build_chart("pie", self.definition(), [{"rate": 1.01}], metadata)

    def test_ratio_uses_totals_not_the_average_of_individual_rates(self):
        chart = self.ratio([{"net": 1, "cancelled": 2}, {"net": 9, "cancelled": 90}])
        self.assertAlmostEqual(chart["fraction"], 10 / 92)
        self.assertNotAlmostEqual(chart["fraction"], (.5 + .1) / 2)
        self.assertEqual(chart["pie_mode"], "percentage")
        self.assertEqual(chart["aggregation"], "ratio")
        self.assertEqual(chart["aggregation_label"], "Ratio of totals")
        self.assertEqual(chart["percentage_scale"], "fraction")
        self.assertEqual(chart["value_type"], "percent")
        self.assertEqual(chart["numerator_field_id"], "net")
        self.assertEqual(chart["denominator_field_id"], "cancelled")
        self.assertEqual(chart["categories"], ["Net / Cancelled"])
        self.assertEqual(chart["series"][0]["numerators"], [10])
        self.assertEqual(chart["series"][0]["denominators"], [92])
        self.assertEqual(chart["series"][0]["sample_counts"], [2])

    def test_ratio_pairs_rows_and_exposes_zero_and_missing_denominators(self):
        chart = self.ratio([
            {"name": "A", "net": 1, "cancelled": 10}, {"name": "A", "net": 1000, "cancelled": None},
            {"name": "A", "net": None, "cancelled": 1000}, {"name": "A", "net": 0, "cancelled": 10},
            {"name": "B", "net": 0, "cancelled": 10}, {"name": "C", "net": 10, "cancelled": 0},
            {"name": "D", "net": None, "cancelled": None},
        ], kind="bar", dimension_field_id="name")
        self.assertEqual(chart["categories"], ["A", "B", "C", "D"])
        self.assertEqual(chart["series"][0]["label"], "Net / Cancelled")
        self.assertEqual(chart["series"][0]["values"], [1001 / 1020, 0, None, None])
        self.assertEqual(chart["series"][0]["numerators"], [1001, 0, 10, 0])
        self.assertEqual(chart["series"][0]["denominators"], [1020, 10, 0, 0])
        self.assertEqual(chart["series"][0]["sample_counts"], [4, 1, 1, 1])
        self.assertEqual(chart["source_row_count"], 7)
        for rows in ([], [{"net": 1, "cancelled": 0}]):
            self.assertIsNone(self.ratio(rows)["fraction"])
        self.assertEqual(self.ratio([{"net": 0, "cancelled": 2}])["fraction"], 0)
        self.assertEqual(self.ratio([{"net": None, "cancelled": 2}])["fraction"], 0)

    def test_ratio_geometry_checks_result_while_bar_and_line_allow_outside_percentage_bounds(self):
        for numerator, denominator in [(15, 10), (-1, 10)]:
            rows = [{"net": numerator, "cancelled": denominator}]
            with self.subTest(rows=rows), self.assertRaisesRegex(ValidationError, "between 0% and 100%"):
                self.ratio(rows)
            for kind in ("bar", "line"):
                self.assertEqual(self.ratio(rows, kind=kind)["series"][0]["values"], [numerator / denominator])
        self.assertEqual(self.ratio([{"net": 10, "cancelled": 10}])["fraction"], 1)
        with self.assertRaisesRegex(ValidationError, "Composition pie"):
            self.ratio([{"net": 1, "cancelled": 2}], pie_mode="composition")

    def test_ratio_validates_measurement_fields_and_nonfinite_values(self):
        for measures, denominator in [(["rate"], "cancelled"), (["net"], "rate"), (["net"], "missing"), (["net"], "name")]:
            definition = self.definition(aggregation="ratio", measure_field_ids=measures, denominator_field_id=denominator)
            with self.subTest(definition=definition), self.assertRaisesRegex(ValidationError, "numeric numerator and one numeric denominator"):
                validate_chart_meaning("bar", definition, self.fields)
        for row in [{"net": "NaN", "cancelled": 10}, {"net": 1, "cancelled": "Infinity"}]:
            with self.subTest(row=row), self.assertRaisesRegex(ValidationError, "finite numbers"):
                self.ratio([row])
        with self.assertRaisesRegex(ValidationError, "numeric range"):
            self.ratio([{"net": 1e308, "cancelled": 1}, {"net": 1e308, "cancelled": 1}], kind="bar")

    def test_composition_and_count_are_not_treated_as_percentage_gauges(self):
        chart = build_chart("pie", self.definition(measure_field_ids=["net", "cancelled"], aggregation="sum"), [
            {"net": 100, "cancelled": 20}, {"net": None, "cancelled": 0}], self.fields)
        self.assertEqual(chart["pie_mode"], "composition")
        self.assertEqual(chart["series"][0]["values"], [100, 20])
        self.assertEqual(chart["series"][0]["sample_counts"], [2, 2])
        self.assertNotIn("fraction", chart)
        self.assertNotIn("percentage_scale", chart)
        counted = build_chart("pie", self.definition(aggregation="count"), [{"rate": 0}, {"rate": .143}, {"rate": None}], self.fields)
        self.assertEqual(counted["pie_mode"], "composition")
        self.assertEqual(counted["series"][0]["values"], [3])
        self.assertEqual(counted["series"][0]["sample_counts"], [3])
        self.assertNotIn("percentage_scale", counted)
        mixed_counts = build_chart("bar", self.definition(measure_field_ids=["rate", "net"], aggregation="count"), [{"rate": 0, "net": 100}], self.fields)
        self.assertEqual(mixed_counts["series"][0]["values"], [1, 1])

    def test_invalid_percentage_structure_is_rejected_at_definition_validation(self):
        cases = [
            ("pie", self.definition(pie_mode="composition"), "Composition pie"),
            ("pie", self.definition(pie_mode="percentage", aggregation="count"), "Percentage pie needs"),
            ("pie", self.definition(pie_mode="percentage", measure_field_ids=["net"]), "Percentage pie needs"),
        ]
        for kind, definition, message in cases:
            with self.subTest(definition=definition), self.assertRaisesRegex(ValidationError, message):
                validate_chart_meaning(kind, definition, self.fields)
        for kind in ("bar", "line", "pie"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValidationError, "cannot be summed"):
                validate_chart_meaning(kind, self.definition(aggregation="sum"), self.fields)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValidationError, "cannot share one chart scale"):
                validate_chart_meaning(kind, self.definition(measure_field_ids=["rate", "net"]), self.fields)

    def test_individual_percentage_rows_become_correct_separate_circles(self):
        rows = [{"name": "Alex", "rate": .143}, {"name": "Blair", "rate": .25}, {"name": "Casey", "rate": None}]
        chart = build_chart("pie", self.definition(dimension_field_id="name", aggregation="none"), rows, self.fields)
        self.assertEqual(chart["layout"], "separate")
        self.assertEqual([panel["label"] for panel in chart["panels"]], ["Alex", "Blair", "Casey"])
        self.assertEqual([panel["chart"]["fraction"] for panel in chart["panels"]], [.143, .25, 0])
        self.assertEqual([panel["chart"]["series"][0]["row_indices"] for panel in chart["panels"]], [[[0]], [[1]], [[2]]])
        for panel in chart["panels"]:
            self.assertEqual(panel["chart"]["series"][0]["value_format"]["type"], "percent")
            self.assertEqual(panel["chart"]["percentage_scale"], "fraction")

    def test_multiple_percentage_measures_remain_independent_not_parts_of_a_total(self):
        rows = [{"name": "A", "rate": .143, "other_rate": .5}]
        chart = build_chart("pie", self.definition(measure_field_ids=["rate", "other_rate"]), rows, self.fields)
        self.assertEqual(chart["layout"], "separate")
        self.assertEqual([panel["chart"]["fraction"] for panel in chart["panels"]], [.143, .5])
        self.assertEqual([panel["label"] for panel in chart["panels"]], ["Close rate", "Pitched rate"])

    def test_total_ratio_average_of_ratios_and_individuals_do_not_collapse_to_same_calculation(self):
        rows = [{"name": "A", "net": .5, "cancelled": 2}, {"name": "B", "net": .5, "cancelled": 3}]
        totals = self.ratio(rows, ratio_mode="totals")
        averaged = self.ratio(rows, ratio_mode="row_average")
        individual = self.ratio(rows, kind="bar", dimension_field_id="name", ratio_mode="individual")
        self.assertAlmostEqual(totals["fraction"], .2)
        self.assertAlmostEqual(averaged["fraction"], (.25 + 1 / 6) / 2)
        self.assertEqual(individual["series"][0]["values"], [.25, 1 / 6])
        self.assertEqual(averaged["ratio_mode"], "row_average")
        self.assertEqual(averaged["series"][0]["row_indices"], [[0, 1]])
        self.assertEqual(individual["series"][0]["row_indices"], [[0], [1]])
        self.assertNotEqual(totals["aggregation_label"], averaged["aggregation_label"])

    def test_ratio_number_format_does_not_turn_average_net_into_a_percentage(self):
        rows = [{"net": 10550, "cancelled": .5}]
        chart = self.ratio(rows, kind="bar", result_type="number")
        self.assertEqual(chart["value_type"], "number")
        self.assertNotIn("percentage_scale", chart)
        self.assertEqual(chart["series"][0]["values"], [21100])
        self.assertEqual(chart["series"][0]["value_format"]["type"], "number")
        self.assertEqual(chart["series"][0]["value_formats"][0]["type"], "number")
        with self.assertRaisesRegex(ValidationError, "percentage value"):
            self.ratio(rows, result_type="number", pie_mode="percentage")

    def test_each_value_keeps_its_own_calculation_and_format_in_shared_or_separate_layout(self):
        rows = [{"net": 20, "cancelled": 2, "rate": .1}, {"net": 40, "cancelled": 4, "rate": .3}]
        definition = self.definition(measure_field_ids=["net", "cancelled"], aggregation="sum", measure_settings={
            "cancelled": {"aggregation": "average"}})
        chart = build_chart("bar", definition, rows, self.fields)
        series = chart["series"][0]
        self.assertEqual(series["values"], [60, 3])
        self.assertEqual(chart["aggregation"], "mixed")
        self.assertEqual([item["aggregation"] for item in series["value_settings"]], ["sum", "average"])
        self.assertEqual([item["type"] for item in series["value_formats"]], ["number", "number"])
        mixed = self.definition(measure_field_ids=["net", "rate"], aggregation="none", layout="separate", measure_settings={
            "rate": {"aggregation": "average"}})
        panels = build_chart("bar", mixed, rows, self.fields)["panels"]
        self.assertEqual(panels[0]["chart"]["series"][0]["values"], [20, 40])
        self.assertEqual(panels[0]["chart"]["series"][0]["value_format"]["type"], "number")
        self.assertAlmostEqual(panels[1]["chart"]["series"][0]["values"][0], .2)
        self.assertEqual(panels[1]["chart"]["series"][0]["value_format"]["type"], "percent")
        with self.assertRaisesRegex(ValidationError, "share one chart scale"):
            build_chart("bar", {**mixed, "layout": "shared"}, rows, self.fields)

    def test_unavailable_calculations_and_invalid_cells_never_become_blank_zero(self):
        metadata = {**self.fields, "net": {**self.fields["net"], "kind": "calculated"}}
        chart = build_chart("bar", self.definition(measure_field_ids=["net"]), [{"net": 10}, {"net": None}], metadata)
        self.assertEqual(chart["series"][0]["values"], [None])
        self.assertIn("unavailable", chart["series"][0]["reasons"][0])
        chart = build_chart("bar", self.definition(measure_field_ids=["net"]), [{"net": 10}, {"net": None, "__invalid_fields": ["net"]}], self.fields)
        self.assertEqual(chart["series"][0]["values"], [None])
        for mode in ("individual", "row_average"):
            ratio = self.ratio([{"net": 2, "cancelled": 0}], kind="bar", ratio_mode=mode)
            self.assertEqual(ratio["series"][0]["values"], [None])
            self.assertIn("zero", ratio["series"][0]["reasons"][0])
        self.assertEqual(self.ratio([{"net": None, "cancelled": 10}], ratio_mode="row_average")["fraction"], 0)

    def test_zero_category_and_text_value_are_not_mistaken_for_blank(self):
        rows = [{"name": 0, "net": 10}, {"name": "", "net": 20}]
        chart = build_chart("bar", self.definition(dimension_field_id="name", measure_field_ids=["net"], aggregation="none"), rows, self.fields)
        self.assertEqual(chart["categories"], ["0", "(Empty)"])
        chart = build_chart("bar", self.definition(measure_field_ids=["name"], aggregation="count"), rows, self.fields)
        self.assertEqual(chart["series"][0]["values"], [1])

    def test_nonfinite_values_and_negative_compositions_are_explicit_errors(self):
        for value in (float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "1e999"):
            with self.subTest(value=value), self.assertRaisesRegex(ValidationError, "finite numbers"):
                build_chart("bar", self.definition(measure_field_ids=["net"]), [{"net": value}], self.fields)
        with self.assertRaisesRegex(ValidationError, "non-negative"):
            build_chart("pie", self.definition(measure_field_ids=["net"], aggregation="sum"), [{"net": -20}, {"net": 100}], self.fields)
        with self.assertRaisesRegex(ValidationError, "numeric range"):
            build_chart("bar", self.definition(measure_field_ids=["net"], aggregation="sum"), [{"net": 1e308}, {"net": 1e308}], self.fields)

    def test_chart_policy_stays_source_and_storage_independent(self):
        source = (ROOT / "app/stats_core/services/widget_charts.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertEqual(imports, ["__future__", "datetime", "stats_core.errors"])
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue({"repositories", "connect", "execute", "sources", "themes", "screens"}.isdisjoint(attrs))


if __name__ == "__main__":
    unittest.main()
