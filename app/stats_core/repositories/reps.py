from __future__ import annotations

import json

import database

_CACHE_TABLE = "rep_fallback_cache_v108"


class RepRepository:
    def list(self):
        return database.list_reps()

    def raw_list(self):
        with database.connect() as con:
            return [dict(row) for row in con.execute("SELECT * FROM reps").fetchall()]

    def replace(self, rows):
        return database.replace_reps(rows)

    def apply_organization(self, rows):
        return database.apply_team_overlay(rows)

    def ensure_fallback_cache(self):
        with database.connect() as con:
            con.execute(
                f"CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} ("
                "scope TEXT NOT NULL, rep_key TEXT NOT NULL, "
                "rep_name TEXT NOT NULL DEFAULT '', row_json TEXT NOT NULL, "
                "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY(scope, rep_key))"
            )

    def fallback_cache(self, scope):
        self.ensure_fallback_cache()
        with database.connect() as con:
            rows = con.execute(
                f"SELECT rep_key,row_json FROM {_CACHE_TABLE} WHERE scope=?", (scope,)
            ).fetchall()
        result = {}
        for row in rows:
            try:
                value = json.loads(row["row_json"])
            except Exception:
                continue
            if isinstance(value, dict):
                result[str(row["rep_key"])] = value
        return result

    def write_fallback_cache(self, scope, rows):
        self.ensure_fallback_cache()
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
                    (scope, rep_key, rep_name, json.dumps(dict(row), default=str)),
                )

    def scrub_source_organization(self):
        with database.connect() as con:
            cur = con.execute(
                "UPDATE reps SET team='Unassigned', team_lead=NULL "
                "WHERE COALESCE(team,'')<>'Unassigned' OR team_lead IS NOT NULL"
            )
            changed = max(0, int(cur.rowcount or 0))
        if changed:
            database.bump_version()
        return changed
