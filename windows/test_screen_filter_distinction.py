#!/usr/bin/env python3
"""Static architecture guard for Data Filters versus Display Filters."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class ScreenFilterDistinctionTests(unittest.TestCase):
    def test_filter_owner_has_no_source_or_report_field_contract(self):
        service = (APP / "stats_core" / "services" / "filters.py").read_text(encoding="utf-8")
        repository = (APP / "stats_core" / "repositories" / "filters.py").read_text(encoding="utf-8")
        for text in (service, repository):
            self.assertNotIn("source_config", text)
            self.assertNotIn("workbook", text.lower())
            self.assertNotIn("tableau", text.lower())
        screens = (APP / "stats_core" / "services" / "screens.py").read_text(encoding="utf-8")
        self.assertIn("display_filter_mappings", screens)
        self.assertNotIn("source_config", screens)


if __name__ == "__main__":
    unittest.main()
