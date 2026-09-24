"""Persist the last refreshed rep names and their one weighted total."""
from __future__ import annotations

import json
import math


REP_NAMES_KEY = 'mod_sheet_rep_names'
REP_TOTALS_KEY = 'mod_sheet_rep_totals'


class ModSheetRepRepository:
    def __init__(self, db):
        self.db = db

    def snapshot(self) -> tuple[tuple[str, ...] | None, dict[str, float]]:
        # Read both values in one statement so refresh cannot mix two snapshots.
        with self.db.connect() as conn:
            values = {row['key']: json.loads(row['value']) for row in conn.execute(
                'SELECT key,value FROM meta WHERE key IN (?,?)', (REP_NAMES_KEY, REP_TOTALS_KEY))}
        names = values.get(REP_NAMES_KEY)
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            return None, {}
        # Existing installations have saved names but no measured totals yet.
        totals = values.get(REP_TOTALS_KEY)
        totals = totals if isinstance(totals, dict) else {}
        return tuple(names), {name: totals[name] for name in names if name in totals
                              and type(totals[name]) in (int, float)
                              and math.isfinite(totals[name]) and totals[name] >= 0}

    def replace(self, names: tuple[str, ...], totals: dict[str, float] | None = None) -> None:
        # Preserve the existing names format; replace names and totals atomically.
        with self.db.connect() as conn:
            conn.executemany(
                'INSERT INTO meta(key,value) VALUES (?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                ((REP_NAMES_KEY, json.dumps(list(names))),
                 (REP_TOTALS_KEY, json.dumps(totals or {}))),
            )
