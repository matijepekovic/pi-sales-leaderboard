"""Settings policy and validation."""
from __future__ import annotations

import re

from sources import tableau_configured
from stats_core.config import FEATURE_ACCESS, METRIC_DEFS, SECRET_SETTING_KEYS
from stats_core.errors import ValidationError
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


def clean_source(raw):
    raw = raw if isinstance(raw, dict) else {}
    clean = {}
    for key in (
        "server", "site", "pat_name", "workbook", "sheet",
        "date_start_field", "date_end_field",
    ):
        if isinstance(raw.get(key), str):
            clean[key] = raw[key].strip()[:300]
    if isinstance(raw.get("export"), str):
        mode = raw["export"].strip().lower()
        if mode in tableau_configured.EXPORTS:
            clean["export"] = mode
    if isinstance(raw.get("filters"), list):
        clean["filters"] = [
            {
                "field": str(item.get("field") or "").strip()[:200],
                "value": str(item.get("value") or "").strip()[:200],
            }
            for item in raw["filters"][:10]
            if isinstance(item, dict) and str(item.get("field") or "").strip()
        ]
    if isinstance(raw.get("row_filter"), dict):
        valid = {key for key, _, _ in METRIC_DEFS}
        column = str(raw["row_filter"].get("column") or "").strip()[:200]
        clean["row_filter"] = {
            "column": column if column in valid else "",
            "value": str(raw["row_filter"].get("value") or "").strip()[:200],
        }
    if isinstance(raw.get("mapping"), dict):
        mapping = raw["mapping"]
        metrics = mapping.get("metrics") if isinstance(mapping.get("metrics"), dict) else {}
        valid = {key for key, _, _ in METRIC_DEFS}
        clean["mapping"] = {
            "rep_name": str(mapping.get("rep_name") or "")[:200],
            "home_branch": str(mapping.get("home_branch") or "")[:200],
            "team": str(mapping.get("team") or "")[:200],
            "metrics": {
                str(key): str(value)[:200]
                for key, value in metrics.items()
                if key in valid and str(value or "").strip()
            },
        }
    return clean


class SettingsService:
    def __init__(self, settings_repo, meta_repo):
        self.settings_repo = settings_repo
        self.meta_repo = meta_repo

    def get(self):
        return self.settings_repo.get()

    def public(self, settings=None):
        data = dict(settings if settings is not None else self.get())
        configured = bool(str(data.get("tableau_pat_secret") or "").strip())
        has_pin = bool(str(data.get("settings_pin_hash") or "").strip())
        for key in SECRET_SETTING_KEYS:
            data.pop(key, None)
        data.pop("github_repo", None)
        data["tableau_pat_configured"] = configured
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
        if isinstance(incoming.get("tableau_server"), str):
            value = incoming["tableau_server"].strip().rstrip("/")
            if value and not value.startswith(("http://", "https://")):
                value = "https://" + value
            current["tableau_server"] = value[:300]
        for key in ("tableau_site", "tableau_pat_name", "tableau_view"):
            if isinstance(incoming.get(key), str):
                current[key] = incoming[key].strip()[:200]
        if isinstance(incoming.get("tableau_pat_secret"), str):
            value = incoming["tableau_pat_secret"].strip()
            if value:
                current["tableau_pat_secret"] = value
        if incoming.get("tableau_pat_clear") is True:
            current["tableau_pat_secret"] = ""
        if isinstance(incoming.get("data_office"), str):
            current["data_office"] = incoming["data_office"].strip()[:120]
        date_mode = str(incoming.get("data_date_mode") or "").strip()
        if date_mode in ("current_month", "custom"):
            current["data_date_mode"] = date_mode
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for key in ("data_date_start", "data_date_end"):
            if isinstance(incoming.get(key), str):
                value = incoming[key].strip()
                if value and not date_pattern.match(value):
                    raise ValidationError("Dates must look like YYYY-MM-DD.")
                current[key] = value
        if (
            current.get("data_date_mode") == "custom"
            and current.get("data_date_start")
            and current.get("data_date_end")
            and current["data_date_start"] > current["data_date_end"]
        ):
            raise ValidationError("The start date must be on or before the end date.")
        for key in ("data_date_param_start", "data_date_param_end"):
            if isinstance(incoming.get(key), str):
                current[key] = incoming[key].strip()[:80]
        for key in ("data_include_people", "data_exclude_people"):
            if isinstance(incoming.get(key), list):
                names, seen = [], set()
                for value in incoming[key]:
                    name = str(value).strip()[:120]
                    if name and name.lower() not in seen:
                        seen.add(name.lower())
                        names.append(name)
                current[key] = names[:200]
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
        for key in ("tableau_workbook", "tableau_sheet"):
            if isinstance(incoming.get(key), str):
                current[key] = incoming[key].strip()[:300]
        if isinstance(incoming.get("source_mapping"), dict):
            raw = incoming["source_mapping"]
            metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
            valid = {key for key, _, _ in METRIC_DEFS}
            current["source_mapping"] = {
                "rep_name": str(raw.get("rep_name") or "")[:200],
                "home_branch": str(raw.get("home_branch") or "")[:200],
                "team": str(raw.get("team") or "")[:200],
                "metrics": {
                    str(key): str(value)[:200]
                    for key, value in metrics.items()
                    if key in valid and str(value or "").strip()
                },
            }
        if isinstance(incoming.get("source"), dict):
            current["source"] = clean_source(incoming["source"])
        if isinstance(incoming.get("product_icons"), dict):
            allowed = {"bath", "siding", "windows", "gutters", "roof", "overall"}
            icons = {}
            for card, url in incoming["product_icons"].items():
                card = str(card).strip().lower()
                url = str(url or "").strip()
                if (
                    card in allowed
                    and url.startswith("/api/asset-library/")
                    and ".." not in url
                ):
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
