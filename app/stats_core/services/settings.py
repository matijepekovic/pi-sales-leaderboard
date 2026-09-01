"""Application settings policy and validation.

External source/report configuration is owned by SourceService/ReportService and
source adapters, not by general application settings.
"""
from __future__ import annotations

from stats_core.config import FEATURE_ACCESS, METRIC_DEFS, SECRET_SETTING_KEYS
from stats_core.services.product import PRODUCT_MODE

CORE_MODES = {
    "whole_office": "Whole Office",
    "team_vs_team": "Team vs Team",
    "all_teams": "All Teams",
    "per_team": "Per Team",
}
NON_DISPLAY_METRICS = {"home_branch", "title", "hire_date"}


def split_active_mode(value):
    value = str(value or "").strip()
    if value.startswith("per_team::"):
        return "per_team", value.split("::", 1)[1].strip()
    return value, ""


class SettingsService:
    def __init__(self, settings_repo, meta_repo):
        self.settings_repo = settings_repo
        self.meta_repo = meta_repo

    def get(self):
        return self.settings_repo.get()

    def public(self, settings=None):
        data = dict(settings if settings is not None else self.get())
        has_pin = bool(str(data.get("settings_pin_hash") or "").strip())
        for key in SECRET_SETTING_KEYS:
            data.pop(key, None)
        data.pop("github_repo", None)
        data["settings_pin_set"] = has_pin
        data["feature_access"] = dict(FEATURE_ACCESS)
        return data

    def bump(self):
        return self.meta_repo.bump("settings_version")

    def update(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        current = self.get()

        active = str(incoming.get("active_mode") or "").strip()
        parsed, team = split_active_mode(active)
        if active and (
            (parsed in CORE_MODES and FEATURE_ACCESS.get(parsed, False))
            or (active == PRODUCT_MODE and FEATURE_ACCESS.get("product_close", False))
        ):
            current["active_mode"] = active
            if parsed == "per_team" and team:
                current["per_team_selected"] = team

        if isinstance(incoming.get("title"), str):
            current["title"] = incoming["title"][:80]
        if isinstance(incoming.get("subtitle"), str):
            current["subtitle"] = incoming["subtitle"][:120]
        current["github_auto_update"] = False

        if isinstance(incoming.get("team_vs_team_selected"), list):
            selected = []
            for value in incoming["team_vs_team_selected"]:
                value = str(value)
                if value and value not in selected:
                    selected.append(value)
            current["team_vs_team_selected"] = selected[:2]
        if isinstance(incoming.get("per_team_selected"), str):
            current["per_team_selected"] = incoming["per_team_selected"][:120]
        current["show_team_members_in_vs"] = True

        valid_keys = {key for key, _, _ in METRIC_DEFS if key not in NON_DISPLAY_METRICS}
        if isinstance(incoming.get("visible_metrics"), dict):
            current.setdefault("visible_metrics", {})
            for mode in CORE_MODES:
                values = incoming["visible_metrics"].get(mode)
                if isinstance(values, list):
                    current["visible_metrics"][mode] = [v for v in values if v in valid_keys]

        if isinstance(incoming.get("sort_metric"), dict):
            numeric_keys = {
                key for key, _, typ in METRIC_DEFS
                if typ in ("number", "percent", "currency")
            }
            current.setdefault("sort_metric", {})
            for mode in CORE_MODES:
                value = incoming["sort_metric"].get(mode)
                if value in numeric_keys:
                    current["sort_metric"][mode] = value

        if isinstance(incoming.get("number_font_scale"), dict):
            current.setdefault("number_font_scale", {})
            for mode in CORE_MODES:
                try:
                    raw = incoming["number_font_scale"].get(mode)
                    if raw is not None:
                        current["number_font_scale"][mode] = min(max(int(raw), 60), 300)
                except Exception:
                    pass

        if isinstance(incoming.get("product_icons"), dict):
            allowed = {"bath", "siding", "windows", "gutters", "roof", "overall"}
            icons = {}
            for card, url in incoming["product_icons"].items():
                card = str(card).strip().lower()
                url = str(url or "").strip()
                if card in allowed and url.startswith("/api/asset-library/") and ".." not in url:
                    icons[card] = url[:300]
            current["product_icons"] = icons

        try:
            refresh = int(incoming.get(
                "display_refresh_seconds", current.get("display_refresh_seconds", 5)
            ))
            current["display_refresh_seconds"] = min(max(refresh, 2), 60)
        except Exception:
            pass

        current["rank_direction"] = {mode: "desc" for mode in CORE_MODES}
        self.settings_repo.save(current)
        self.bump()
        return current
