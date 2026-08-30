from __future__ import annotations

FEATURE_ACCESS = {
    "whole_office": True,
    "per_team": True,
    "team_vs_team": True,
    "all_teams": True,
    "product_close": True,
    "temporary_date": True,
    "themes": True,
    "theme_editor": True,
    "controls": True,
    "settings": True,
}


class EntitlementService:
    """Single feature-access boundary.

    Production/test currently grants every existing feature. Account/payment
    policy can replace this implementation later without touching features.
    """

    def can_use(self, feature):
        return bool(FEATURE_ACCESS.get(str(feature or "").strip(), False))

    def snapshot(self):
        return dict(FEATURE_ACCESS)
