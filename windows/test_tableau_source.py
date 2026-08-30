#!/usr/bin/env python3
"""Deterministic contracts for configurable Tableau report exports."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from sources.tableau_configured import ConfiguredTableauSource  # noqa: E402
from sources.tableau_mapped import parse_mapped  # noqa: E402


def source_config(**overrides):
    config = {
        "server": "https://tableau.example",
        "site": "site",
        "pat_name": "token",
        "workbook": "Workbook",
        "sheet": "Sheet",
        "export": "auto",
        "filters": [],
        "date_start_field": "",
        "date_end_field": "",
        "mapping": {},
        "row_filter": {},
    }
    config.update(overrides)
    return config


class CapturingSource(ConfiguredTableauSource):
    def __init__(self, **overrides):
        super().__init__({}, source_config(**overrides))
        self.requests = []

    def _request(self, url, method="GET", token=None, body=None, timeout=60):
        self.requests.append(url)
        if "/crosstab/excel?" in url:
            return 200, b"xlsx"
        return 200, b"rep,value\nAlice,1\n"


class TableauSourceContractTests(unittest.TestCase):
    def test_parameter_names_use_tableau_parameters_namespace(self):
        source = CapturingSource(
            date_start_field="Parameters.Select Start Date",
            date_end_field="Parameters.Select End Date",
            filters=[{"field": "Home Branch", "value": "Olympia"}],
        )
        source._query_csv(
            "https://tableau.example/api/3.22",
            "token",
            "site-id",
            "view-id",
            "2026-08-01",
            "2026-08-31",
            source.filters,
        )
        query = parse_qs(urlsplit(source.requests[-1]).query)
        self.assertEqual(query["vf_Parameters.Select Start Date"], ["2026-08-01"])
        self.assertEqual(query["vf_Parameters.Select End Date"], ["2026-08-31"])
        self.assertEqual(query["vf_Home Branch"], ["Olympia"])
        self.assertEqual(query["maxAge"], ["1"])

    def test_crosstab_uses_the_same_parameter_and_filter_contract(self):
        source = CapturingSource(
            date_start_field="Parameters.Select Start Date",
            date_end_field="Parameters.Select End Date",
            filters=[{"field": "Home Branch", "value": "Olympia"}],
        )
        source._query_crosstab(
            "https://tableau.example/api/3.22",
            "token",
            "site-id",
            "view-id",
            "2026-08-01",
            "2026-08-31",
            source.filters,
        )
        query = parse_qs(urlsplit(source.requests[-1]).query)
        self.assertEqual(query["vf_Parameters.Select Start Date"], ["2026-08-01"])
        self.assertEqual(query["vf_Parameters.Select End Date"], ["2026-08-31"])
        self.assertEqual(query["vf_Home Branch"], ["Olympia"])

    def test_auto_falls_back_to_crosstab_when_csv_is_zero_byte(self):
        class EmptyCsvSource(CapturingSource):
            def _view_id(self, base, token, site_id):
                return "view-id"

            def fetch_csv(self, base, token, site_id, start, end):
                return ""

        source = EmptyCsvSource(export="auto")
        payload, how, csv_error = source.read_export(
            "base", "token", "site", "2026-08-01", "2026-08-31"
        )
        self.assertEqual(payload, b"xlsx")
        self.assertEqual(how, "crosstab")
        self.assertEqual(csv_error, "")
        self.assertEqual(len(source.requests), 1)
        self.assertIn("/crosstab/excel?", source.requests[0])

    def test_explicit_crosstab_never_reads_stitched_csv(self):
        class CrosstabOnlySource(CapturingSource):
            def _view_id(self, base, token, site_id):
                return "view-id"

            def fetch_csv(self, *args, **kwargs):
                raise AssertionError("explicit Crosstab must not request CSV")

        source = CrosstabOnlySource(export="crosstab")
        payload, how, csv_error = source.read_export(
            "base", "token", "site", "2026-08-01", "2026-08-31"
        )
        self.assertEqual(payload, b"xlsx")
        self.assertEqual(how, "crosstab")
        self.assertEqual(csv_error, "")
        self.assertEqual(len(source.requests), 1)
        self.assertIn("/crosstab/excel?", source.requests[0])

    def test_stitched_duplicate_summary_cells_do_not_double_totals(self):
        csv_text = (
            "Sales Rep,Net Split,Close Rate\n"
            "Alice,1000,0.50\n"
            "Alice,1000,0.50\n"
        )
        rows, notes = parse_mapped(
            csv_text,
            {
                "rep_name": "Sales Rep",
                "metrics": {
                    "net_split": "Net Split",
                    "close_rate": "Close Rate",
                },
            },
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["netSplit"], 1000)
        self.assertEqual(rows[0]["closeRate"], 50)
        self.assertIn("net_split", notes["collapsed"])


if __name__ == "__main__":
    unittest.main()
