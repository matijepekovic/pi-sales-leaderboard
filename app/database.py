import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

DATA_DIR = Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
DB_PATH = DATA_DIR / "leaderboard.db"
_LOCK = threading.RLock()

DEFAULT_METRICS = {
    "whole_office": [
        "rank", "rep_name", "team", "issued_leads", "pitched_leads",
        "sold_leads", "close_rate", "gross_split", "pending_split",
        "net_split", "dpl"
    ],
    "team_vs_team": [
        "rank", "rep_name",
        "issued_leads", "pitched_leads", "pitched_rate",
        "sold_leads", "close_rate",
        "gross_split", "pending_split", "net_split", "dpl",
        "sales_retention", "avg_gross_sale", "avg_net_sale"
    ],
    "all_teams": [
        "rank", "rep_name", "sold_leads", "close_rate",
        "gross_split", "pending_split", "net_split", "dpl"
    ],
    "per_team": [
        "rank", "rep_name", "issued_leads", "pitched_leads",
        "sold_leads", "close_rate", "gross_split",
        "pending_split", "net_split", "dpl"
    ],
}

DEFAULT_SETTINGS = {
    "active_mode": "whole_office",
    "sort_metric": {
        "whole_office": "net_split",
        "team_vs_team": "net_split",
        "all_teams": "net_split",
        "per_team": "net_split",
    },
    "rank_direction": {
        "whole_office": "desc",
        "team_vs_team": "desc",
        "all_teams": "desc",
        "per_team": "desc",
    },
    # v75. Percent size of the numbers only, per screen. 100 is unchanged.
    "number_font_scale": {
        "whole_office": 100,
        "team_vs_team": 100,
        "all_teams": 100,
        "per_team": 100,
    },
    "visible_metrics": DEFAULT_METRICS,
    "team_vs_team_selected": [],
    "per_team_selected": "",
    "show_team_members_in_vs": True,
    "display_refresh_seconds": 5,
    "source_refresh_seconds": 60,
    "title": "SALES LEADERBOARD",
    "subtitle": "",
    "currency_symbol": "$",
    "theme_config": {"office": {}, "teams": {}},

    # Public GitHub auto-update source.
    # Example: "yourusername/pi-sales-leaderboard"
    "github_repo": "",
    "github_auto_update": False,

    # ---- Tableau connection -------------------------------------------
    # tableau_pat_secret is WRITE-ONLY: the API never returns it, it only
    # reports tableau_pat_configured, so a stored token cannot be read back
    # over the network.
    "tableau_server": "",
    "tableau_site": "",
    "tableau_pat_name": "",
    "tableau_pat_secret": "",
    "tableau_view": "",

    # ---- What to pull (persists across refreshes, reboots and updates) --
    # Office "" means every office.
    "data_office": "",
    # "current_month" (default, auto-rolls) or "custom".
    "data_date_mode": "current_month",
    "data_date_start": "",
    "data_date_end": "",
    # Tableau parameter names that carry the date window.
    "data_date_param_start": "Start",
    "data_date_param_end": "End",
    # Always included whatever office they sit in; exclusion always wins.
    "data_include_people": [],
    "data_exclude_people": [],

    # v79 rep-board report override. Empty means the shipped default, and
    # the shipped connector runs unchanged. Only written after a trial pull
    # against the chosen report has actually parsed.
    "tableau_workbook": "",
    "tableau_sheet": "",
    # Which of the chosen report's columns feeds which board stat. Empty
    # means the report is read by the shipped parser, unmapped.
    "source_mapping": {},

    # v78 product-card icon overrides: {"bath": "<library url>", ...}.
    # Empty means the screen's built-in SVG glyph is used.
    "product_icons": {},

    # Office printer, raw port 9100. Remembered so the test button works
    # without retyping the address.
    "printer_host": "",
    "printer_port": 9100,

    # Settings-page lock. Stores a salted PBKDF2 hash, never the PIN.
    "settings_pin_hash": "",
}

# Values that must never appear in an API response.
SECRET_SETTING_KEYS = ("tableau_pat_secret", "settings_pin_hash")

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

