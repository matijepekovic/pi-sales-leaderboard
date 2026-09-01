"""Persistence for reusable display Filter definitions."""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_FILTERS_KEY = "display_filters"


class FilterRepository:
    def list(self):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (_FILTERS_KEY,)
            ).fetchone()
        if not row:
            return []
        try:
            value = json.loads(row["value"])
        except Exception:
            return []
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def save_all(self, filters):
        clean = [dict(item) for item in (filters or []) if isinstance(item, dict)]
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_FILTERS_KEY, json.dumps(clean)),
            )
        return clean

    def get(self, filter_id):
        key = str(filter_id or "")
        return next((item for item in self.list() if str(item.get("id")) == key), None)

    def save(self, filter_def):
        item = dict(filter_def or {})
        key = str(item.get("id") or "")
        rows = [row for row in self.list() if str(row.get("id")) != key]
        rows.append(item)
        self.save_all(rows)
        return item

    def delete(self, filter_id):
        key = str(filter_id or "")
        rows = self.list()
        kept = [row for row in rows if str(row.get("id")) != key]
        if len(kept) == len(rows):
            return False
        self.save_all(kept)
        return True
