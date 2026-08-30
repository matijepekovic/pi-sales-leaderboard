#!/usr/bin/env python3
"""The display render chain is a declared order, not a load-order accident.

These are source assertions rather than browser tests so they run anywhere.
The behaviour itself is checked by rendering both trees and diffing the
screenshots; this file guards the property that made that safe -- that no file
extends the board by capturing and reassigning render() any more.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DISPLAY_JS = APP / "static" / "display"
TEMPLATES = APP / "templates" / "display"

STAGE = re.compile(r"Display\.stage\(\s*(\d+)\s*,")


def display_sources():
    yield from sorted(DISPLAY_JS.glob("*.js"))
    yield from sorted(TEMPLATES.glob("*.html"))


class DisplayRuntimeTests(unittest.TestCase):
    def test_nothing_reassigns_render_any_more(self):
        offenders = []
        for path in display_sources():
            text = path.read_text(encoding="utf-8")
            if re.search(r"(?:^|[^.\w])render\s*=\s*function", text, re.MULTILINE):
                offenders.append(path.name)
            if re.search(r"window\.render\s*=", text):
                offenders.append(path.name)
            for captured in ("previousRender", "baseRender"):
                if captured in text:
                    offenders.append(f"{path.name} ({captured})")
        self.assertEqual(offenders, [])

    def test_the_registry_exists_and_the_board_is_the_innermost_stage(self):
        core = (TEMPLATES / "core.html").read_text(encoding="utf-8")
        self.assertIn("const Display = (function(){", core)
        self.assertIn("function renderBoard(data){", core)
        self.assertIn("return Display.dispatch(data);", core)
        # Exactly one caller of render(), in load().
        self.assertEqual(len(re.findall(r"^\s{6}render\(data\);", core, re.MULTILINE)), 1)

    def test_every_stage_order_is_unique(self):
        seen = {}
        for path in display_sources():
            for order in STAGE.findall(path.read_text(encoding="utf-8")):
                order = int(order)
                self.assertNotIn(
                    order, seen,
                    f"{path.name} reuses order {order} (already {seen.get(order)})",
                )
                seen[order] = path.name
        self.assertGreaterEqual(len(seen), 16)

    def test_the_eligibility_filter_stays_innermost(self):
        # It removes reps with no local team and re-totals what is left. Every
        # other stage has to see the filtered rows, so it must run first.
        eligibility = (TEMPLATES / "eligibility.html").read_text(encoding="utf-8")
        orders = [int(o) for o in STAGE.findall(eligibility)]
        self.assertEqual(orders, [0])

        others = []
        for path in display_sources():
            if path.name == "eligibility.html":
                continue
            others.extend(int(o) for o in STAGE.findall(path.read_text(encoding="utf-8")))
        self.assertTrue(all(order > 0 for order in others), sorted(others))

    def test_the_product_screen_stays_outermost(self):
        # In product mode it draws a full-screen overlay and returns without
        # calling next(), so no theme or layout pass runs against a hidden
        # board. That only holds while it is the last stage.
        product = (DISPLAY_JS / "product-tv.js").read_text(encoding="utf-8")
        product_orders = [int(o) for o in STAGE.findall(product)]
        self.assertEqual(len(product_orders), 1)

        highest = max(
            int(o)
            for path in display_sources()
            for o in STAGE.findall(path.read_text(encoding="utf-8"))
        )
        self.assertEqual(product_orders[0], highest)

    def test_the_stack_stays_classic_scripts(self):
        # content, scaleRoot and esc are top-level const in core.html: shared
        # across classic scripts, absent from window. Module scope would turn
        # every use of them into a ReferenceError at runtime only.
        display_page = (APP / "templates" / "display.html").read_text(encoding="utf-8")
        self.assertNotIn('type="module"', display_page)
        for path in DISPLAY_JS.glob("*.js"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("export ", text, path.name)
            self.assertFalse(
                re.search(r"^\s*import\s", text, re.MULTILINE), path.name
            )

    def test_the_settling_passes_are_still_there(self):
        # Each of these runs its decorate step more than once on purpose, to
        # settle against images that have not decoded yet. A single pass looks
        # right on a warm cache and wrong on a cold one.
        for name, delay in (
            ("theme-corners.js", 80),
            ("theme-extras.js", 80),
            ("table-readability.js", 90),
        ):
            text = (DISPLAY_JS / name).read_text(encoding="utf-8")
            self.assertIn("requestAnimationFrame", text, name)
            self.assertRegex(text, rf"setTimeout\(.+,\s*{delay}\s*\)", name)

    def test_number_scale_still_writes_nothing_at_one_hundred_percent(self):
        text = (DISPLAY_JS / "number-scale.js").read_text(encoding="utf-8")
        self.assertIn("if(factor!==1) ensureStyles();", text)
        self.assertIn("if(factor!==1&&typeof fitLeaderboard", text)


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
