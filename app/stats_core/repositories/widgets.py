"""Persistence for reusable, unstyled Widget definitions."""
from __future__ import annotations

import json

from stats_core.storage import sqlite


class WidgetRepository:
    """Persist each Widget independently; callers cannot mutate other domains."""

    _PREFIX = "widget:"

    def list(self):
        with sqlite.connect() as con:
            rows = con.execute("SELECT value FROM settings WHERE key LIKE ?", (self._PREFIX + "%",)).fetchall()
        return [json.loads(row["value"]) for row in rows]

    def get(self, widget_id):
        with sqlite.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (self._PREFIX + str(widget_id),)).fetchone()
        return json.loads(row["value"]) if row else None

    def save(self, widget):
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self._PREFIX + str(widget["id"]), json.dumps(widget, allow_nan=False)),
            )
        return dict(widget)

    def delete(self, widget_id):
        with sqlite.connect() as con:
            result = con.execute("DELETE FROM settings WHERE key=?", (self._PREFIX + str(widget_id),))
        return bool(result.rowcount)

    def field_dependents(self, field_id):
        return [
            str(widget.get("name") or widget["id"])
            for widget in self.list()
            if field_id in widget.get("field_ids", [])
            or any(rule.get("field_id") == field_id for rule in widget.get("filters", []))
        ]
