"""Application settings defaults and metric definitions."""
from __future__ import annotations

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
    "theme_config": {"office": {}, "teams": {}},
    "github_repo": "",
    "github_auto_update": False,
    "tableau_server": "",
    "tableau_site": "",
    "tableau_pat_name": "",
    "tableau_pat_secret": "",
    "tableau_view": "",
    "data_office": "",
    "data_date_mode": "current_month",
    "data_date_start": "",
    "data_date_end": "",
    "data_date_param_start": "Start",
    "data_date_param_end": "End",
    "data_include_people": [],
    "data_exclude_people": [],
    "tableau_workbook": "",
    "tableau_sheet": "",
    "source_mapping": {},
    "source": {},
    "product_icons": {},
    "settings_pin_hash": "",
}

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
