"""User-manageable Display Filters over normalized Report data.

A Display Filter owns the filtering rule itself. Screens only select Filter ids.
Rules target normalized Report fields, never source/vendor structures.
"""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError

OPERATORS = ("equals", "not_equals", "contains", "not_contains")


class FilterService:
    def __init__(self, repos, reports):
        self.repos = repos
        self.reports = reports

    def list(self):
        return sorted(
            [self._normalized_saved(item) for item in self.repos.filters.list()],
            key=lambda item: str(item.get("name") or "").casefold(),
        )

    def get(self, filter_id):
        item = self.repos.filters.get(str(filter_id or "").strip())
        if not item:
            raise ValidationError("Filter not found.")
        return self._normalized_saved(item)

    @staticmethod
    def _normalized_saved(item):
        item = item if isinstance(item, dict) else {}
        return {
            "id": str(item.get("id") or "").strip(),
            "name": str(item.get("name") or "").strip(),
            "rules": [dict(rule) for rule in (item.get("rules") or []) if isinstance(rule, dict)],
        }

    def _clean_rule(self, raw):
        raw = raw if isinstance(raw, dict) else {}
        report_id = str(raw.get("report_id") or "").strip()
        field = str(raw.get("field") or "").strip()
        operator = str(raw.get("operator") or "equals").strip().lower()
        value = str(raw.get("value") if raw.get("value") is not None else "").strip()[:500]
        if not report_id:
            raise ValidationError("Choose a Report for every Filter rule.")
        if not field:
            raise ValidationError("Choose a field for every Filter rule.")
        if operator not in OPERATORS:
            raise ValidationError("Unsupported Filter operator.")
        report = self.reports.get(report_id)
        valid_fields = {str(item.get("key") or "") for item in self.reports.fields(report_id)}
        if field not in valid_fields:
            raise ValidationError(
                f"Field '{field}' is not available in Report '{report.get('name') or report_id}'."
            )
        return {
            "report_id": report_id,
            "field": field,
            "operator": operator,
            "value": value,
        }

    def _normalize(self, incoming, filter_id=None, validate_unique=True):
        incoming = incoming if isinstance(incoming, dict) else {}
        filter_id = str(filter_id or incoming.get("id") or "").strip() or f"filter-{uuid.uuid4().hex[:12]}"
        name = str(incoming.get("name") or "").strip()[:120]
        if not name:
            raise ValidationError("Filter name is required.")
        if validate_unique:
            for item in self.repos.filters.list():
                if str(item.get("id")) != filter_id and str(item.get("name") or "").strip().casefold() == name.casefold():
                    raise ValidationError("A Filter with that name already exists.")
        rules = [self._clean_rule(rule) for rule in (incoming.get("rules") or []) if isinstance(rule, dict)]
        if not rules:
            raise ValidationError("Add at least one rule to this Filter.")
        return {"id": filter_id, "name": name, "rules": rules[:100]}

    def save(self, incoming):
        saved = self.repos.filters.save(self._normalize(incoming))
        self.repos.meta.bump("settings_version")
        return saved

    def delete(self, filter_id):
        filter_id = str(filter_id or "").strip()
        for screen in self.repos.screens.list():
            if filter_id in [str(value) for value in (screen.get("filter_ids") or [])]:
                raise ValidationError("Remove this Filter from its Screens before deleting it.")
        if not self.repos.filters.delete(filter_id):
            raise ValidationError("Filter not found.")
        self.repos.meta.bump("settings_version")
        return True

    @staticmethod
    def _matches(value, operator, expected):
        actual = str(value if value is not None else "").strip().casefold()
        expected = str(expected if expected is not None else "").strip().casefold()
        if operator == "equals":
            return actual == expected
        if operator == "not_equals":
            return actual != expected
        if operator == "contains":
            return expected in actual
        if operator == "not_contains":
            return expected not in actual
        return False

    def apply(self, report_id, rows, filter_ids):
        selected = []
        for filter_id in filter_ids or []:
            item = self.repos.filters.get(str(filter_id or "").strip())
            if not item:
                continue
            relevant = [
                rule for rule in (item.get("rules") or [])
                if isinstance(rule, dict) and str(rule.get("report_id") or "") == str(report_id)
            ]
            if relevant:
                selected.append(relevant)
        if not selected:
            return [dict(row) for row in (rows or [])]
        result = []
        for row in rows or []:
            if all(
                all(self._matches(row.get(rule.get("field")), rule.get("operator"), rule.get("value")) for rule in rules)
                for rules in selected
            ):
                result.append(dict(row))
        return result

    def preview(self, incoming, row_limit=50):
        definition = self._normalize(incoming, filter_id="filter-preview", validate_unique=False)
        report_ids = []
        for rule in definition["rules"]:
            report_id = rule["report_id"]
            if report_id not in report_ids:
                report_ids.append(report_id)
        result = []
        for report_id in report_ids:
            report = self.reports.get(report_id)
            rows = self.reports.rows(report_id)
            matching = self._apply_definition(report_id, rows, definition)
            result.append({
                "report_id": report_id,
                "report_name": str(report.get("name") or report_id),
                "fields": self.reports.fields(report_id),
                "total_rows": len(rows),
                "matched_rows": len(matching),
                "rows": matching[:max(1, min(int(row_limit or 50), 100))],
            })
        return {"filter": definition, "reports": result}

    def _apply_definition(self, report_id, rows, definition):
        rules = [
            rule for rule in definition.get("rules") or []
            if str(rule.get("report_id") or "") == str(report_id)
        ]
        if not rules:
            return [dict(row) for row in rows or []]
        return [
            dict(row) for row in rows or []
            if all(self._matches(row.get(rule["field"]), rule["operator"], rule["value"]) for rule in rules)
        ]
