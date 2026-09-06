"""Screen asset geometry is independent of Group branding and Theme storage."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

from stats_core.errors import ValidationError
from stats_core.screens.composition import clean_assets


class ScreenAssetPlacementTests(unittest.TestCase):
    allowed = {"hero", "logo_small", "corner_tl", "background"}

    def test_absent_and_empty_have_distinct_meanings(self):
        self.assertIsNone(clean_assets(None, self.allowed))
        self.assertEqual(clean_assets([], self.allowed), [])

    def test_repeated_slot_placements_have_independent_identity_and_fit(self):
        original = [
            {"id": "left-logo", "key": "logo_small", "x": 0, "y": 5, "width": 10, "height": 20},
            {"id": "right-logo", "key": "logo_small", "x": 90, "y": 5, "width": 10, "height": 20, "fit": "cover"},
        ]
        before = copy.deepcopy(original)
        result = clean_assets(original, self.allowed)
        self.assertEqual(original, before)
        self.assertEqual([item["fit"] for item in result], ["contain", "cover"])
        self.assertEqual(result[1]["x"] + result[1]["width"], 100)

    def test_unknown_slots_background_and_content_values_are_rejected(self):
        for item in ({"key": "unknown"}, {"key": "background"}, {"key": "hero", "url": "/art.png"}, {"key": "hero", "fit": "stretch"}):
            with self.subTest(item=item), self.assertRaises(ValidationError):
                clean_assets([item], self.allowed)

    def test_duplicate_ids_overflow_and_invalid_numbers_are_rejected(self):
        cases = [
            [{"id": "a", "key": "hero"}, {"id": "a", "key": "logo_small"}],
            [{"key": "hero", "x": 90, "width": 20}],
            [{"key": "hero", "width": float("nan")}],
            [{"key": "hero", "x": True}],
            [{"key": "hero"}] * 51,
        ]
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                clean_assets(raw, self.allowed)

    def test_missing_ids_are_generated_once_and_round_trip(self):
        saved = clean_assets([{"key": "hero"}, {"key": "hero"}], self.allowed)
        self.assertNotEqual(saved[0]["id"], saved[1]["id"])
        self.assertEqual(clean_assets([{"key": "hero"}, {"key": "hero"}], self.allowed), saved)
        self.assertEqual(clean_assets(saved, self.allowed), saved)


if __name__ == "__main__":
    unittest.main()
