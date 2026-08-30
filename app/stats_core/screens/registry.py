from __future__ import annotations

from stats_core.services.product import PRODUCT_LABEL, PRODUCT_MODE
from stats_core.services.settings import CORE_MODES, split_active_mode
from .all_teams import AllTeamsScreen
from .per_team import PerTeamScreen
from .product_close import ProductCloseScreen
from .team_vs_team import TeamVsTeamScreen
from .whole_office import WholeOfficeScreen


class ScreenRegistry:
    """Central registry for every display mode.

    Screen implementations render payloads; controls and settings ask this
    registry what screens exist instead of mutating screen lists themselves.
    """

    def __init__(self, leaderboard, products, organization):
        self.leaderboard = leaderboard
        self.products = products
        self.organization = organization
        self._screens = {}
        for screen in (
            WholeOfficeScreen(), PerTeamScreen(), TeamVsTeamScreen(),
            AllTeamsScreen(), ProductCloseScreen(products),
        ):
            self.register(screen)

    def register(self, screen):
        key = str(screen.key)
        if key in self._screens:
            raise ValueError(f"Screen already registered: {key}")
        self._screens[key] = screen

    def screen(self, key):
        return self._screens[str(key)]

    def modes(self):
        return [{"key": key, "label": label} for key, label in CORE_MODES.items()]

    def cycle_views(self):
        return [option["value"] for option in self.cycle_view_options()]

    def cycle_view_options(self):
        """The rotation, with labels, so no control surface writes its own list.

        The settings page used to hardcode three screens here and needed a
        separate script to inject the fourth. Both ask this instead.
        """
        options = [
            {"value": "whole_office", "label": CORE_MODES["whole_office"]},
            {"value": "team_vs_team", "label": CORE_MODES["team_vs_team"]},
            {"value": "all_teams", "label": CORE_MODES["all_teams"]},
            {"value": PRODUCT_MODE, "label": PRODUCT_LABEL},
        ]
        for team in self.organization.definitions_for_api():
            name = str(team.get("name") or "").strip()
            if name:
                options.append({"value": f"per_team::{name}", "label": f"Team — {name}"})
        return options

    def render(self, raw_mode=None, sort_metric_override=None, team_pair=None):
        settings = self.leaderboard.repos.settings.get()
        raw = str(raw_mode if raw_mode is not None else settings.get("active_mode", "whole_office") or "").strip()
        if raw == PRODUCT_MODE:
            return self.screen(PRODUCT_MODE).render()
        mode, parsed_team = split_active_mode(raw)
        if mode not in CORE_MODES:
            mode = "whole_office"
            parsed_team = ""
        context = self.leaderboard.context(
            mode, parsed_team=parsed_team, sort_metric_override=sort_metric_override,
            settings=settings,
        )
        return self.screen(mode).render(context, team_pair=team_pair)