-- Legacy table retained so older installs can migrate without losing overrides.
CREATE TABLE IF NOT EXISTS team_overrides (
    rep_key TEXT PRIMARY KEY,
    override_team TEXT NOT NULL
);

-- Pi-owned organization structure.
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

-- Names intentionally deleted from the Pi organization.
-- This prevents a Tableau source team from silently recreating itself.
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

-- v75 Close Rate by Product. Stands entirely apart from reps: a different
-- Tableau workbook, a different grain, and no join to anything else here.
-- Beta, reachable only from the settings remote.
CREATE TABLE IF NOT EXISTS product_close (
    product TEXT PRIMARY KEY,
    close_rate REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

METRIC_DEFS = [
    ("rank", "Rank", "system"),
    ("rep_name", "Sales Rep", "text"),
    ("team", "Team", "text"),
    ("home_branch", "Home Branch", "text"),
    ("title", "Title", "text"),
    ("hire_date", "Hire Date", "text"),
    ("issued_leads", "Issued Leads", "number"),
    ("pitched_leads", "Pitched Leads", "number"),
    ("pitched_rate", "Pitched Rate", "percent"),
    ("sold_leads", "Sold Leads", "number"),
    ("close_rate", "Close Rate", "percent"),
    ("gross_split", "Gross Split", "currency"),
    ("pending_split", "Pending Split", "currency"),
    ("net_split", "Net Split", "currency"),
    ("dpl", "DPL", "currency"),
    ("sales_retention", "Sales Retention", "percent"),
    ("avg_gross_sale", "Avg. Gross Sale", "currency"),
    ("avg_net_sale", "Avg. Net Sale", "currency"),
]


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


def _ensure_team_in_connection(con, name, restore_deleted=False):
    name = str(name or "").strip()
    if not name or name.lower() == "unassigned":
        return None

    # A deleted team name is NOT blocked. If Tableau sends the team again,
    # it is allowed to recreate normally.
    con.execute(
        "INSERT INTO teams(name,active) VALUES(?,1) "
        "ON CONFLICT(name) DO UPDATE SET active=1",
        (name,)
    )
    row = con.execute(
        "SELECT team_id FROM teams WHERE name=? COLLATE NOCASE", (name,)
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
                (row["rep_key"], team_id)
            )


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)

        # Schema migration for older installs.
        team_cols = {r["name"] for r in con.execute("PRAGMA table_info(teams)").fetchall()}
        if "logo_path" not in team_cols:
            con.execute("ALTER TABLE teams ADD COLUMN logo_path TEXT")

        row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
        if not row:
            con.execute(
                "INSERT INTO settings(key,value) VALUES('config',?)",
                (json.dumps(DEFAULT_SETTINGS),)
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

        # v18: Team vs Team is a purpose-built two-team comparison. On an
        # existing install, expand its rep metrics once so the new layout starts
        # with complete individual stats. The user can still turn metrics off
        # afterward in Team vs Team mode settings.
        if not con.execute("SELECT 1 FROM meta WHERE key='v18_team_vs_team_layout'").fetchone():
            row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
            if row:
                try:
                    cfg = json.loads(row["value"])
                    visible = cfg.setdefault("visible_metrics", {})
                    visible["team_vs_team"] = list(DEFAULT_METRICS["team_vs_team"])
                    cfg["team_vs_team_selected"] = list(dict.fromkeys(
                        cfg.get("team_vs_team_selected", [])
                    ))[:2]
                    cfg["show_team_members_in_vs"] = True
                    con.execute(
                        "UPDATE settings SET value=? WHERE key='config'",
                        (json.dumps(cfg),)
                    )
                except Exception:
                    pass
            con.execute(
                "INSERT INTO meta(key,value) VALUES('v18_team_vs_team_layout','1')"
            )

        # v19: force the head-to-head mode back to the complete numeric rep
        # stat set once. The TV renderer itself also uses a fixed complete list,
        # so stale older settings cannot hide rep stats.
        if not con.execute("SELECT 1 FROM meta WHERE key='v19_head_to_head_layout'").fetchone():
            row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
            if row:
                try:
                    cfg = json.loads(row["value"])
                    cfg.setdefault("visible_metrics", {})["team_vs_team"] = list(DEFAULT_METRICS["team_vs_team"])
                    cfg["team_vs_team_selected"] = list(dict.fromkeys(
                        cfg.get("team_vs_team_selected", [])
                    ))[:2]
                    cfg["show_team_members_in_vs"] = True
                    con.execute(
                        "UPDATE settings SET value=? WHERE key='config'",
                        (json.dumps(cfg),)
                    )
                except Exception:
                    pass
            con.execute(
                "INSERT INTO meta(key,value) VALUES('v19_head_to_head_layout','1')"
            )

        # v22: ranking has one rule everywhere: highest selected metric is #1.
        if not con.execute("SELECT 1 FROM meta WHERE key='v22_highest_always_wins'").fetchone():
            row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
            if row:
                try:
                    cfg = json.loads(row["value"])
                    cfg["rank_direction"] = {
                        "whole_office": "desc",
                        "team_vs_team": "desc",
                        "all_teams": "desc",
                        "per_team": "desc",
                    }
                    con.execute(
                        "UPDATE settings SET value=? WHERE key='config'",
                        (json.dumps(cfg),)
                    )
                except Exception:
                    pass
            con.execute(
                "INSERT INTO meta(key,value) VALUES('v22_highest_always_wins','1')"
            )

        # Existing v3/v4 installations automatically become v5 organization data.
        _sync_source_teams_in_connection(con)
        _migrate_legacy_overrides_in_connection(con)


def get_settings():
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key='config'").fetchone()
        base = json.loads(json.dumps(DEFAULT_SETTINGS))
        if not row:
            return base
        incoming = json.loads(row["value"])
        base.update(incoming)
        base["visible_metrics"] = {
            **DEFAULT_METRICS,
            **incoming.get("visible_metrics", {})
        }
        base["sort_metric"] = {
            **DEFAULT_SETTINGS["sort_metric"],
            **incoming.get("sort_metric", {})
        }
        base["number_font_scale"] = {
            **DEFAULT_SETTINGS["number_font_scale"],
            **incoming.get("number_font_scale", {})
        }
        # Ranking direction is no longer user-configurable.
        # Highest selected metric is always #1.
        base["rank_direction"] = {
            "whole_office": "desc",
            "team_vs_team": "desc",
            "all_teams": "desc",
            "per_team": "desc",
        }
        return base


def save_settings(settings):
    with connect() as con:
        con.execute(
            "INSERT INTO settings(key,value) VALUES('config',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(settings),)
        )


def get_meta(key, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_meta(key, value):
    with connect() as con:
        con.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value))
        )


