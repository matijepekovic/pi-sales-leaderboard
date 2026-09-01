"""Built-in Screen templates.

Templates are immutable starting points. A user creates a normal editable Screen
from one of these templates, then chooses Reports, Display Values, presentation
and Theme like any other Screen.
"""
from __future__ import annotations


_TEMPLATES = (
    {
        "key": "whole_office",
        "name": "Whole Office",
        "description": "Rank everyone together on one office-wide leaderboard.",
        "layout": "leaderboard",
        "group_hint": "No grouping is required for the office-wide view.",
    },
    {
        "key": "per_team",
        "name": "Per Team",
        "description": "A leaderboard focused on one team.",
        "layout": "leaderboard",
        "group_hint": "Choose the Display Value that identifies teams, then choose one team value.",
    },
    {
        "key": "team_vs_team",
        "name": "Team vs Team",
        "description": "Compare two teams side by side using the same Report.",
        "layout": "comparison",
        "group_hint": "Choose the Display Value that identifies teams, then choose two team values.",
    },
    {
        "key": "all_teams",
        "name": "All Teams",
        "description": "Show teams as competitive panels from the same Report.",
        "layout": "comparison_grid",
        "group_hint": "Choose the Display Value that identifies teams. Leave team values empty to show every value.",
    },
    {
        "key": "product_close",
        "name": "Product Close",
        "description": "A compact product-performance leaderboard for close-rate competition.",
        "layout": "product",
        "group_hint": "Choose the Display Values you want this Screen to show.",
    },
)


def list_templates():
    return [dict(item) for item in _TEMPLATES]


def get_template(key):
    key = str(key or "").strip()
    for item in _TEMPLATES:
        if item["key"] == key:
            return dict(item)
    return None
