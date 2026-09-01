"""Screen composition over normalized Reports and reusable Display Filters."""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError


class ScreenService:
    """Owns user-created Screens.

    Screens choose Reports, reusable Filter ids, table presentation and theme
    policy. They never know how a Source retrieves data.
    """

    def __init__(self, repos, reports, filters):
        self.repos = repos
        self.reports = reports
        self.filters = filters

    def list(self):
        return sorted(self.repos.screens.list(), key=lambda item: str(item.get("name") or "").casefold())

    def get(self, screen_id):
        screen = self.repos.screens.get(str(screen_id or "").strip())
        if not screen:
            raise ValidationError("Screen not found.")
        return screen

    def _clean_filter_ids(self, raw):
        result = []
        for value in raw if isinstance(raw, list) else []:
            filter_id = str(value or "").strip()
            if not filter_id or filter_id in result:
                continue
            self.filters.get(filter_id)
            result.append(filter_id)
        return result[:100]

    def _clean_tables(self, raw, report_ids):
        tables, seen = [], set()
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            report_id = str(item.get("report_id") or "").strip()
            if report_id not in report_ids or report_id in seen:
                continue
            seen.add(report_id)
            fields = self.reports.fields(report_id)
            valid = {str(field.get("key") or "") for field in fields}
            columns = [str(value) for value in (item.get("columns") or []) if str(value) in valid]
            if not columns:
                columns = [str(field.get("key") or "") for field in fields[:8] if str(field.get("key") or "")]
            sort_field = str(item.get("sort_field") or "").strip()
            if sort_field not in valid:
                sort_field = ""
            direction = str(item.get("sort_direction") or "desc").lower()
            if direction not in {"asc", "desc"}:
                direction = "desc"
            try:
                limit = min(max(int(item.get("limit") or 100), 1), 500)
            except Exception:
                limit = 100
            tables.append({
                "report_id": report_id,
                "columns": list(dict.fromkeys(columns))[:50],
                "sort_field": sort_field,
                "sort_direction": direction,
                "limit": limit,
            })
        for report_id in report_ids:
            if report_id in seen:
                continue
            fields = self.reports.fields(report_id)
            tables.append({
                "report_id": report_id,
                "columns": [str(field.get("key") or "") for field in fields[:8] if str(field.get("key") or "")],
                "sort_field": "",
                "sort_direction": "desc",
                "limit": 100,
            })
        return tables

    def _normalize(self, incoming, screen_id=None):
        incoming = incoming if isinstance(incoming, dict) else {}
        screen_id = str(screen_id or incoming.get("id") or "").strip() or f"screen-{uuid.uuid4().hex[:12]}"
        name = str(incoming.get("name") or "Untitled Screen").strip()[:120]
        if not name:
            raise ValidationError("Screen name is required.")

        report_ids = []
        for value in incoming.get("reports") if isinstance(incoming.get("reports"), list) else []:
            report_id = str(value or "").strip()
            if report_id and report_id not in report_ids:
                self.reports.get(report_id)
                report_ids.append(report_id)
        if not report_ids:
            raise ValidationError("Choose at least one Report for this Screen.")

        theme_mode = str(incoming.get("theme_mode") or "inherited").strip().lower()
        if theme_mode not in {"inherited", "custom"}:
            theme_mode = "inherited"

        return {
            "id": screen_id,
            "name": name,
            "reports": report_ids[:20],
            "filter_ids": self._clean_filter_ids(incoming.get("filter_ids")),
            "tables": self._clean_tables(incoming.get("tables"), set(report_ids)),
            "theme_mode": theme_mode,
        }

    def save(self, incoming):
        screen = self._normalize(incoming)
        self.repos.screens.save(screen)
        self.repos.meta.bump("settings_version")
        return screen

    def delete(self, screen_id):
        screen_id = str(screen_id or "").strip()
        if not self.repos.screens.delete(screen_id):
            raise ValidationError("Screen not found.")
        self.repos.meta.bump("settings_version")
        return True

    @staticmethod
    def _sort_value(value):
        if isinstance(value, (int, float)):
            return (0, float(value))
        text = str(value if value is not None else "").strip()
        try:
            return (0, float(text.replace(",", "").replace("$", "").replace("%", "")))
        except ValueError:
            return (1, text.casefold())

    def _section(self, screen, table):
        report_id = str(table.get("report_id") or "")
        report = self.reports.get(report_id)
        fields = self.reports.fields(report_id)
        by_key = {str(field.get("key") or ""): dict(field) for field in fields}
        columns = [key for key in table.get("columns") or [] if key in by_key]
        rows = self.filters.apply(report_id, self.reports.rows(report_id), screen.get("filter_ids") or [])
        sort_field = str(table.get("sort_field") or "")
        if sort_field in by_key:
            rows.sort(
                key=lambda row: self._sort_value(row.get(sort_field)),
                reverse=str(table.get("sort_direction") or "desc") == "desc",
            )
        limit = int(table.get("limit") or 100)
        return {
            "report_id": report_id,
            "report_name": str(report.get("name") or report_id),
            "fields": [by_key[key] for key in columns],
            "rows": rows[:limit],
            "total_rows": len(rows),
            "sort_field": sort_field,
            "sort_direction": str(table.get("sort_direction") or "desc"),
        }

    def _filter_payload(self, screen):
        result = []
        for filter_id in screen.get("filter_ids") or []:
            try:
                item = self.filters.get(filter_id)
            except ValidationError:
                continue
            result.append({"id": item["id"], "name": item["name"]})
        return result

    def render_definition(self, screen):
        sections = [self._section(screen, table) for table in screen.get("tables") or []]
        return {
            "mode": "screen",
            "screen_id": screen["id"],
            "screen_name": screen["name"],
            "theme_mode": screen.get("theme_mode", "inherited"),
            "display_filters": self._filter_payload(screen),
            "sections": sections,
        }

    def preview(self, incoming):
        return self.render_definition(self._normalize(incoming, screen_id="screen-preview"))

    def render(self, screen_id):
        return self.render_definition(self.get(screen_id))
