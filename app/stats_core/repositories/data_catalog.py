"""Persistent source/report catalog backed by the existing settings KV table.

The repository stores normalized Stats contracts only. Vendor adapters own
migration from their legacy settings into those contracts.
"""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_CATALOG_KEY = "data_catalog"
PRIMARY_SOURCE_ID = "source-primary"
REP_REPORT_ID = "report-reps"
PRODUCT_REPORT_ID = "report-products"


class DataCatalogRepository:
    def _read(self):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (_CATALOG_KEY,)
            ).fetchone()
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

    def ensure(self, default_catalog=None):
        current = self._read()
        if current is None:
            default_catalog = default_catalog if isinstance(default_catalog, dict) else {}
            current = {
                "sources": list(default_catalog.get("sources") or []),
                "reports": list(default_catalog.get("reports") or []),
            }
            self._write(current)
        return self.get()

    def get(self):
        value = self._read() or {"sources": [], "reports": []}
        value.setdefault("sources", [])
        value.setdefault("reports", [])
        return value

    def save(self, catalog):
        value = {
            "sources": list((catalog or {}).get("sources") or []),
            "reports": list((catalog or {}).get("reports") or []),
        }
        self._write(value)
        return value

    def source(self, source_id):
        key = str(source_id or "")
        return next((dict(row) for row in self.get()["sources"] if str(row.get("id")) == key), None)

    def report(self, report_id):
        key = str(report_id or "")
        return next((dict(row) for row in self.get()["reports"] if str(row.get("id")) == key), None)
