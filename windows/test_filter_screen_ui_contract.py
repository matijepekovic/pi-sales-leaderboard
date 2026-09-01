#!/usr/bin/env python3
"""Static UI contract for the human-first Screen Builder."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "app" / "static" / "settings" / "data-screen-display.js"


class FilterScreenUiContractTests(unittest.TestCase):
    def test_screen_builder_uses_real_pulled_data_for_filter_matching(self):
        text = WORKSPACE.read_text(encoding="utf-8")
        for required in (
            "1. Choose Data",
            "2. Display Data — Match Filters",
            "3. Create Table",
            "4. Theme",
            "/inspect",
            "sample_values",
            "Create & Match",
            "Data Filters",
            "Display Filters",
        ):
            self.assertIn(required, text)
        self.assertNotIn("Filter Set", text)
        self.assertNotIn("filter set", text.lower())


if __name__ == "__main__":
    unittest.main()
