#!/usr/bin/env python3
"""Static UI contract for human-manageable Filters and Screen assignment."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "app" / "templates" / "settings.html"
FILTERS = ROOT / "app" / "static" / "settings" / "filters.js"
SCREENS = ROOT / "app" / "static" / "settings" / "screens.js"
DATA = ROOT / "app" / "static" / "settings" / "data.js"


class FilterScreenUiContractTests(unittest.TestCase):
    def test_filters_are_managed_against_real_pulled_data(self):
        template = SETTINGS.read_text(encoding="utf-8")
        filters = FILTERS.read_text(encoding="utf-8")
        data = DATA.read_text(encoding="utf-8")

        self.assertIn("settingsFiltersHost", template)
        self.assertIn("/static/settings/filters.js", template)
        self.assertIn("/api/data/reports/", filters)
        self.assertIn("/inspect", filters)
        self.assertIn("sample_values", filters)
        self.assertIn("Pulled Report Data", filters)
        self.assertIn("Test Filter", filters)
        self.assertIn("Data Filters", data)
        self.assertNotIn("Filter Set", filters)
        self.assertNotIn("filter set", filters.lower())

    def test_screens_select_filters_without_owning_filter_rules(self):
        screens = SCREENS.read_text(encoding="utf-8")
        self.assertIn("Assign Filters", screens)
        self.assertIn("+ Create Filter", screens)
        self.assertIn("filter_ids", screens)
        self.assertIn("Live Preview", screens)
        self.assertNotIn("display_filter_mappings", screens)
        self.assertNotIn("filter_values", screens)


if __name__ == "__main__":
    unittest.main()
