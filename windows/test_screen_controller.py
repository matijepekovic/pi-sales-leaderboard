#!/usr/bin/env python3
"""Tests for the server-side screen controller.

The rotation used to live in the display's JavaScript, where nothing could
check it. These cover the behaviour that moved: cycling, pairing, sorting, the
idle timeout, and the rule that an explicit request outranks the controls.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

os.environ.setdefault("STATS_DATA_DIR", tempfile.mkdtemp(prefix="stats-controller-"))

from stats_core.bootstrap import create_app  # noqa: E402
from stats_core.services.screen_controller import INACTIVITY_SECONDS, parsed_mode  # noqa: E402


class ScreenControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app("windows", start_background=False)
        cls.runtime = cls.app.extensions["stats_runtime"]
        cls.client = cls.app.test_client()
        cls.client.post("/api/demo/load")
        for name in ("Alpha", "Bravo", "Charlie"):
            cls.runtime.organization.create(name)
        cls.controller = cls.runtime.screen_controller

    def setUp(self):
        self.controller.release()

    # -- cycling ----------------------------------------------------------

    def test_next_and_previous_walk_the_configured_cycle(self):
        views = self.controller.cycle()
        self.assertGreater(len(views), 1)

        first = self.controller.dispatch("next")
        self.assertTrue(first["active"])
        self.assertEqual(first["view"], views[1])

        back = self.controller.dispatch("previous")
        self.assertEqual(back["view"], views[0])

    def test_cycling_wraps_in_both_directions(self):
        views = self.controller.cycle()
        self.controller.release()
        self.assertEqual(self.controller.dispatch("previous")["view"], views[-1])

        self.controller.release()
        for _ in range(len(views)):
            state = self.controller.dispatch("next")
        self.assertEqual(state["view"], views[0])

    def test_per_team_views_are_offered_once_teams_exist(self):
        views = self.controller.cycle()
        self.assertTrue(
            any(view.startswith("per_team::") for view in views),
            views,
        )
        self.assertEqual(parsed_mode("per_team::Alpha"), "per_team")

    # -- pairing ----------------------------------------------------------

    def test_pair_only_moves_on_the_team_vs_team_screen(self):
        state = self.controller.dispatch("next")
        while state["view"] != "team_vs_team":
            state = self.controller.dispatch("next")
        self.assertIsNotNone(state["pair"])

        first_pair = state["pair"]
        second = self.controller.dispatch("pair")
        self.assertNotEqual(second["pair"], first_pair)

        while self.controller.state()["view"] == "team_vs_team":
            state = self.controller.dispatch("next")
        self.assertIsNone(state["pair"])
        self.assertFalse(self.controller.dispatch("pair")["changed"])

    def test_pair_cycles_every_combination_and_returns(self):
        state = self.controller.dispatch("next")
        while state["view"] != "team_vs_team":
            state = self.controller.dispatch("next")
        start = state["pair"]
        total = len(self.controller.pairs())
        self.assertEqual(total, 3)  # Alpha/Bravo, Alpha/Charlie, Bravo/Charlie
        for _ in range(total):
            state = self.controller.dispatch("pair")
        self.assertEqual(state["pair"], start)

    # -- sorting ----------------------------------------------------------

    def test_sort_moves_only_when_the_screen_has_numeric_columns(self):
        state = self.controller.dispatch("sort_next")
        mode = parsed_mode(state["view"])
        metrics = self.controller.sortable_metrics(mode)
        if metrics:
            self.assertIn(state["sort_metric"], metrics)
        else:
            self.assertFalse(state["changed"])

    def test_sort_is_remembered_per_screen(self):
        self.controller.dispatch("sort_next")
        first_view = self.controller.state()["view"]
        first_metric = self.controller.state()["sort_metric"]
        if not first_metric:
            self.skipTest("no numeric columns visible on the opening screen")

        self.controller.dispatch("next")
        self.controller.dispatch("previous")
        self.assertEqual(self.controller.state()["view"], first_view)
        self.assertEqual(self.controller.state()["sort_metric"], first_metric)

    # -- the idle timeout --------------------------------------------------

    def test_the_board_returns_to_the_configured_view_when_left_alone(self):
        configured = self.controller.configured_view()
        moved = self.controller.dispatch("next", now=1000.0)
        self.assertTrue(moved["active"])
        self.assertNotEqual(moved["view"], configured)
        self.assertEqual(moved["expires_in"], INACTIVITY_SECONDS)

        still_held = self.controller.state(now=1000.0 + 299)
        self.assertTrue(still_held["active"])

        expired = self.controller.state(now=1000.0 + 301)
        self.assertFalse(expired["active"])
        self.assertEqual(expired["view"], configured)

    def test_each_action_extends_the_timeout(self):
        self.controller.dispatch("next", now=1000.0)
        self.controller.dispatch("next", now=1200.0)
        self.assertTrue(self.controller.state(now=1450.0)["active"])
        self.assertFalse(self.controller.state(now=1550.0)["active"])

    def test_release_returns_to_the_configured_view_at_once(self):
        self.controller.dispatch("next")
        self.assertTrue(self.controller.state()["active"])
        released = self.controller.release()
        self.assertFalse(released["active"])
        self.assertEqual(released["view"], self.controller.configured_view())

    # -- how the rest of the app sees it -----------------------------------

    def test_the_board_follows_the_controller_when_no_mode_is_asked_for(self):
        moved = self.controller.dispatch("next")
        board = self.client.get("/api/leaderboard").get_json()
        self.assertEqual(board["mode"], parsed_mode(moved["view"]))

    def test_an_explicit_mode_outranks_the_controller(self):
        # The Theme Builder preview pins one team; the macro pad must not drag
        # it somewhere else.
        self.controller.dispatch("next")
        board = self.client.get("/api/leaderboard?mode=all_teams").get_json()
        self.assertEqual(board["mode"], "all_teams")

    def test_state_is_shared_rather_than_per_browser(self):
        self.controller.dispatch("next")
        expected = self.controller.state()["view"]
        other_tab = self.app.test_client()
        seen = other_tab.get("/api/controls/state").get_json()["state"]
        self.assertEqual(seen["view"], expected)
        self.assertEqual(
            other_tab.get("/api/leaderboard").get_json()["mode"],
            parsed_mode(expected),
        )

    def test_unknown_actions_are_refused(self):
        response = self.client.post("/api/controls/action", json={"action": "explode"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.controller.state()["active"])

    def test_the_display_is_told_the_key_map_instead_of_guessing_it(self):
        payload = self.client.get("/api/keyboard-controls").get_json()["keyboard"]
        self.assertEqual(
            set(payload["actions"]),
            {"previous", "next", "pair", "sort_prev", "sort_next"},
        )
        self.assertEqual(set(payload["keys"]), set(payload["actions"]))

        offered = {item["value"]: item["label"] for item in payload["available_views"]}
        self.assertEqual(offered["whole_office"], "Whole Office")
        # The settings page wrote its own screen list and left this one out, so
        # a second script had to inject the checkbox. Both come from here now.
        self.assertEqual(offered["product_close"], "Product Close Rates")
        self.assertIn("per_team::Alpha", offered)

    def test_the_settings_page_no_longer_writes_its_own_screen_list(self):
        controls = (APP / "static" / "settings" / "controls.js").read_text(encoding="utf-8")
        self.assertIn("available_views", controls)
        for hardcoded in ('value:"whole_office"', 'value:"team_vs_team"', 'value:"all_teams"'):
            self.assertNotIn(hardcoded, controls, hardcoded)
        self.assertFalse((APP / "static" / "settings" / "product-rotation.js").exists())
        settings_page = (APP / "templates" / "settings.html").read_text(encoding="utf-8")
        self.assertNotIn("product-rotation.js", settings_page)

    def test_the_display_script_no_longer_owns_rotation_state(self):
        source = (APP / "static" / "display" / "keyboard-controls.js").read_text(encoding="utf-8")
        for gone in ("INACTIVITY_MS", "availableViews", "keyboardLeaderboardUrl", "sortableMetrics"):
            self.assertNotIn(gone, source, gone)
        self.assertIn("/api/controls/action", source)

        core = (APP / "templates" / "display" / "core.html").read_text(encoding="utf-8")
        self.assertNotIn("keyboardLeaderboardUrl", core)


if __name__ == "__main__":
    unittest.main()
