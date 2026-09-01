"""Persistence for display playback state."""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_DISPLAY_KEY = "display_state"
DEFAULT_DISPLAY_STATE = {
    "active_screen_id": "builtin:whole_office",
    "rotation_screen_ids": [],
    "temporary_override_screen_id": "",
}


class DisplayRepository:
    def get(self):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (_DISPLAY_KEY,)
            ).fetchone()
        value = dict(DEFAULT_DISPLAY_STATE)
        if row:
            try:
                incoming = json.loads(row["value"])
            except Exception:
                incoming = {}
            if isinstance(incoming, dict):
                value.update(incoming)
        value["active_screen_id"] = str(value.get("active_screen_id") or DEFAULT_DISPLAY_STATE["active_screen_id"])
        value["rotation_screen_ids"] = [
            str(item) for item in (value.get("rotation_screen_ids") or []) if str(item).strip()
        ]
        value["temporary_override_screen_id"] = str(value.get("temporary_override_screen_id") or "")
        return value

    def save(self, state):
        value = dict(DEFAULT_DISPLAY_STATE)
        value.update(state or {})
        value["rotation_screen_ids"] = list(dict.fromkeys(
            str(item) for item in (value.get("rotation_screen_ids") or []) if str(item).strip()
        ))
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_DISPLAY_KEY, json.dumps(value)),
            )
        return value
