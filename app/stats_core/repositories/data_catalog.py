"""Persistent source/report catalog backed by the existing settings KV table.

The SQLite schema intentionally stays unchanged. Source and report definitions
are application configuration documents, while report data continues to live in
the repositories that own that data.
"""
from __future__ import annotations

import json

from stats_core.storage import sqlite

_CATALOG_KEY = "data_catalog"
PRIMARY_SOURCE_ID = "source-tableau"
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

    @staticmethod
    def defaults(settings):
        settings = settings if isinstance(settings, dict) else {}
        legacy = settings.get("source") if isinstance(settings.get("source"), dict) else {}
        server = str(legacy.get("server") or settings.get("tableau_server") or "").strip()
        site = str(legacy.get("site") or settings.get("tableau_site") or "").strip()
        pat_name = str(legacy.get("pat_name") or settings.get("tableau_pat_name") or "").strip()
        report_config = {
            key: legacy.get(key)
            for key in (
                "workbook", "sheet", "filters", "date_start_field", "date_end_field",
                "mapping", "row_filter", "export",
            )
            if key in legacy
        }
        return {
            "sources": [
                {
                    "id": PRIMARY_SOURCE_ID,
                    "name": "Tableau",
                    "adapter": "tableau",
                    "enabled": True,
                    "connection": {
                        "server": server,
                        "site": site,
                        "pat_name": pat_name,
                        "secret_ref": "tableau_pat_secret",
                    },
                }
            ],
            "reports": [
                {
                    "id": REP_REPORT_ID,
                    "source_id": PRIMARY_SOURCE_ID,
                    "name": "Sales Rep Performance",
                    "kind": "rep_performance",
                    "source_config": report_config,
                    "runtime": {
                        "date_mode": str(settings.get("data_date_mode") or "current_month"),
                        "date_start": str(settings.get("data_date_start") or ""),
                        "date_end": str(settings.get("data_date_end") or ""),
                    },
                },
                {
                    "id": PRODUCT_REPORT_ID,
                    "source_id": PRIMARY_SOURCE_ID,
                    "name": "Close Rate by Product",
                    "kind": "product_close",
                    "source_config": {},
                    "runtime": {"market": str(settings.get("product_market") or "Olympia")},
                },
            ],
        }

    def ensure(self, settings):
        current = self._read()
        if current is None:
            current = self.defaults(settings)
            self._write(current)
        return current

    def get(self, settings=None):
        value = self._read()
        if value is None:
            return self.defaults(settings or {})
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

    def source(self, source_id, settings=None):
        key = str(source_id or "")
        return next((dict(row) for row in self.get(settings)["sources"] if str(row.get("id")) == key), None)

    def report(self, report_id, settings=None):
        key = str(report_id or "")
        return next((dict(row) for row in self.get(settings)["reports"] if str(row.get("id")) == key), None)
