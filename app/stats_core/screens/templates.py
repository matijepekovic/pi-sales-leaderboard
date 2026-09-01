"""Built-in Screen templates.

Templates are immutable starting points. A user creates a normal editable Screen
from one of these templates, then chooses Reports, Filters, presentation and
Theme like any other Screen.
"""
from __future__ import annotations


_TEMPLATES = (
    {
        "key": "whole_office",
        "name": "Whole Office",
        "description": "Rank everyone together on one office-wide leaderboard.",
        "layout": "leaderboard",
        "filter_hint": "Usually no team Filter is needed unless you want to narrow the office view.",
    },
    {
        "key": "per_team",
        "name": "Per Team",
        "description": "A leaderboard focused on one team.",
        "layout": "leaderboard",
        "filter_hint": "Assign the team Filter this Screen should show.",
    },
    {
        "key": "team_vs_team",
        "name": "Team vs Team",
        "description": "Compare two teams side by side using the same Report.",
        "layout": "comparison",
        "filter_hint": "Assign two team Filters. Each Filter is rendered as its own side of the comparison.",
    },
    {
        "key": "all_teams",
        "name": "All Teams",
        "description": "Show every selected team as its own competitive panel.",
        "layout": "comparison_grid",
        "filter_hint": "Assign the team Filters you want included. Each Filter becomes one team panel.",
    },
    {
        "key": "product_close",
        "name": "Product Close",
        "description": "A compact product-performance leaderboard for close-rate competition.",
        "layout": "product",
        "filter_hint": "Assign any Product, Office or Team Filters needed for this Screen.",
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
