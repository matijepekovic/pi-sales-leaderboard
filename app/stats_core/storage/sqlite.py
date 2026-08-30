import json
import sqlite3
import threading
from contextlib import contextmanager

from stats_core.config import DEFAULT_METRICS, DEFAULT_SETTINGS
from stats_core.paths import prepare_data_dir

DATA_DIR = prepare_data_dir()
DB_PATH = DATA_DIR / "leaderboard.db"
_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS reps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rep_key TEXT UNIQUE NOT NULL,
    rep_name TEXT NOT NULL,
    team TEXT NOT NULL DEFAULT 'Unassigned',
    team_lead TEXT,
    home_branch TEXT,
    lead_branch TEXT,
    regional TEXT,
    district TEXT,
    title TEXT,
    hire_date TEXT,
    issued_leads REAL DEFAULT 0,
    pitched_leads REAL DEFAULT 0,
    pitched_rate REAL DEFAULT 0,
    sold_leads REAL DEFAULT 0,
    close_rate REAL DEFAULT 0,
    gross_split REAL DEFAULT 0,
    pending_split REAL DEFAULT 0,
    net_split REAL DEFAULT 0,
    dpl REAL DEFAULT 0,
    sales_retention REAL DEFAULT 0,
    avg_gross_sale REAL DEFAULT 0,
    avg_net_sale REAL DEFAULT 0,
    product TEXT,
    position_filter TEXT,
    pir_result TEXT,
    source_updated_at TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS team_overrides (
    rep_key TEXT PRIMARY KEY,
    override_team TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    logo_path TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_leads (
    lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    lead_name TEXT NOT NULL,
    lead_role TEXT NOT NULL DEFAULT 'Sales Manager',
    FOREIGN KEY(team_id) REFERENCES teams(team_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rep_team_assignments (
    rep_key TEXT PRIMARY KEY,
    team_id INTEGER NOT NULL,
    FOREIGN KEY(team_id) REFERENCES teams(team_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS deleted_teams (
    name TEXT PRIMARY KEY COLLATE NOCASE,
    deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_close (
    product TEXT PRIMARY KEY,
    close_rate REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        con = sqlite3.connect(DB_PATH, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()


def _ensure_team_in_connection(con, name):
    name = str(name or "").strip()
    if not name or name.lower() == "unassigned":
        return None
    con.execute(
        "INSERT INTO teams(name,active) VALUES(?,1) "
        "ON CONFLICT(name) DO UPDATE SET active=1",
        (name,),
    )
    row = con.execute(
        "SELECT team_id FROM teams WHERE name=? COLLATE NOCASE",
        (name,),
    ).fetchone()
    return int(row["team_id"]) if row else None


def _sync_source_teams_in_connection(con):
    rows = con.execute(
        "SELECT DISTINCT team FROM reps WHERE team IS NOT NULL AND TRIM(team)<>''"
    ).fetchall()
    for row in rows:
        _ensure_team_in_connection(con, row["team"])


def _migrate_legacy_overrides_in_connection(con):
    legacy = con.execute(
        "SELECT rep_key, override_team FROM team_overrides "
        "WHERE override_team IS NOT NULL AND TRIM(override_team)<>''"
    ).fetchall()
    for row in legacy:
        team_id = _ensure_team_in_connection(con, row["override_team"])
        if team_id:
            con.execute(
                "INSERT OR IGNORE INTO rep_team_assignments(rep_key,team_id) VALUES(?,?)",
                (row["rep_key"], team_id),
            )


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)

        team_cols = {
            row["name"] for row in con.execute("PRAGMA table_info(teams)").fetchall()
        }
        if "logo_path" not in team_cols:
            con.execute("ALTER TABLE teams ADD COLUMN logo_path TEXT")

        row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
        if not row:
            con.execute(
                "INSERT INTO settings(key,value) VALUES('config',?)",
                (json.dumps(DEFAULT_SETTINGS),),
            )

        for key, default in (
            ("data_version", "0"),
            ("settings_version", "0"),
            ("organization_version", "0"),
            ("tv_refresh_version", "0"),
            ("app_restart_version", "0"),
            ("github_update_status", "Not configured"),
            ("github_last_check", ""),
            ("github_remote_version", ""),
        ):
            if not con.execute("SELECT 1 FROM meta WHERE key=?", (key,)).fetchone():
                con.execute("INSERT INTO meta(key,value) VALUES(?,?)", (key, default))

        if not con.execute(
            "SELECT 1 FROM meta WHERE key='v99_demo_printer_removed'"
        ).fetchone():
            row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
            if row:
                try:
                    config = json.loads(row["value"])
                    config.pop("printer_host", None)
                    config.pop("printer_port", None)
                    con.execute(
                        "UPDATE settings SET value=? WHERE key='config'",
                        (json.dumps(config),),
                    )
                except Exception:
                    pass

            status_row = con.execute(
                "SELECT value FROM meta WHERE key='source_status'"
            ).fetchone()
            status = str(status_row["value"] if status_row else "").strip().lower()
            if status.startswith("sample data"):
                con.execute("DELETE FROM reps")
                version_row = con.execute(
                    "SELECT value FROM meta WHERE key='data_version'"
                ).fetchone()
                try:
                    next_version = int(version_row["value"] if version_row else 0) + 1
                except Exception:
                    next_version = 1
                con.execute(
                    "INSERT INTO meta(key,value) VALUES('data_version',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(next_version),),
                )
                con.execute(
                    "INSERT INTO meta(key,value) VALUES('source_status','No Tableau data loaded') "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                )
                con.execute(
                    "INSERT INTO meta(key,value) VALUES('last_source_refresh','') "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
                )
            con.execute(
                "INSERT INTO meta(key,value) VALUES('v99_demo_printer_removed','1')"
            )

        if not con.execute(
            "SELECT 1 FROM meta WHERE key='v18_team_vs_team_layout'"
        ).fetchone():
            row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
            if row:
                try:
                    config = json.loads(row["value"])
                    visible = config.setdefault("visible_metrics", {})
                    visible["team_vs_team"] = list(DEFAULT_METRICS["team_vs_team"])
                    config["team_vs_team_selected"] = list(
                        dict.fromkeys(config.get("team_vs_team_selected", []))
                    )[:2]
                    config["show_team_members_in_vs"] = True
                    con.execute(
                        "UPDATE settings SET value=? WHERE key='config'",
                        (json.dumps(config),),
                    )
                except Exception:
                    pass
            con.execute(
                "INSERT INTO meta(key,value) VALUES('v18_team_vs_team_layout','1')"
            )

        if not con.execute(
            "SELECT 1 FROM meta WHERE key='v19_head_to_head_layout'"
        ).fetchone():
            row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
            if row:
                try:
                    config = json.loads(row["value"])
                    config.setdefault("visible_metrics", {})["team_vs_team"] = list(
                        DEFAULT_METRICS["team_vs_team"]
                    )
                    config["team_vs_team_selected"] = list(
                        dict.fromkeys(config.get("team_vs_team_selected", []))
                    )[:2]
                    config["show_team_members_in_vs"] = True
                    con.execute(
                        "UPDATE settings SET value=? WHERE key='config'",
                        (json.dumps(config),),
                    )
                except Exception:
                    pass
            con.execute(
                "INSERT INTO meta(key,value) VALUES('v19_head_to_head_layout','1')"
            )

        if not con.execute(
            "SELECT 1 FROM meta WHERE key='v22_highest_always_wins'"
        ).fetchone():
            row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
            if row:
                try:
                    config = json.loads(row["value"])
                    config["rank_direction"] = {
                        "whole_office": "desc",
                        "team_vs_team": "desc",
                        "all_teams": "desc",
                        "per_team": "desc",
                    }
                    con.execute(
                        "UPDATE settings SET value=? WHERE key='config'",
                        (json.dumps(config),),
                    )
                except Exception:
                    pass
            con.execute(
                "INSERT INTO meta(key,value) VALUES('v22_highest_always_wins','1')"
            )

        _sync_source_teams_in_connection(con)
        _migrate_legacy_overrides_in_connection(con)
