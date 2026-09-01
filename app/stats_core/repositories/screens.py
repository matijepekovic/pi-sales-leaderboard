"""Persistence for user-created screen definitions."""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_SCREENS_KEY = "screen_definitions"


class ScreenRepository:
    def list(self):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (_SCREENS_KEY,)
            ).fetchone()
        if not row:
            return []
        try:
            value = json.loads(row["value"])
        except Exception:
            return []
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def save_all(self, screens):
        clean = [dict(item) for item in (screens or []) if isinstance(item, dict)]
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_SCREENS_KEY, json.dumps(clean)),
            )
        return clean

    def get(self, screen_id):
        key = str(screen_id or "")
        return next((row for row in self.list() if str(row.get("id")) == key), None)

    def save(self, screen):
        screen = dict(screen or {})
        key = str(screen.get("id") or "")
        rows = [row for row in self.list() if str(row.get("id")) != key]
        rows.append(screen)
        self.save_all(rows)
        return screen

    def delete(self, screen_id):
        key = str(screen_id or "")
        rows = self.list()
        kept = [row for row in rows if str(row.get("id")) != key]
        if len(kept) == len(rows):
            return False
        self.save_all(kept)
        return True
