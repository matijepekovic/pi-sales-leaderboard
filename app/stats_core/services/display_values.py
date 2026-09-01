"""User-facing names for normalized Report fields."""
from __future__ import annotations

import hashlib

from stats_core.errors import ValidationError


class DisplayValueService:
    """Turns every normalized Report field into a user-manageable Display Value."""

    def __init__(self, repos, reports):
        self.repos = repos
        self.reports = reports

    @staticmethod
    def _id(report_id, field_key):
        raw = f"{report_id}\0{field_key}".encode("utf-8")
        return f"display-value-{hashlib.sha1(raw).hexdigest()[:20]}"

    @staticmethod
    def _source_name(field):
        return str(field.get("label") or field.get("key") or "").strip()

    def _from_field(self, report, field, aliases):
        report_id = str(report.get("id") or "")
        field_key = str(field.get("key") or "")
        value_id = self._id(report_id, field_key)
        source_name = self._source_name(field)
        return {
            "id": value_id,
            "report_id": report_id,
            "report_name": str(report.get("name") or report_id),
            "field_key": field_key,
            "source_name": source_name,
            "name": str(aliases.get(value_id) or source_name),
            "type": str(field.get("type") or "text"),
        }

    def for_report(self, report_id):
        report = self.reports.get(report_id)
        aliases = self.repos.display_values.list_names()
        return [
            self._from_field(report, field, aliases)
            for field in self.reports.fields(report_id)
            if str(field.get("key") or "").strip()
        ]

    def list(self, report_id=None):
        if report_id:
            return self.for_report(report_id)
        result = []
        aliases = self.repos.display_values.list_names()
        for report in self.reports.list():
            for field in report.get("fields") or []:
                if str(field.get("key") or "").strip():
                    result.append(self._from_field(report, field, aliases))
        return result

    def get(self, display_value_id):
        key = str(display_value_id or "").strip()
        for item in self.list():
            if item["id"] == key:
                return item
        raise ValidationError("Display Value not found.")

    def rename(self, display_value_id, incoming):
        item = self.get(display_value_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        name = str(incoming.get("name") or "").strip()[:120]
        if not name:
            raise ValidationError("Display Value name is required.")
        if name == item["source_name"]:
            self.repos.display_values.delete_name(item["id"])
        else:
            self.repos.display_values.save_name(item["id"], name)
        self.repos.meta.bump("settings_version")
        return {**item, "name": name}

    def values(self, display_value_id, limit=500):
        item = self.get(display_value_id)
        try:
            limit = min(max(int(limit), 1), 2000)
        except Exception:
            limit = 500
        values, seen = [], set()
        for row in self.reports.rows(item["report_id"]):
            raw = row.get(item["field_key"])
            if raw is None:
                continue
            text = str(raw).strip()
            if not text:
                continue
            folded = text.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            values.append(text)
            if len(values) >= limit:
                break
        values.sort(key=str.casefold)
        return values