def bump_meta(key):
    v = int(get_meta(key, "0")) + 1
    set_meta(key, v)
    return v


def bump_version():
    return bump_meta("data_version")


def replace_reps(rows):
    """Replace Tableau/source metrics only. Pi team assignments are NOT touched."""
    allowed = {
        "rep_key", "rep_name", "team", "team_lead", "home_branch", "lead_branch",
        "regional", "district", "title", "hire_date", "issued_leads",
        "pitched_leads", "pitched_rate", "sold_leads", "close_rate",
        "gross_split", "pending_split", "net_split", "dpl", "sales_retention",
        "avg_gross_sale", "avg_net_sale", "product", "position_filter",
        "pir_result", "source_updated_at", "raw_json"
    }
    cols = sorted(allowed)
    placeholders = ",".join("?" for _ in cols)
    sql = f"INSERT INTO reps ({','.join(cols)}) VALUES ({placeholders})"
    with connect() as con:
        con.execute("DELETE FROM reps")
        for row in rows:
            clean = {k: row.get(k) for k in cols}
            if not clean["rep_key"]:
                clean["rep_key"] = clean["rep_name"]
            if not clean["team"]:
                clean["team"] = "Unassigned"
            con.execute(sql, tuple(clean[c] for c in cols))
            _ensure_team_in_connection(con, clean["team"])
    bump_version()


def replace_product_close(rows):
    """Replace the beta product close-rate table. Touches nothing else.

    Deliberately does NOT bump data_version: the TV has no product view, so
    there is nothing for the display to re-render and no reason to make it
    reload the board.
    """
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with connect() as con:
        con.execute("DELETE FROM product_close")
        for row in rows:
            product = str(row.get("product") or "").strip()
            if not product:
                continue
            con.execute(
                "INSERT OR REPLACE INTO product_close "
                "(product, close_rate, updated_at) VALUES (?,?,?)",
                (product, float(row.get("close_rate") or 0), stamp),
            )


