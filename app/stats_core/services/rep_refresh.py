"""Rep pull policy + refresh service.

Every rep refresh explicitly goes through this service, where Tableau owns
metrics and local storage owns team organization.
"""
from __future__ import annotations

import json
import time

import database
from sources.tableau import resolve_dates
from stats_core.services.tableau import TableauService

_CACHE_TABLE = "rep_fallback_cache_v108"


class RepRefreshService:
    def __init__(self, repos, tableau=None):
        self.repos = repos
        self.tableau = tableau or TableauService()

    @staticmethod
    def _normalize_row(row):
        clean = dict(row or {})
        clean.pop("id", None)
        clean["team"] = "Unassigned"
        clean["team_lead"] = None
        return clean

    def _scope(self, settings):
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

    def _ensure_cache_table(self):
        with database.connect() as con:
            con.execute(
                f"CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} ("
                "scope TEXT NOT NULL, rep_key TEXT NOT NULL, "
                "rep_name TEXT NOT NULL DEFAULT '', row_json TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY(scope, rep_key))"
            )

    def _raw_stored_rows(self):
        with database.connect() as con:
            return [dict(row) for row in con.execute("SELECT * FROM reps").fetchall()]

    def _cache_rows(self, scope):
        with database.connect() as con:
            rows = con.execute(
                f"SELECT rep_key,row_json FROM {_CACHE_TABLE} WHERE scope=?", (scope,)
            ).fetchall()
        cached = {}
        for row in rows:
            try:
                value = json.loads(row["row_json"])
                if isinstance(value, dict):
                    cached[str(row["rep_key"])] = self._normalize_row(value)
            except Exception:
                continue
        return cached

    def _write_cache(self, scope, rows):
        with database.connect() as con:
            for row in rows:
                rep_key = str(row.get("rep_key") or row.get("rep_name") or "").strip()
                if not rep_key:
                    continue
                rep_name = str(row.get("rep_name") or rep_key).strip()
                con.execute(
                    f"INSERT INTO {_CACHE_TABLE}(scope,rep_key,rep_name,row_json,updated_at) "
                    "VALUES(?,?,?,?,CURRENT_TIMESTAMP) "
                    "ON CONFLICT(scope,rep_key) DO UPDATE SET "
                    "rep_name=excluded.rep_name,row_json=excluded.row_json,updated_at=CURRENT_TIMESTAMP",
                    (scope, rep_key, rep_name, json.dumps(self._normalize_row(row), default=str)),
                )

    def _seed_current_scope(self):
        if str(self.repos.meta.get("v108_cache_seeded", "") or "") == "1":
            return 0
        settings = self.repos.settings.get()
        scope, start, end = self._scope(settings)
        status = str(self.repos.meta.get("source_status", "") or "")
        rows = []
        if status.lower().startswith("tableau") and f"{start} to {end}" in status:
            rows = [self._normalize_row(row) for row in self._raw_stored_rows()]
            self._write_cache(scope, rows)
            self.repos.meta.set("v108_rep_scope", scope)
            self.repos.meta.set("v108_rep_period", f"{start}|{end}")
        if rows:
            self.repos.meta.set("v108_cache_seeded", "1")
        return len(rows)

    def _scrub_source_organization(self):
        with database.connect() as con:
            cur = con.execute(
                "UPDATE reps SET team='Unassigned', team_lead=NULL "
                "WHERE COALESCE(team,'')<>'Unassigned' OR team_lead IS NOT NULL"
            )
            changed = max(0, int(cur.rowcount or 0))
        if changed:
            try:
                database.bump_version()
            except Exception:
                self.repos.meta.bump("data_version")
        return changed

    def prepare(self):
        self._ensure_cache_table()
        return {"seeded": self._seed_current_scope(), "scrubbed": self._scrub_source_organization()}

    def apply_policy(self, settings, fresh_rows):
        if not fresh_rows:
            return fresh_rows
        self._ensure_cache_table()
        scope, start, end = self._scope(settings)
        fresh = [self._normalize_row(row) for row in fresh_rows]
        fresh_keys = {str(row.get("rep_key") or row.get("rep_name") or "").strip() for row in fresh}
        fresh_keys.discard("")
        cached = self._cache_rows(scope)
        retained = [row for key, row in cached.items() if key not in fresh_keys]
        self._write_cache(scope, fresh)
        self.repos.meta.set("v108_rep_scope", scope)
        self.repos.meta.set("v108_rep_period", f"{start}|{end}")
        self.repos.meta.set("v108_retained_reps", json.dumps([
            str(row.get("rep_name") or row.get("rep_key") or "") for row in retained
        ]))
        return fresh + retained

    def pull(self, settings):
        source = self.tableau.source(settings)
        rows = source.fetch()
        return self.apply_policy(settings, rows), source

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
            + (f" — {len(collapsed)} repeated measure(s) counted once: " + ", ".join(collapsed[:6]) if collapsed else "")
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
