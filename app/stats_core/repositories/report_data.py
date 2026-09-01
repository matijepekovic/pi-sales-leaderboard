"""Persistent snapshots for generic report data.

Known product domains keep their purpose-built tables. Generic reports use one
JSON snapshot per report so adding a source/report does not require changing the
SQLite schema.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")


class ReportDataRepository:
    def __init__(self, data_root):
        self.root = Path(data_root) / "report-data"

    @staticmethod
    def _name(report_id):
        value = _SAFE.sub("-", str(report_id or "").strip()).strip("-.")
        if not value:
            raise ValueError("Report id is required.")
        return value + ".json"

    def _path(self, report_id):
        return self.root / self._name(report_id)

    def read(self, report_id):
        path = self._path(report_id)
        if not path.is_file():
            return {"fields": [], "rows": [], "meta": {}}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {"fields": [], "rows": [], "meta": {}}
        if not isinstance(value, dict):
            return {"fields": [], "rows": [], "meta": {}}
        return {
            "fields": list(value.get("fields") or []),
            "rows": [dict(row) for row in (value.get("rows") or []) if isinstance(row, dict)],
            "meta": dict(value.get("meta") or {}),
        }

    def replace(self, report_id, fields, rows, meta=None):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(report_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        value = {
            "fields": list(fields or []),
            "rows": [dict(row) for row in (rows or []) if isinstance(row, dict)],
            "meta": dict(meta or {}),
        }
        tmp.write_text(json.dumps(value, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(path)
        return value

    def delete(self, report_id):
        path = self._path(report_id)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed
