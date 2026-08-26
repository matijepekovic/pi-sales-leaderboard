"""v108 pull rules: Tableau owns numbers; the Pi owns organization.

Two guarantees live here:

1. A Tableau pull can never create/assign a Pi team or team lead. Incoming
   organization text is stripped before rows reach database.replace_reps().
2. If a rep disappears from Tableau, their last row for the exact same pull
   scope is retained. The cache is keyed by resolved date range + report/filter
   configuration, so changing the date range or report does not carry them
   forward.

This module is installed from tableau_scheduler while server.py is importing,
before database.init_db() runs. That timing also lets us disable the legacy
source-team sync without touching Team Builder or its persistent assignments.
"""
import json

import database
from sources.tableau import resolve_dates

_CACHE_TABLE = "rep_fallback_cache_v108"
_INSTALLED = False
_ORIGINAL_RESOLVE_SOURCE = None


def _normalize_row(row):
    """Keep source metrics/identity, but remove source-owned organization."""
    clean = dict(row or {})
    clean.pop("id", None)
    clean["team"] = "Unassigned"
    clean["team_lead"] = None
    return clean


def _scope(source_picker_module, settings):
    """Stable key for one exact report/date/filter selection."""
    settings = settings or {}
    start, end = resolve_dates(settings)
    config = source_picker_module.source_config(settings)
    signature = {
        "start": start,
        "end": end,
        "server": config.get("server", ""),
        "site": config.get("site", ""),
        "pat_name": config.get("pat_name", ""),
        "workbook": config.get("workbook", ""),
        "sheet": config.get("sheet", ""),
        "export": config.get("export", ""),
        "filters": config.get("filters", []),
        "row_filter": config.get("row_filter", {}),
        "mapping": config.get("mapping", {}),
        "date_start_field": config.get("date_start_field", ""),
        "date_end_field": config.get("date_end_field", ""),
        # Legacy/global people filters still affect who the source returns.
        "data_office": settings.get("data_office", ""),
        "data_include_people": settings.get("data_include_people", []),
        "data_exclude_people": settings.get("data_exclude_people", []),
    }
    key = json.dumps(signature, sort_keys=True, separators=(",", ":"), default=str)
    return key, start, end


def _ensure_cache_table():
    with database.connect() as con:
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} ("
            "scope TEXT NOT NULL, "
            "rep_key TEXT NOT NULL, "
            "rep_name TEXT NOT NULL DEFAULT '', "
            "row_json TEXT NOT NULL, "
            "updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY(scope, rep_key))"
        )


def _raw_stored_rows():
    with database.connect() as con:
        return [dict(row) for row in con.execute("SELECT * FROM reps").fetchall()]


def _cache_rows(scope):
    with database.connect() as con:
        rows = con.execute(
            f"SELECT rep_key,row_json FROM {_CACHE_TABLE} WHERE scope=?",
            (scope,),
        ).fetchall()
    cached = {}
    for row in rows:
        try:
            value = json.loads(row["row_json"])
            if isinstance(value, dict):
                cached[str(row["rep_key"])] = _normalize_row(value)
        except Exception:
            continue
    return cached


def _write_cache(scope, rows):
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
                "rep_name=excluded.rep_name,row_json=excluded.row_json,"
                "updated_at=CURRENT_TIMESTAMP",
                (scope, rep_key, rep_name, json.dumps(_normalize_row(row), default=str)),
            )


def _merge_with_fallback(source_picker_module, settings, fresh_rows):
    """Fresh rows win; cached same-scope reps fill only truly missing keys."""
    if not fresh_rows:
        return fresh_rows

    _ensure_cache_table()
    # On the first v108 pull, the old reps table still contains the previous
    # successful snapshot. Seed it before replacement when we can prove it is
    # the same resolved period.
    _seed_current_scope(source_picker_module)
    scope, start, end = _scope(source_picker_module, settings)
    fresh = [_normalize_row(row) for row in fresh_rows]
    fresh_keys = {
        str(row.get("rep_key") or row.get("rep_name") or "").strip()
        for row in fresh
    }
    fresh_keys.discard("")

    cached = _cache_rows(scope)
    retained = [row for key, row in cached.items() if key not in fresh_keys]

    # Fresh data becomes the next fallback snapshot for this exact scope.
    _write_cache(scope, fresh)
    database.set_meta("v108_rep_scope", scope)
    database.set_meta("v108_rep_period", f"{start}|{end}")
    database.set_meta(
        "v108_retained_reps",
        json.dumps([str(row.get("rep_name") or row.get("rep_key") or "")
                    for row in retained]),
    )
    return fresh + retained


class _PolicySource:
    def __init__(self, inner, source_picker_module, settings):
        self._inner = inner
        self._source_picker_module = source_picker_module
        self._settings = dict(settings or {})

    def fetch(self):
        rows = self._inner.fetch()
        return _merge_with_fallback(self._source_picker_module, self._settings, rows)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def install(source_picker_module):
    """Install before database.init_db() and before any real pull occurs."""
    global _INSTALLED, _ORIGINAL_RESOLVE_SOURCE
    if _INSTALLED:
        return

    # Legacy startup used source team text to create Pi teams. Team Builder is
    # now the only owner of organization, so startup must never do that sync.
    if hasattr(database, "_sync_source_teams_in_connection"):
        database._sync_source_teams_in_connection = lambda _con: None

    _ORIGINAL_RESOLVE_SOURCE = source_picker_module.resolve_source

    def resolve_source_with_policy(settings):
        inner = _ORIGINAL_RESOLVE_SOURCE(settings)
        return _PolicySource(inner, source_picker_module, settings)

    source_picker_module.resolve_source = resolve_source_with_policy
    _INSTALLED = True


def _seed_current_scope(source_picker_module):
    """Seed v108 cache once from the board's existing same-period rows.

    This makes the upgrade protective immediately: if the current stored rows
    are known to belong to the currently resolved date range, they become the
    initial fallback snapshot before source organization text is scrubbed.
    """
    if str(database.get_meta("v108_cache_seeded", "") or "") == "1":
        return 0

    settings = database.get_settings()
    scope, start, end = _scope(source_picker_module, settings)
    status = str(database.get_meta("source_status", "") or "")
    rows = []
    if status.lower().startswith("tableau") and f"{start} to {end}" in status:
        rows = [_normalize_row(row) for row in _raw_stored_rows()]
        _write_cache(scope, rows)
        database.set_meta("v108_rep_scope", scope)
        database.set_meta("v108_rep_period", f"{start}|{end}")

    if rows:
        database.set_meta("v108_cache_seeded", "1")
    return len(rows)


def _scrub_source_organization():
    """Remove old Tableau team/team-lead text without touching Pi assignments."""
    with database.connect() as con:
        cur = con.execute(
            "UPDATE reps SET team='Unassigned', team_lead=NULL "
            "WHERE COALESCE(team,'')<>'Unassigned' OR team_lead IS NOT NULL"
        )
        changed = max(0, int(cur.rowcount or 0))
    if changed:
        database.bump_version()
    return changed


def bootstrap(source_picker_module):
    """Run after init_db(): create/seed cache, then enforce Pi-only organization."""
    _ensure_cache_table()
    seeded = _seed_current_scope(source_picker_module)
    scrubbed = _scrub_source_organization()
    return {"seeded": seeded, "scrubbed": scrubbed}
