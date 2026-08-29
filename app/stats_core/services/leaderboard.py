"""Leaderboard calculations and screen payloads."""
from __future__ import annotations

from database import METRIC_DEFS
from stats_core.services.product import PRODUCT_MODE
from stats_core.services.settings import CORE_MODES, NON_DISPLAY_METRICS, split_active_mode

SUM_FIELDS = {
    "issued_leads", "pitched_leads", "sold_leads",
    "gross_split", "pending_split", "net_split",
}


def numeric(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def safe_rate(numerator, denominator, multiplier=100):
    return (numerator / denominator * multiplier) if denominator else 0


def sort_rows(rows, metric, direction="desc"):
    reverse = direction != "asc"
    if metric in ("rep_name", "team", "home_branch", "title", "hire_date"):
        return sorted(rows, key=lambda row: str(row.get(metric) or "").lower(), reverse=reverse)
    return sorted(rows, key=lambda row: numeric(row.get(metric)), reverse=reverse)


def aggregate_team(team_name, rows, team_definition=None):
    total = {
        "team": team_name,
        "team_id": (team_definition or {}).get("team_id"),
        "rep_count": len(rows),
        "leads": (team_definition or {}).get("leads", []),
        "logo_url": (team_definition or {}).get("logo_url"),
    }
    for field in SUM_FIELDS:
        total[field] = sum(numeric(row.get(field)) for row in rows)
    total["pitched_rate"] = safe_rate(total["pitched_leads"], total["issued_leads"])
    total["close_rate"] = safe_rate(total["sold_leads"], total["issued_leads"])
    total["dpl"] = total["net_split"] / total["issued_leads"] if total["issued_leads"] else 0
    total["sales_retention"] = safe_rate(total["net_split"], total["gross_split"])
    total["avg_gross_sale"] = total["gross_split"] / total["sold_leads"] if total["sold_leads"] else 0
    total["avg_net_sale"] = total["net_split"] / total["sold_leads"] if total["sold_leads"] else 0
    return total


class LeaderboardService:
    def __init__(self, repos, organization, snapshots, products):
        self.repos = repos
        self.organization = organization
        self.snapshots = snapshots
        self.products = products

    @staticmethod
    def metric_type_map():
        return {key: typ for key, _label, typ in METRIC_DEFS}

    def payload(self, mode=None, sort_metric_override=None, team_vs_team_override=None):
        settings = self.repos.settings.get()
        raw_mode = mode if mode is not None else settings.get("active_mode", "whole_office")
        raw_mode = str(raw_mode or "").strip()
        if raw_mode == PRODUCT_MODE:
            return self.products.mode_payload()

        parsed_mode, parsed_team = split_active_mode(raw_mode)
        mode = parsed_mode if parsed_mode in CORE_MODES else "whole_office"
        rows, snapshot_kind = self.snapshots.rows()
        numeric_sort_metrics = {
            key for key, _label, typ in METRIC_DEFS
            if typ in ("number", "percent", "currency") and key != "rank"
        }
        metric = settings.get("sort_metric", {}).get(mode, "net_split")
        if sort_metric_override in numeric_sort_metrics:
            metric = sort_metric_override
        direction = "desc"
        visible = [
            key for key in settings.get("visible_metrics", {}).get(mode, [])
            if key not in NON_DISPLAY_METRICS
        ]
        team_defs = self.organization.definitions_for_api()
        team_by_name = {team["name"]: team for team in team_defs}

        if mode == "whole_office":
            return {
                "mode": mode,
                "mode_label": CORE_MODES[mode],
                "metrics": visible,
                "rows": sort_rows(rows, metric, direction),
                "teams": [],
                "office_summary": aggregate_team("WHOLE OFFICE", rows, None),
                "snapshot": snapshot_kind,
            }

        grouped = {team["name"]: [] for team in team_defs}
        for row in rows:
            grouped.setdefault(row.get("team") or "Unassigned", []).append(row)

        if mode == "team_vs_team":
            requested_pair = team_vs_team_override if isinstance(team_vs_team_override, (list, tuple)) else None
            selected = list(dict.fromkeys(requested_pair or settings.get("team_vs_team_selected") or []))[:2]
            if not selected:
                selected = [team["name"] for team in team_defs[:2]]
            teams = []
            for team_name in selected:
                members = grouped.get(team_name, [])
                definition = team_by_name.get(team_name)
                if not members and not definition:
                    continue
                teams.append({
                    "summary": aggregate_team(team_name, members, definition),
                    "members": sort_rows(members, metric, direction),
                })
            teams.sort(key=lambda item: numeric(item["summary"].get(metric)), reverse=True)
            type_map = self.metric_type_map()
            selected_numeric = [
                key for key in visible if type_map.get(key) in {"number", "percent", "currency"}
            ]
            return {
                "mode": mode,
                "mode_label": CORE_MODES[mode],
                "metrics": visible,
                "rows": [],
                "teams": teams[:2],
                "show_members": True,
                "team_total_metrics": selected_numeric,
                "rep_stat_metrics": selected_numeric,
                "team_rank_metric": metric,
                "team_rank_direction": direction,
                "snapshot": snapshot_kind,
            }

        if mode == "per_team":
            selected_team = parsed_team or settings.get("per_team_selected") or ""
            if not selected_team and team_defs:
                selected_team = team_defs[0]["name"]
            members = grouped.get(selected_team, [])
            definition = team_by_name.get(selected_team)
            return {
                "mode": mode,
                "mode_label": f"{CORE_MODES[mode]} — {selected_team}" if selected_team else CORE_MODES[mode],
                "metrics": visible,
                "rows": sort_rows(members, metric, direction),
                "teams": [],
                "selected_team": selected_team,
                "team_summary": aggregate_team(selected_team, members, definition) if selected_team else None,
                "snapshot": snapshot_kind,
            }

        teams = []
        for team_name, members in grouped.items():
            definition = team_by_name.get(team_name)
            if not members and not definition:
                continue
            teams.append({
                "summary": aggregate_team(team_name, members, definition),
                "members": sort_rows(members, metric, direction),
            })
        teams.sort(key=lambda item: numeric(item["summary"].get(metric)), reverse=True)
        return {
            "mode": mode,
            "mode_label": CORE_MODES[mode],
            "metrics": visible,
            "rows": [],
            "teams": teams,
            "snapshot": snapshot_kind,
        }
