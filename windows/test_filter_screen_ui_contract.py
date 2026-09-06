#!/usr/bin/env python3
"""Static UI contract for human-manageable Filters and Screen assignment."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / "app" / "templates" / "settings.html"
SCREENS = ROOT / "app" / "static" / "settings" / "screens.js"
DATA = ROOT / "app" / "static" / "settings" / "data.js"


class FilterScreenUiContractTests(unittest.TestCase):
    def test_data_filters_are_owned_by_the_report_editor(self):
        template = SETTINGS.read_text(encoding="utf-8")
        data = DATA.read_text(encoding="utf-8")

        self.assertNotIn("settingsFiltersHost", template)
        self.assertNotIn("/static/settings/filters.js", template)
        self.assertIn("Data Filters", data)
        self.assertIn("Filter the data pulled for this Report", data)
        self.assertIn("data-data-filter-field", data)
        self.assertIn("data-data-filter-value", data)

    def test_screens_do_not_duplicate_data_filter_configuration(self):
        screens = SCREENS.read_text(encoding="utf-8")
        self.assertIn("Live Preview", screens)
        self.assertNotIn("Assign Filters", screens)
        self.assertNotIn("+ Create Filter", screens)
        self.assertNotIn("/api/filters", screens)
        self.assertNotIn("display_filter_mappings", screens)
        self.assertNotIn("filter_values", screens)


if __name__ == "__main__":
    unittest.main()
