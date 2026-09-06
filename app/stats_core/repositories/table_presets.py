"""Persistence for reusable Report table-presentation presets."""
from __future__ import annotations

import json

from stats_core.storage import sqlite


_TABLE_PRESETS_KEY = "table_presets"


class TablePresetRepository:
    """Store table presets independently from Screen definitions."""

    @staticmethod
    def list():
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (_TABLE_PRESETS_KEY,)
            ).fetchone()
        if not row:
            return []
        try:
            value = json.loads(row["value"])
        except Exception:
            return []
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def save_all(presets):
        clean = [dict(item) for item in (presets or []) if isinstance(item, dict)]
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_TABLE_PRESETS_KEY, json.dumps(clean)),
            )
        return clean

    def get(self, preset_id):
        key = str(preset_id or "")
        return next((item for item in self.list() if str(item.get("id") or "") == key), None)

    def save(self, preset):
        preset = dict(preset or {})
        key = str(preset.get("id") or "")
        rows = [item for item in self.list() if str(item.get("id") or "") != key]
        rows.append(preset)
        self.save_all(rows)
        return preset

    def delete(self, preset_id):
        key = str(preset_id or "")
        rows = self.list()
        kept = [item for item in rows if str(item.get("id") or "") != key]
        if len(kept) == len(rows):
            return False
        self.save_all(kept)
        return True

    def delete_report(self, report_id):
        key = str(report_id or "")
        rows = self.list()
        kept = [item for item in rows if str(item.get("report_id") or "") != key]
        if len(kept) == len(rows):
            return False
        self.save_all(kept)
        return True
