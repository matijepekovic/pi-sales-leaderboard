"""Screen composition over normalized Reports and Display Values."""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError
from stats_core.screens.templates import get_template, list_templates


_GROUPED_TEMPLATES = {"per_team", "team_vs_team", "all_teams"}


class ScreenService:
    """Owns user-created Screens and the built-in Screen template catalog.

    Screens choose Reports and Display Values. A Display Value owns the
    user-facing name for one normalized Report field; Screens never store or
    expose vendor field names as presentation labels.
    """

    def __init__(self, repos, reports, display_values):
        self.repos = repos
        self.reports = reports
        self.display_values = display_values

    def templates(self):
        return list_templates()

    def list(self):
        return sorted(self.repos.screens.list(), key=lambda item: str(item.get("name") or "").casefold())

    def get(self, screen_id):
        screen = self.repos.screens.get(str(screen_id or "").strip())
        if not screen:
            raise ValidationError("Screen not found.")
        return screen

    def _clean_tables(self, raw, report_ids):
        tables, seen = [], set()
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            report_id = str(item.get("report_id") or "").strip()
            if report_id not in report_ids or report_id in seen:
                continue
            seen.add(report_id)
            values = self.display_values.for_report(report_id)
            valid = {value["id"] for value in values}
            selected = [str(value) for value in (item.get("display_value_ids") or []) if str(value) in valid]
            if not selected:
                selected = [value["id"] for value in values[:8]]
            sort_value = str(item.get("sort_display_value_id") or "").strip()
            if sort_value not in valid:
                sort_value = ""
            direction = str(item.get("sort_direction") or "desc").lower()
            if direction not in {"asc", "desc"}:
                direction = "desc"
            try:
                limit = min(max(int(item.get("limit") or 100), 1), 500)
            except Exception:
                limit = 100
            tables.append({
                "report_id": report_id,
                "display_value_ids": list(dict.fromkeys(selected))[:50],
                "sort_display_value_id": sort_value,
                "sort_direction": direction,
                "limit": limit,
            })
        for report_id in report_ids:
            if report_id in seen:
                continue
            values = self.display_values.for_report(report_id)
            tables.append({
                "report_id": report_id,
                "display_value_ids": [value["id"] for value in values[:8]],
                "sort_display_value_id": "",
                "sort_direction": "desc",
                "limit": 100,
            })
        return tables

    def _clean_grouping(self, incoming, report_ids, template_key):
        if template_key not in _GROUPED_TEMPLATES:
            return "", []
        group_by = str(incoming.get("group_by_display_value_id") or "").strip()
        if group_by:
            value = self.display_values.get(group_by)
            if value["report_id"] not in report_ids:
                raise ValidationError("Group By must use a Display Value from this Screen's Reports.")
        values = []
        for raw in incoming.get("group_values") if isinstance(incoming.get("group_values"), list) else []:
            text = str(raw if raw is not None else "").strip()
            if text and text not in values:
                values.append(text)
        max_values = 1 if template_key == "per_team" else 2 if template_key == "team_vs_team" else 100
        return group_by, values[:max_values]

    def _normalize(self, incoming, screen_id=None):
        incoming = incoming if isinstance(incoming, dict) else {}
        screen_id = str(screen_id or incoming.get("id") or "").strip() or f"screen-{uuid.uuid4().hex[:12]}"
        name = str(incoming.get("name") or "Untitled Screen").strip()[:120]
        if not name:
            raise ValidationError("Screen name is required.")

        template_key = str(incoming.get("template_key") or "").strip()
        if template_key and not get_template(template_key):
            raise ValidationError("Unknown Screen template.")

        report_ids = []
        for value in incoming.get("reports") if isinstance(incoming.get("reports"), list) else []:
            report_id = str(value or "").strip()
            if report_id and report_id not in report_ids:
                self.reports.get(report_id)
                report_ids.append(report_id)
        if not report_ids:
            raise ValidationError("Choose at least one Report for this Screen.")

        group_by, group_values = self._clean_grouping(incoming, set(report_ids), template_key)
        theme_mode = str(incoming.get("theme_mode") or "inherited").strip().lower()
        if theme_mode not in {"inherited", "custom"}:
            theme_mode = "inherited"

        return {
            "id": screen_id,
            "name": name,
            "template_key": template_key,
            "reports": report_ids[:20],
            "group_by_display_value_id": group_by,
            "group_values": group_values,
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

    def _section(self, table, rows=None, name_override=None):
        report_id = str(table.get("report_id") or "")
        report = self.reports.get(report_id)
        values = {value["id"]: value for value in self.display_values.for_report(report_id)}
        selected_ids = [value_id for value_id in table.get("display_value_ids") or [] if value_id in values]
        selected = [values[value_id] for value_id in selected_ids]
        section_rows = [dict(row) for row in (rows if rows is not None else self.reports.rows(report_id))]

        sort_value_id = str(table.get("sort_display_value_id") or "")
        sort_value = values.get(sort_value_id)
        if sort_value:
            field_key = sort_value["field_key"]
            section_rows.sort(
                key=lambda row: self._sort_value(row.get(field_key)),
                reverse=str(table.get("sort_direction") or "desc") == "desc",
            )

        limit = int(table.get("limit") or 100)
        fields = [
            {
                "display_value_id": value["id"],
                "key": value["field_key"],
                "label": value["name"],
                "type": value["type"],
            }
            for value in selected
        ]
        return {
            "report_id": report_id,
            "report_name": str(name_override or report.get("name") or report_id),
            "fields": fields,
            "rows": section_rows[:limit],
            "total_rows": len(section_rows),
            "sort_display_value_id": sort_value_id if sort_value else "",
            "sort_direction": str(table.get("sort_direction") or "desc"),
        }

    @staticmethod
    def _matches_group(raw, expected):
        return str(raw if raw is not None else "").strip().casefold() == str(expected).strip().casefold()

    def _template_sections(self, screen):
        key = str(screen.get("template_key") or "")
        tables = screen.get("tables") or []
        group_by_id = str(screen.get("group_by_display_value_id") or "")
        if key not in _GROUPED_TEMPLATES or not group_by_id:
            return [self._section(table) for table in tables]

        group_by = self.display_values.get(group_by_id)
        table = next((item for item in tables if str(item.get("report_id")) == group_by["report_id"]), None)
        if not table:
            return [self._section(item) for item in tables]

        available = self.display_values.values(group_by_id)
        selected = [value for value in screen.get("group_values") or [] if value in available]
        if key == "per_team":
            selected = (selected or available)[:1]
        elif key == "team_vs_team":
            selected = (selected or available)[:2]
        else:
            selected = selected or available

        rows = self.reports.rows(group_by["report_id"])
        sections = []
        for value in selected:
            grouped = [row for row in rows if self._matches_group(row.get(group_by["field_key"]), value)]
            sections.append(self._section(table, grouped, value))
        return sections or [self._section(item) for item in tables]

    def render_definition(self, screen):
        template = get_template(screen.get("template_key"))
        group_by = None
        if screen.get("group_by_display_value_id"):
            try:
                group_by = self.display_values.get(screen["group_by_display_value_id"])
            except ValidationError:
                group_by = None
        return {
            "mode": "screen",
            "screen_id": screen["id"],
            "screen_name": screen["name"],
            "template_key": screen.get("template_key", ""),
            "layout": (template or {}).get("layout", "standard"),
            "theme_mode": screen.get("theme_mode", "inherited"),
            "group_by": group_by,
            "group_values": list(screen.get("group_values") or []),
            "sections": self._template_sections(screen),
        }

    def preview(self, incoming):
        return self.render_definition(self._normalize(incoming, screen_id="screen-preview"))

    def render(self, screen_id):
        return self.render_definition(self.get(screen_id))