def get_product_close():
    """Stored product close rates, best first."""
    with connect() as con:
        rows = con.execute(
            "SELECT product, close_rate, updated_at FROM product_close "
            "ORDER BY close_rate DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def create_team(name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("Team name is required.")
    with connect() as con:
        team_id = _ensure_team_in_connection(con, name, restore_deleted=True)
    bump_meta("organization_version")
    return team_id


def rename_team(team_id, name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("Team name is required.")
    with connect() as con:
        con.execute(
            "UPDATE teams SET name=?, active=1 WHERE team_id=?",
            (name, int(team_id))
        )
    bump_meta("organization_version")


def delete_team(team_id, reassignments=None):
    """
    Permanently delete a Pi team.

    Every rep who currently belongs to the team (including Tableau-fallback
    members without a local override) must be reassigned to another active
    Pi team before deletion can complete.
    """
    team_id = int(team_id)
    reassignments = reassignments or []
    requested = {
        str(item.get("rep_key") or "").strip(): int(item.get("team_id"))
        for item in reassignments
        if str(item.get("rep_key") or "").strip()
        and item.get("team_id") not in (None, "", 0, "0")
    }

    with connect() as con:
        team = con.execute(
            "SELECT team_id,name,logo_path FROM teams WHERE team_id=? AND active=1",
            (team_id,)
        ).fetchone()
        if not team:
            raise ValueError("Team not found.")

        team_name = str(team["name"])
        logo_path = team["logo_path"]

        active_destinations = {
            int(r["team_id"]): r["name"]
            for r in con.execute(
                "SELECT team_id,name FROM teams WHERE active=1 AND team_id<>?",
                (team_id,)
            ).fetchall()
        }

        assignments = {
            r["rep_key"]: int(r["team_id"])
            for r in con.execute(
                "SELECT rep_key,team_id FROM rep_team_assignments"
            ).fetchall()
        }
        source_reps = [dict(r) for r in con.execute(
            "SELECT rep_key,team FROM reps"
        ).fetchall()]

        effective_members = []
        for rep in source_reps:
            rep_key = str(rep.get("rep_key") or "")
            assigned_id = assignments.get(rep_key)
            if assigned_id == team_id:
                effective_members.append(rep_key)
                continue
            if assigned_id:
                continue
            if str(rep.get("team") or "").strip().lower() == team_name.lower():
                effective_members.append(rep_key)

        if effective_members and not active_destinations:
            raise ValueError(
                "This team has reps. Create another team before deleting it."
            )

        missing = [rep_key for rep_key in effective_members if rep_key not in requested]
        if missing:
            raise ValueError(
                "Every rep on this team must be reassigned before the team can be deleted."
            )

        for rep_key in effective_members:
            destination_id = requested[rep_key]
            if destination_id == team_id or destination_id not in active_destinations:
                raise ValueError("Choose a valid destination team for every rep.")
            con.execute(
                "INSERT INTO rep_team_assignments(rep_key,team_id) VALUES(?,?) "
                "ON CONFLICT(rep_key) DO UPDATE SET team_id=excluded.team_id",
                (rep_key, destination_id)
            )

        # Delete only the current Pi team structure. We intentionally do NOT
        # blacklist the name. If Tableau later sends this team again, the normal
        # source-team sync is allowed to recreate it.
        con.execute("DELETE FROM teams WHERE team_id=?", (team_id,))

    bump_meta("organization_version")
    return {
        "team_id": team_id,
        "name": team_name,
        "logo_path": logo_path,
        "member_count": len(effective_members),
        "destination_team_ids": sorted(set(requested.values())),
    }


def set_team_lead(team_id, lead_name, lead_role):
    """Each team has exactly one leader. Saving replaces the previous leader."""
    lead_name = str(lead_name or "").strip()
    lead_role = str(lead_role or "Sales Manager").strip() or "Sales Manager"

    with connect() as con:
        con.execute("DELETE FROM team_leads WHERE team_id=?", (int(team_id),))
        if not lead_name:
            bump_meta("organization_version")
            return None

        cur = con.execute(
            "INSERT INTO team_leads(team_id,lead_name,lead_role) VALUES(?,?,?)",
            (int(team_id), lead_name, lead_role)
        )
        lead_id = cur.lastrowid

    bump_meta("organization_version")
    return lead_id


def delete_team_lead(lead_id):
    with connect() as con:
        con.execute("DELETE FROM team_leads WHERE lead_id=?", (int(lead_id),))
    bump_meta("organization_version")


def assign_rep_to_team(rep_key, team_id):
    rep_key = str(rep_key or "").strip()
    if not rep_key:
        raise ValueError("Rep key is required.")
    with connect() as con:
        if team_id in (None, "", 0, "0"):
            con.execute("DELETE FROM rep_team_assignments WHERE rep_key=?", (rep_key,))
        else:
            con.execute(
                "INSERT INTO rep_team_assignments(rep_key,team_id) VALUES(?,?) "
                "ON CONFLICT(rep_key) DO UPDATE SET team_id=excluded.team_id",
                (rep_key, int(team_id))
            )
    bump_meta("organization_version")


def set_rep_team_assignments(items):
    with connect() as con:
        for item in items:
            rep_key = str(item.get("rep_key") or "").strip()
            team_id = item.get("team_id")
            if not rep_key:
                continue
            if team_id in (None, "", 0, "0"):
                con.execute("DELETE FROM rep_team_assignments WHERE rep_key=?", (rep_key,))
            else:
                con.execute(
                    "INSERT INTO rep_team_assignments(rep_key,team_id) VALUES(?,?) "
                    "ON CONFLICT(rep_key) DO UPDATE SET team_id=excluded.team_id",
                    (rep_key, int(team_id))
                )
    bump_meta("organization_version")


def set_team_logo(team_id, logo_path):
    with connect() as con:
        con.execute(
            "UPDATE teams SET logo_path=? WHERE team_id=?",
            (str(logo_path or "").strip() or None, int(team_id))
        )
    bump_meta("organization_version")


def save_team_builder(team_id, name, leader_name, leader_role, member_rep_keys):
    """
    Unified Team Builder save:
      - create/rename team
      - assign exactly one leader
      - assign selected reps to the team
      - remove reps that were previously locally assigned to this team but
        are no longer selected

    Tableau metrics are never modified.
    """
    name = str(name or "").strip()
    if not name:
        raise ValueError("Team name is required.")

    leader_name = str(leader_name or "").strip()
    leader_role = str(leader_role or "Sales Manager").strip() or "Sales Manager"
    desired_members = {str(x).strip() for x in (member_rep_keys or []) if str(x).strip()}

    with connect() as con:
        if team_id:
            team_id = int(team_id)
            con.execute(
                "UPDATE teams SET name=?,active=1 WHERE team_id=?",
                (name, team_id)
            )
        else:
            con.execute(
                "INSERT INTO teams(name,active) VALUES(?,1)",
                (name,)
            )
            team_id = int(con.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        # Exactly one leader.
        con.execute("DELETE FROM team_leads WHERE team_id=?", (team_id,))
        if leader_name:
            con.execute(
                "INSERT INTO team_leads(team_id,lead_name,lead_role) VALUES(?,?,?)",
                (team_id, leader_name, leader_role)
            )

        # Remove local assignments no longer selected for this team.
        current = {
            r["rep_key"]
            for r in con.execute(
                "SELECT rep_key FROM rep_team_assignments WHERE team_id=?",
                (team_id,)
            ).fetchall()
        }
        for rep_key in current - desired_members:
            con.execute(
                "DELETE FROM rep_team_assignments WHERE rep_key=? AND team_id=?",
                (rep_key, team_id)
            )

        # Assign desired members. ON CONFLICT moves them from any prior local team.
        for rep_key in desired_members:
            con.execute(
                "INSERT INTO rep_team_assignments(rep_key,team_id) VALUES(?,?) "
                "ON CONFLICT(rep_key) DO UPDATE SET team_id=excluded.team_id",
                (rep_key, team_id)
            )

    bump_meta("organization_version")
    return team_id


def get_team_definitions(include_inactive=False):
    where = "" if include_inactive else "WHERE t.active=1"
    with connect() as con:
        teams = [dict(r) for r in con.execute(
            f"SELECT t.team_id,t.name,t.logo_path,t.active,t.created_at FROM teams t {where} "
            "ORDER BY t.name COLLATE NOCASE"
        ).fetchall()]
        leads = [dict(r) for r in con.execute(
            "SELECT lead_id,team_id,lead_name,lead_role FROM team_leads "
            "ORDER BY lead_name COLLATE NOCASE"
        ).fetchall()]
        assignments = {
            r["rep_key"]: int(r["team_id"])
            for r in con.execute(
                "SELECT rep_key,team_id FROM rep_team_assignments"
            ).fetchall()
        }
        source_reps = [dict(r) for r in con.execute(
            "SELECT rep_key,team FROM reps"
        ).fetchall()]

    leads_by_team = {}
    for lead in leads:
        leads_by_team.setdefault(int(lead["team_id"]), []).append(lead)

    local_counts = {}
    for rep_key, team_id in assignments.items():
        local_counts[team_id] = local_counts.get(team_id, 0) + 1

    # Effective count includes un-overridden reps whose Tableau team matches a Pi team.
    team_id_by_name = {t["name"].lower(): int(t["team_id"]) for t in teams}
    effective_counts = {}
    for rep in source_reps:
        tid = assignments.get(rep["rep_key"])
        if not tid:
            tid = team_id_by_name.get(str(rep.get("team") or "").strip().lower())
        if tid:
            effective_counts[tid] = effective_counts.get(tid, 0) + 1

    for team in teams:
        tid = int(team["team_id"])
        lead_list = leads_by_team.get(tid, [])
        team["leader"] = lead_list[0] if lead_list else None
        team["leads"] = lead_list[:1]  # backward compatibility for display code
        team["assigned_rep_count"] = local_counts.get(tid, 0)
        team["rep_count"] = effective_counts.get(tid, 0)
    return teams


def apply_team_overlay(rows):
    """Put the Pi's organization layer onto rep rows, whatever produced them.

    A rep's team is decided here, not by whatever the source returned:

      1. the persistent Pi assignment for that rep_key, when there is one
      2. otherwise the source's own team text, matched to a team of that name
      3. otherwise that text as its own bucket

    list_reps() has always done this to the stored rows; it is a function of
    its own so the mapping preview can be given the same treatment. Preview
    rows are the same people under the same rep_key, so they have to land on
    the same teams they will land on once the report is switched over.

    Rows are updated in place and returned.
    """
    rows = list(rows or [])
    with connect() as con:
        assignments = {
            r["rep_key"]: int(r["team_id"])
            for r in con.execute(
                "SELECT rep_key,team_id FROM rep_team_assignments"
            ).fetchall()
        }
        teams = {
            int(r["team_id"]): r["name"]
            for r in con.execute("SELECT team_id,name FROM teams WHERE active=1").fetchall()
        }
        team_ids_by_name = {
            name.lower(): team_id for team_id, name in teams.items()
        }

    for row in rows:
        tableau_team = str(row.get("team") or "Unassigned").strip() or "Unassigned"
        assigned_team_id = assignments.get(row.get("rep_key"))
        assigned_team_name = teams.get(assigned_team_id) if assigned_team_id else None

        if assigned_team_name:
            effective_team = assigned_team_name
            effective_team_id = assigned_team_id
            local_override = True
        else:
            effective_team = tableau_team
            effective_team_id = team_ids_by_name.get(tableau_team.lower())
            local_override = False

        row["tableau_team"] = tableau_team
        row["team"] = effective_team
        row["team_id"] = effective_team_id
        row["assigned_team_id"] = assigned_team_id
        row["team_override"] = assigned_team_name or ""
        row["local_team_override"] = local_override
    return rows


def list_reps():
    with connect() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM reps").fetchall()]
    return apply_team_overlay(rows)


def list_teams():
    return [
        {
            "team_id": t["team_id"],
            "team": t["name"],
            "reps": t["rep_count"],
            "leads": t["leads"],
        }
        for t in get_team_definitions()
    ]
