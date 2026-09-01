"""Persistent normalized Source and Report catalog."""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_CATALOG_KEY = "data_catalog"


class DataCatalogRepository:
    def _read(self):
        with sqlite.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (_CATALOG_KEY,)).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["value"])
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def _write(self, value):
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_CATALOG_KEY, json.dumps(value)),
            )

    def ensure(self):
        if self._read() is None:
            self._write({"sources": [], "reports": []})
        return self.get()

    def get(self):
        value = self._read() or {"sources": [], "reports": []}
        return {
            "sources": [dict(row) for row in (value.get("sources") or []) if isinstance(row, dict)],
            "reports": [dict(row) for row in (value.get("reports") or []) if isinstance(row, dict)],
        }

    def save(self, catalog):
        value = {
            "sources": [dict(row) for row in ((catalog or {}).get("sources") or []) if isinstance(row, dict)],
            "reports": [dict(row) for row in ((catalog or {}).get("reports") or []) if isinstance(row, dict)],
        }
        self._write(value)
        return value

    def source(self, source_id):
        key = str(source_id or "")
        return next((dict(row) for row in self.get()["sources"] if str(row.get("id")) == key), None)

    def report(self, report_id):
        key = str(report_id or "")
        return next((dict(row) for row in self.get()["reports"] if str(row.get("id")) == key), None)
