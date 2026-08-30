"""One rep refresh path for manual and scheduled Tableau pulls."""
from __future__ import annotations

import time

from sources.tableau import resolve_dates


class RepRefreshService:
    def __init__(self, repos, tableau, pull_policy):
        self.repos = repos
        self.tableau = tableau
        self.pull_policy = pull_policy

    def prepare(self):
        return self.pull_policy.prepare()

    def pull(self, settings):
        source = self.tableau.source(settings)
        rows = source.fetch()
        return self.pull_policy.apply(settings, rows), source

    def refresh(self, settings=None):
        settings = settings or self.repos.settings.get()
        rows, source = self.pull(settings)
        if not rows:
            self.repos.meta.set("source_status", "Tableau returned no matching people")
            return {
                "ok": False,
                "error": "Tableau returned no people for this selection. Check the office name and date range.",
                "total_rows": getattr(source, "last_total_rows", 0),
                "offices": getattr(source, "last_offices", []),
            }
        self.repos.reps.replace(rows)
        runtime = self.tableau.normalized_settings(settings)
        start, end = resolve_dates(runtime)
        collapsed = (getattr(source, "last_notes", {}) or {}).get("collapsed") or []
        status = (
            f"Tableau — {len(rows)} people, {start} to {end}"
            + (f", office {runtime.get('data_office')}" if runtime.get("data_office") else ", all offices")
            + (
                f" — {len(collapsed)} repeated measure(s) counted once: " + ", ".join(collapsed[:6])
                if collapsed else ""
            )
        )
        self.repos.meta.set("source_status", status)
        self.repos.meta.set("last_source_refresh", time.strftime("%Y-%m-%d %H:%M:%S"))
        self.repos.meta.bump("data_version")
        return {
            "ok": True, "rows": len(rows),
            "total_rows": getattr(source, "last_total_rows", 0),
            "offices": getattr(source, "last_offices", []),
            "start": start, "end": end, "message": status,
        }
