"""Persistent snapshots for generic report data.

Known product domains keep their purpose-built tables. Generic reports use one
JSON snapshot per report so adding a source/report does not require changing the
SQLite schema.
"""
from __future__ import annotations

import json
import re
import uuid
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
        return self._read_path(path)

    @staticmethod
    def _read_path(path):
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
        path = self._path(report_id)
        return self._replace_path(path, fields, rows, meta)

    @staticmethod
    def _replace_path(path, fields, rows, meta=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex}.tmp")
        value = {
            "fields": list(fields or []),
            "rows": [dict(row) for row in (rows or []) if isinstance(row, dict)],
            "meta": dict(meta or {}),
        }
        try:
            tmp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return value

    def _query_root(self, report_id):
        return self.root / "queries" / self._name(report_id)[:-5]

    def _query_path(self, report_id, query_key):
        if not re.fullmatch(r"[a-f0-9]{64}", str(query_key or "")):
            raise ValueError("A valid query snapshot key is required.")
        return self._query_root(report_id) / (query_key + ".json")

    def read_query(self, report_id, query_key):
        return self._read_path(self._query_path(report_id, query_key))

    def replace_query(self, report_id, query_key, fields, rows, meta=None):
        return self._replace_path(self._query_path(report_id, query_key), fields, rows, meta)

    def list_queries(self, report_id):
        return [self._read_path(path) for path in self._query_root(report_id).glob("*.json")]

    def delete(self, report_id):
        path = self._path(report_id)
        existed = path.exists()
        path.unlink(missing_ok=True)
        query_root = self._query_root(report_id)
        for query in query_root.glob("*.json"):
            query.unlink()
        if query_root.is_dir() and not any(query_root.iterdir()):
            query_root.rmdir()
        return existed
