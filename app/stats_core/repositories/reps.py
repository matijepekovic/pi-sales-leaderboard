from __future__ import annotations

import json

from stats_core.storage import sqlite as database

_CACHE_TABLE = "rep_fallback_cache_v108"
_REP_COLUMNS = sorted({
    "rep_key", "rep_name", "team", "team_lead", "home_branch", "lead_branch",
    "regional", "district", "title", "hire_date", "issued_leads",
    "pitched_leads", "pitched_rate", "sold_leads", "close_rate",
    "gross_split", "pending_split", "net_split", "dpl", "sales_retention",
    "avg_gross_sale", "avg_net_sale", "product", "position_filter",
    "pir_result", "source_updated_at", "raw_json",
})


class RepRepository:
    def __init__(self, meta_repo, organization_repo):
        self.meta = meta_repo
        self.organization = organization_repo

    def list(self):
        return self.organization.apply_overlay(self.raw_list())

    def raw_list(self):
        with database.connect() as con:
            return [dict(row) for row in con.execute("SELECT * FROM reps").fetchall()]

    def replace(self, rows):
        placeholders = ",".join("?" for _ in _REP_COLUMNS)
        sql = f"INSERT INTO reps ({','.join(_REP_COLUMNS)}) VALUES ({placeholders})"
        with database.connect() as con:
            con.execute("DELETE FROM reps")
            for row in rows:
                clean = {key: row.get(key) for key in _REP_COLUMNS}
                if not clean["rep_key"]:
                    clean["rep_key"] = clean["rep_name"]
                if not clean["team"]:
                    clean["team"] = "Unassigned"
                con.execute(sql, tuple(clean[key] for key in _REP_COLUMNS))
                self.organization.ensure_source_team_in_connection(con, clean["team"])
        self.meta.bump("data_version")

    def apply_organization(self, rows):
        return self.organization.apply_overlay(rows)

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
                f"SELECT rep_key,row_json FROM {_CACHE_TABLE} WHERE scope=?",
                (scope,),
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
            self.meta.bump("data_version")
        return changed
