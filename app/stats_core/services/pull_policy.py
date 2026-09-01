"""Explicit normalization/retention policy for rep report pulls."""
from __future__ import annotations

import json


class RepPullPolicy:
    def __init__(self, repos):
        self.repos = repos

    @staticmethod
    def normalize(row):
        clean = dict(row or {})
        clean.pop("id", None)
        # Organization is local ownership. External report metrics never overwrite it.
        clean["team"] = "Unassigned"
        clean["team_lead"] = None
        return clean

    @staticmethod
    def scope(context):
        context = context if isinstance(context, dict) else {}
        scope = str(context.get("id") or "").strip()
        start = str(context.get("start") or "").strip()
        end = str(context.get("end") or "").strip()
        if not scope:
            scope = json.dumps(context, sort_keys=True, separators=(",", ":"), default=str)
        return scope, start, end

    def prepare(self, current_scope=None):
        self.repos.reps.ensure_fallback_cache()
        return {
            "seeded": self._seed_current_scope(current_scope) if current_scope else 0,
            "scrubbed": self.repos.reps.scrub_source_organization(),
        }

    def _seed_current_scope(self, context):
        if str(self.repos.meta.get("v108_cache_seeded", "") or "") == "1":
            return 0
        scope, start, end = self.scope(context)
        status = str(self.repos.meta.get("source_status", "") or "")
        rows = []
        if start and end and f"{start} to {end}" in status:
            rows = [self.normalize(row) for row in self.repos.reps.raw_list()]
            self.repos.reps.write_fallback_cache(scope, rows)
            self.repos.meta.set("v108_rep_scope", scope)
            self.repos.meta.set("v108_rep_period", f"{start}|{end}")
        if rows:
            self.repos.meta.set("v108_cache_seeded", "1")
        return len(rows)

    def apply(self, context, fresh_rows):
        if not fresh_rows:
            return fresh_rows
        scope, start, end = self.scope(context)
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
            json.dumps([str(row.get("rep_name") or row.get("rep_key") or "") for row in retained]),
        )
        return fresh + retained
