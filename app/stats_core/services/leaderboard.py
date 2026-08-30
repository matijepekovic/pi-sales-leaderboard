"""Leaderboard calculations shared by registered screens."""
from __future__ import annotations

from stats_core.config import METRIC_DEFS
from stats_core.services.settings import CORE_MODES, NON_DISPLAY_METRICS

SUM_FIELDS = {
    "issued_leads", "pitched_leads", "sold_leads",
    "gross_split", "pending_split", "net_split",
}


class LeaderboardService:
    def __init__(self, repos, organization, snapshots):
        self.repos = repos
        self.organization = organization
        self.snapshots = snapshots

    @staticmethod
    def numeric(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    @staticmethod
    def safe_rate(numerator, denominator, multiplier=100):
        return (numerator / denominator * multiplier) if denominator else 0

    def sort_rows(self, rows, metric, direction="desc"):
        reverse = direction != "asc"
        if metric in ("rep_name", "team", "home_branch", "title", "hire_date"):
            return sorted(
                rows, key=lambda row: str(row.get(metric) or "").lower(), reverse=reverse
            )
        return sorted(rows, key=lambda row: self.numeric(row.get(metric)), reverse=reverse)

    def aggregate_team(self, team_name, rows, team_definition=None):
        total = {
            "team": team_name,
            "team_id": (team_definition or {}).get("team_id"),
            "rep_count": len(rows),
            "leads": (team_definition or {}).get("leads", []),
            "logo_url": (team_definition or {}).get("logo_url"),
        }
        for field in SUM_FIELDS:
            total[field] = sum(self.numeric(row.get(field)) for row in rows)
        total["pitched_rate"] = self.safe_rate(total["pitched_leads"], total["issued_leads"])
        total["close_rate"] = self.safe_rate(total["sold_leads"], total["issued_leads"])
        total["dpl"] = total["net_split"] / total["issued_leads"] if total["issued_leads"] else 0
        total["sales_retention"] = self.safe_rate(total["net_split"], total["gross_split"])
        total["avg_gross_sale"] = total["gross_split"] / total["sold_leads"] if total["sold_leads"] else 0
        total["avg_net_sale"] = total["net_split"] / total["sold_leads"] if total["sold_leads"] else 0
        return total

    @staticmethod
    def metric_type_map():
        return {key: typ for key, _label, typ in METRIC_DEFS}

    def context(self, mode, parsed_team="", sort_metric_override=None, settings=None):
        settings = settings or self.repos.settings.get()
        mode = mode if mode in CORE_MODES else "whole_office"
        rows, snapshot_kind = self.snapshots.rows()
        numeric_sort_metrics = {
            key for key, _label, typ in METRIC_DEFS
            if typ in ("number", "percent", "currency") and key != "rank"
        }
        metric = settings.get("sort_metric", {}).get(mode, "net_split")
        if sort_metric_override in numeric_sort_metrics:
            metric = sort_metric_override
        visible = [
            key for key in settings.get("visible_metrics", {}).get(mode, [])
            if key not in NON_DISPLAY_METRICS
        ]
        team_defs = self.organization.definitions_for_api()
        team_by_name = {team["name"]: team for team in team_defs}
        grouped = {team["name"]: [] for team in team_defs}
        for row in rows:
            grouped.setdefault(row.get("team") or "Unassigned", []).append(row)
        return {
            "leaderboard": self,
            "mode": mode,
            "parsed_team": parsed_team,
            "settings": settings,
            "rows": rows,
            "snapshot": snapshot_kind,
            "metric": metric,
            "visible": visible,
            "team_defs": team_defs,
            "team_by_name": team_by_name,
            "grouped": grouped,
            "metric_types": self.metric_type_map(),
        }
