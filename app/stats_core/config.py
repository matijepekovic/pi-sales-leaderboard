"""Application settings defaults, feature access, and metric definitions."""
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

DEFAULT_METRICS = {
    "whole_office": [
        "rank", "rep_name", "team", "issued_leads", "pitched_leads",
        "sold_leads", "close_rate", "gross_split", "pending_split",
        "net_split", "dpl"
    ],
    "team_vs_team": [
        "rank", "rep_name",
        "issued_leads", "pitched_leads", "pitched_rate",
        "sold_leads", "close_rate",
        "gross_split", "pending_split", "net_split", "dpl",
        "sales_retention", "avg_gross_sale", "avg_net_sale"
    ],
    "all_teams": [
        "rank", "rep_name", "sold_leads", "close_rate",
        "gross_split", "pending_split", "net_split", "dpl"
    ],
    "per_team": [
        "rank", "rep_name", "issued_leads", "pitched_leads",
        "sold_leads", "close_rate", "gross_split",
        "pending_split", "net_split", "dpl"
    ],
}

DEFAULT_SETTINGS = {
    "active_mode": "whole_office",
    "sort_metric": {
        "whole_office": "net_split",
        "team_vs_team": "net_split",
        "all_teams": "net_split",
        "per_team": "net_split",
    },
    "rank_direction": {
        "whole_office": "desc",
        "team_vs_team": "desc",
        "all_teams": "desc",
        "per_team": "desc",
    },
    "number_font_scale": {
        "whole_office": 100,
        "team_vs_team": 100,
        "all_teams": 100,
        "per_team": 100,
    },
    "visible_metrics": DEFAULT_METRICS,
    "team_vs_team_selected": [],
    "per_team_selected": "",
    "show_team_members_in_vs": True,
    "display_refresh_seconds": 5,
    "source_refresh_seconds": 60,
    "title": "SALES LEADERBOARD",
    "subtitle": "",
    "currency_symbol": "$",
    "theme_config": {"office": {}, "teams": {}, "screens": {}},
    "github_repo": "",
    "github_auto_update": False,
    "product_icons": {},
    "settings_pin_hash": "",
}

# tableau_pat_secret is retained only as a protected migration key for installs
# upgrading from the pre-catalog data model. It is not an application default.
SECRET_SETTING_KEYS = ("tableau_pat_secret", "settings_pin_hash")

METRIC_DEFS = [
    ("rank", "Rank", "system"),
    ("rep_name", "Sales Rep", "text"),
    ("team", "Team", "text"),
    ("home_branch", "Home Branch", "text"),
    ("title", "Title", "text"),
    ("hire_date", "Hire Date", "text"),
    ("issued_leads", "Issued Leads", "number"),
    ("pitched_leads", "Pitched Leads", "number"),
    ("pitched_rate", "Pitched Rate", "percent"),
    ("sold_leads", "Sold Leads", "number"),
    ("close_rate", "Close Rate", "percent"),
    ("gross_split", "Gross Split", "currency"),
    ("pending_split", "Pending Split", "currency"),
    ("net_split", "Net Split", "currency"),
    ("dpl", "DPL", "currency"),
    ("sales_retention", "Sales Retention", "percent"),
    ("avg_gross_sale", "Avg. Gross Sale", "currency"),
    ("avg_net_sale", "Avg. Net Sale", "currency"),
]
