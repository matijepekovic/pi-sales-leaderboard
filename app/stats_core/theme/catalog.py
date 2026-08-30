from __future__ import annotations

ASSETS = {
    "background": {"label": "Background"},
    "hero": {"label": "Hero / Header Art"},
    "logo_small": {"label": "Logo Small"},
    "row": {"label": "Leaderboard Row"},
    "champion": {"label": "Champion Row"},
    "medallion": {"label": "Champion Medallion"},
    "corner_tl": {"label": "Top Left Corner", "adjustable": True},
    "corner_tr": {"label": "Top Right Corner", "adjustable": True},
    "corner_bl": {"label": "Bottom Left Corner", "adjustable": True},
    "corner_br": {"label": "Bottom Right Corner", "adjustable": True},
    "totals_mark": {"label": "Totals Mark"},
}

CORNER_ASSET_KEYS = ("corner_tl", "corner_tr", "corner_bl", "corner_br")
CORNER_SHEET_KEY = "corner_sheet"
PRODUCT_ICON_KEYS = {
    "product_bath", "product_siding", "product_windows",
    "product_gutters", "product_roof", "product_overall",
}
LIBRARY_KEYS = set(ASSETS) | {CORNER_SHEET_KEY, "team_logo"} | PRODUCT_ICON_KEYS
ALLOWED_BASES = {"starter", "classic", "undisputed"}
DEFAULT_CORNER_SETTINGS = {"size": 100.0, "crop_x": 0.0, "crop_y": 0.0}

CLASSIC_COLORS = {
    "primary": "#d8b34a",
    "primary_bright": "#e6c760",
    "primary_dark": "#705b20",
    "secondary": "#303030",
    "background": "#080808",
    "panel": "#111111",
    "text": "#f5f5f5",
    "muted": "#9c9c9c",
    "champion_text": "#ffffff",
}
STARTER_COLORS = dict(CLASSIC_COLORS)
UNDISPUTED_COLORS = {
    "primary": "#c58a2a",
    "primary_bright": "#e1ad48",
    "primary_dark": "#6f4612",
    "secondary": "#8b130c",
    "background": "#070706",
    "panel": "#11100d",
    "text": "#e8d6ad",
    "muted": "#a3946f",
    "champion_text": "#f7e7ae",
}

STARTER_FILES = {
    "background": "background.svg",
    "hero": "hero.svg",
    "logo_small": "hero.svg",
    "row": "row.svg",
    "champion": "champion.svg",
    "medallion": "medallion.svg",
    "corner_tl": "corner-tl.svg",
    "corner_tr": "corner-tr.svg",
    "corner_bl": "corner-bl.svg",
    "corner_br": "corner-br.svg",
    "totals_mark": "totals-mark.svg",
}
