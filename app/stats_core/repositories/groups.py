"""Persistence for user-defined Groups."""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_GROUPS_KEY = "group_definitions"
_GROUP_TYPES_KEY = "group_type_definitions"


class GroupRepository:
    """Store generic Groups without coupling them to a particular data source."""

    @staticmethod
    def _read(key):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return []
        try:
            value = json.loads(row["value"])
        except Exception:
            return []
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _write(key, values):
        clean = [dict(item) for item in (values or []) if isinstance(item, dict)]
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(clean)),
            )
        return clean

    def list_types(self):
        return self._read(_GROUP_TYPES_KEY)

    def get_type(self, type_id):
        key = str(type_id or "")
        return next((row for row in self.list_types() if str(row.get("id")) == key), None)

    def save_type(self, definition):
        definition = dict(definition or {})
        key = str(definition.get("id") or "")
        rows = [row for row in self.list_types() if str(row.get("id")) != key]
        rows.append(definition)
        self._write(_GROUP_TYPES_KEY, rows)
        return definition

    def delete_type(self, type_id):
        key = str(type_id or "")
        rows = self.list_types()
        kept = [row for row in rows if str(row.get("id")) != key]
        if len(kept) == len(rows):
            return False
        self._write(_GROUP_TYPES_KEY, kept)
        return True

    def list(self):
        return self._read(_GROUPS_KEY)

    def save_all(self, groups):
        return self._write(_GROUPS_KEY, groups)

    def get(self, group_id):
        key = str(group_id or "")
        return next((row for row in self.list() if str(row.get("id")) == key), None)

    def save(self, group):
        group = dict(group or {})
        key = str(group.get("id") or "")
        rows = [row for row in self.list() if str(row.get("id")) != key]
        rows.append(group)
        self.save_all(rows)
        return group

    def delete(self, group_id):
        key = str(group_id or "")
        rows = self.list()
        kept = [row for row in rows if str(row.get("id")) != key]
        if len(kept) == len(rows):
            return False
        self.save_all(kept)
        return True
