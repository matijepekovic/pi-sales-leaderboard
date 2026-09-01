from __future__ import annotations

from stats_core.services.product import PRODUCT_MODE
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
        views = ["whole_office", "team_vs_team", "all_teams", PRODUCT_MODE]
        for team in self.organization.definitions_for_api():
            name = str(team.get("name") or "").strip()
            if name:
                views.append(f"per_team::{name}")
        return views

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
