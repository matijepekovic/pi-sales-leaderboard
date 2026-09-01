"""Persistence for display playback state."""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_DISPLAY_KEY = "display_state"
DEFAULT_DISPLAY_STATE = {
    "active_screen_id": "builtin:whole_office",
    "rotation_screen_ids": [],
    "rotation_enabled": False,
    "rotation_seconds": 15,
}


def _screen_id_from_mode(raw):
    raw = str(raw or "whole_office").strip()
    if raw.startswith("per_team::"): return f"builtin:per_team:{raw.split('::', 1)[1]}"
    if raw in {"whole_office", "team_vs_team", "all_teams", "product_close"}: return f"builtin:{raw}"
    return "builtin:whole_office"


class DisplayRepository:
    def _read(self):
        with sqlite.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (_DISPLAY_KEY,)).fetchone()
        if not row: return None
        try: value = json.loads(row["value"])
        except Exception: return None
        return value if isinstance(value, dict) else None

    def ensure(self, settings):
        current = self._read()
        if current is None:
            current = {**DEFAULT_DISPLAY_STATE, "active_screen_id": _screen_id_from_mode((settings or {}).get("active_mode"))}
            self.save(current)
        return self.get()

    def get(self):
        incoming = self._read() or {}; value = dict(DEFAULT_DISPLAY_STATE); value.update(incoming)
        value["active_screen_id"] = str(value.get("active_screen_id") or DEFAULT_DISPLAY_STATE["active_screen_id"])
        value["rotation_screen_ids"] = [str(item) for item in (value.get("rotation_screen_ids") or []) if str(item).strip()]
        value["rotation_enabled"] = bool(value.get("rotation_enabled"))
        try: value["rotation_seconds"] = min(max(int(value.get("rotation_seconds") or 15), 5), 3600)
        except Exception: value["rotation_seconds"] = 15
        return value

    def save(self, state):
        value = dict(DEFAULT_DISPLAY_STATE); value.update(state or {})
        value["active_screen_id"] = str(value.get("active_screen_id") or DEFAULT_DISPLAY_STATE["active_screen_id"])
        value["rotation_screen_ids"] = list(dict.fromkeys(str(item) for item in (value.get("rotation_screen_ids") or []) if str(item).strip()))
        value["rotation_enabled"] = bool(value.get("rotation_enabled"))
        try: value["rotation_seconds"] = min(max(int(value.get("rotation_seconds") or 15), 5), 3600)
        except Exception: value["rotation_seconds"] = 15
        with sqlite.connect() as con:
            con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_DISPLAY_KEY, json.dumps(value)))
        return value
