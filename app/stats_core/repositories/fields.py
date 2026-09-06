"""Persistence for Report-owned custom and generated Field definitions."""
from __future__ import annotations

import json

from stats_core.storage import sqlite


_FIELDS_KEY = "field_definitions"
_MATCHES_KEY = "field_matching_rules"


class FieldRepository:
    """Store Field definitions independently from Report snapshots."""

    @staticmethod
    def _read_all():
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (_FIELDS_KEY,)
            ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(row["value"])
        except Exception:
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            str(report_id): [dict(item) for item in items if isinstance(item, dict)]
            for report_id, items in value.items()
            if isinstance(items, list)
        }

    @staticmethod
    def _write_all(value):
        clean = {
            str(report_id): [dict(item) for item in items if isinstance(item, dict)]
            for report_id, items in (value or {}).items()
            if isinstance(items, list)
        }
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_FIELDS_KEY, json.dumps(clean)),
            )
        return clean

    def list(self, report_id):
        return [dict(item) for item in self._read_all().get(str(report_id or ""), [])]

    def get(self, report_id, field_key):
        key = str(field_key or "")
        return next(
            (item for item in self.list(report_id) if str(item.get("key") or "") == key),
            None,
        )

    def save(self, report_id, definition):
        report_id = str(report_id or "")
        definition = dict(definition or {})
        key = str(definition.get("key") or "")
        value = self._read_all()
        rows = [item for item in value.get(report_id, []) if str(item.get("key") or "") != key]
        rows.append(definition)
        value[report_id] = rows
        self._write_all(value)
        return definition

    def delete(self, report_id, field_key):
        report_id, field_key = str(report_id or ""), str(field_key or "")
        value = self._read_all()
        rows = value.get(report_id, [])
        kept = [item for item in rows if str(item.get("key") or "") != field_key]
        if len(kept) == len(rows):
            return False
        if kept:
            value[report_id] = kept
        else:
            value.pop(report_id, None)
        self._write_all(value)
        return True

    def delete_report(self, report_id):
        report_id = str(report_id or "")
        value = self._read_all()
        existed = report_id in value
        value.pop(report_id, None)
        if existed:
            self._write_all(value)
        return existed

    @staticmethod
    def matching_rules():
        """Explicit, reusable Field relationships; reading never creates a rule."""
        with sqlite.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (_MATCHES_KEY,)).fetchone()
        try:
            value = json.loads(row["value"]) if row else []
        except (TypeError, ValueError):
            value = []
        return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _write_matching_rules(rules):
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_MATCHES_KEY, json.dumps(rules)),
            )

    def save_matching_rule(self, rule):
        rules = [item for item in self.matching_rules() if item.get("id") != rule["id"]]
        rules.append(dict(rule))
        self._write_matching_rules(rules)
        return dict(rule)

    def delete_matching_rule(self, rule_id):
        rules = self.matching_rules()
        kept = [item for item in rules if item.get("id") != rule_id]
        if len(kept) == len(rules):
            return False
        self._write_matching_rules(kept)
        return True
