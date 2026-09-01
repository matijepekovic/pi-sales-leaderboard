"""Persistence for user-facing Display Value names."""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_DISPLAY_VALUE_NAMES_KEY = "display_value_names"


class DisplayValueRepository:
    """Stores only rename overrides; Display Values themselves come from Report fields."""

    def list_names(self):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (_DISPLAY_VALUE_NAMES_KEY,)
            ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(row["value"])
        except Exception:
            return {}
        return {str(key): str(name) for key, name in value.items()} if isinstance(value, dict) else {}

    def _save_names(self, names):
        clean = {str(key): str(name) for key, name in (names or {}).items() if str(key) and str(name).strip()}
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_DISPLAY_VALUE_NAMES_KEY, json.dumps(clean)),
            )
        return clean

    def save_name(self, display_value_id, name):
        names = self.list_names()
        names[str(display_value_id)] = str(name)
        self._save_names(names)
        return str(name)

    def delete_name(self, display_value_id):
        names = self.list_names()
        existed = str(display_value_id) in names
        names.pop(str(display_value_id), None)
        self._save_names(names)
        return existed
