"""Explicit normalization/retention policy for rep pulls."""
from __future__ import annotations

import json

from sources.tableau import resolve_dates


class RepPullPolicy:
    def __init__(self, repos, tableau):
        self.repos = repos
        self.tableau = tableau

    @staticmethod
    def normalize(row):
        clean = dict(row or {})
        clean.pop("id", None)
        # Organization is local ownership. Tableau metrics never overwrite it.
        clean["team"] = "Unassigned"
        clean["team_lead"] = None
        return clean

    def scope(self, settings):
        runtime = self.tableau.normalized_settings(settings)
        start, end = resolve_dates(runtime)
        config = runtime["source"]
        signature = {
            "start": start, "end": end,
            "server": config.get("server", ""), "site": config.get("site", ""),
            "pat_name": config.get("pat_name", ""), "workbook": config.get("workbook", ""),
            "sheet": config.get("sheet", ""), "export": config.get("export", ""),
            "filters": config.get("filters", []), "row_filter": config.get("row_filter", {}),
            "mapping": config.get("mapping", {}),
            "date_start_field": config.get("date_start_field", ""),
            "date_end_field": config.get("date_end_field", ""),
            "data_office": runtime.get("data_office", ""),
            "data_include_people": runtime.get("data_include_people", []),
            "data_exclude_people": runtime.get("data_exclude_people", []),
        }
        return json.dumps(signature, sort_keys=True, separators=(",", ":"), default=str), start, end

    def prepare(self):
        self.repos.reps.ensure_fallback_cache()
        return {
            "seeded": self._seed_current_scope(),
            "scrubbed": self.repos.reps.scrub_source_organization(),
        }

    def _seed_current_scope(self):
        if str(self.repos.meta.get("v108_cache_seeded", "") or "") == "1":
            return 0
        settings = self.repos.settings.get()
        scope, start, end = self.scope(settings)
        status = str(self.repos.meta.get("source_status", "") or "")
        rows = []
        if status.lower().startswith("tableau") and f"{start} to {end}" in status:
            rows = [self.normalize(row) for row in self.repos.reps.raw_list()]
            self.repos.reps.write_fallback_cache(scope, rows)
            self.repos.meta.set("v108_rep_scope", scope)
            self.repos.meta.set("v108_rep_period", f"{start}|{end}")
        if rows:
            self.repos.meta.set("v108_cache_seeded", "1")
        return len(rows)

    def apply(self, settings, fresh_rows):
        if not fresh_rows:
            return fresh_rows
        scope, start, end = self.scope(settings)
        fresh = [self.normalize(row) for row in fresh_rows]
        fresh_keys = {
            str(row.get("rep_key") or row.get("rep_name") or "").strip()
            for row in fresh
        }
        fresh_keys.discard("")
        cached = {
            key: self.normalize(value)
            for key, value in self.repos.reps.fallback_cache(scope).items()
        }
        retained = [row for key, row in cached.items() if key not in fresh_keys]
        self.repos.reps.write_fallback_cache(scope, fresh)
        self.repos.meta.set("v108_rep_scope", scope)
        self.repos.meta.set("v108_rep_period", f"{start}|{end}")
        self.repos.meta.set(
            "v108_retained_reps",
            json.dumps([
                str(row.get("rep_name") or row.get("rep_key") or "")
                for row in retained
            ]),
        )
        return fresh + retained
