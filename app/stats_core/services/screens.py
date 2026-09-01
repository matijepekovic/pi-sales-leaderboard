"""Screen composition over normalized report and Filter contracts."""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError


class ScreenService:
    def __init__(self, repos, reports, filters, builtin_registry, organization):
        self.repos = repos
        self.reports = reports
        self.filters = filters
        self.builtin = builtin_registry
        self.organization = organization

    def _builtin_definitions(self):
        rows = [
            {"id": "builtin:whole_office", "name": "Whole Office", "kind": "builtin", "mode": "whole_office", "theme_mode": "inherited"},
            {"id": "builtin:team_vs_team", "name": "Team vs Team", "kind": "builtin", "mode": "team_vs_team", "theme_mode": "inherited"},
            {"id": "builtin:all_teams", "name": "All Teams", "kind": "builtin", "mode": "all_teams", "theme_mode": "inherited"},
            {"id": "builtin:product_close", "name": "Product Close", "kind": "builtin", "mode": "product_close", "theme_mode": "inherited"},
        ]
        for team in self.organization.definitions_for_api():
            name = str(team.get("name") or "").strip()
            if name:
                rows.append({
                    "id": f"builtin:per_team:{name}",
                    "name": name,
                    "kind": "builtin",
                    "mode": f"per_team::{name}",
                    "theme_mode": "inherited",
                })
        return rows

    def list(self):
        return self._builtin_definitions() + self.repos.screens.list()

    def modes(self):
        return self.builtin.modes()

    def cycle_views(self):
        return self.builtin.cycle_views()

    def render_mode(self, raw_mode=None, **kwargs):
        return self.builtin.render(raw_mode, **kwargs)

    def get(self, screen_id):
        key = str(screen_id or "").strip()
        builtin = next((row for row in self._builtin_definitions() if row["id"] == key), None)
        if builtin:
            return builtin
        screen = self.repos.screens.get(key)
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
        return result[:30]

    def _clean_display_mappings(self, raw, report_ids, filter_ids):
        mappings, seen = [], set()
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            filter_id = str(item.get("filter_id") or "").strip()
            report_id = str(item.get("report_id") or "").strip()
            field = str(item.get("field") or "").strip()
            if filter_id not in filter_ids or report_id not in report_ids or not field:
                continue
            valid = {str(value.get("key") or "") for value in self.reports.fields(report_id)}
            if field not in valid:
                continue
            key = (filter_id, report_id)
            if key in seen:
                continue
            seen.add(key)
            mappings.append({"filter_id": filter_id, "report_id": report_id, "field": field})
        return mappings[:100]

    def _clean_filter_values(self, raw, filter_ids):
        raw = raw if isinstance(raw, dict) else {}
        return {
            filter_id: str(raw.get(filter_id) or "").strip()[:300]
            for filter_id in filter_ids
        }

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
            valid = {str(field.get("key")) for field in fields}
            columns = [str(value) for value in (item.get("columns") or []) if str(value) in valid]
            if not columns:
                columns = [str(field.get("key")) for field in fields[:8]]
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
                "columns": list(dict.fromkeys(columns))[:30],
                "sort_field": sort_field,
                "sort_direction": direction,
                "limit": limit,
            })
        for report_id in report_ids:
            if report_id not in seen:
                fields = self.reports.fields(report_id)
                tables.append({
                    "report_id": report_id,
                    "columns": [str(field.get("key")) for field in fields[:8]],
                    "sort_field": "",
                    "sort_direction": "desc",
                    "limit": 100,
                })
        return tables

    def _normalize(self, incoming, screen_id=None):
        incoming = incoming if isinstance(incoming, dict) else {}
        screen_id = str(screen_id or incoming.get("id") or "").strip() or f"screen-{uuid.uuid4().hex[:12]}"
        if screen_id.startswith("builtin:"):
            raise ValidationError("Built-in screens cannot be replaced.")
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

        filter_ids = self._clean_filter_ids(incoming.get("filter_ids"))
        mappings = self._clean_display_mappings(
            incoming.get("display_filter_mappings"), set(report_ids), set(filter_ids)
        )
        filter_values = self._clean_filter_values(incoming.get("filter_values"), filter_ids)
        theme_mode = str(incoming.get("theme_mode") or "inherited").strip().lower()
        if theme_mode not in {"inherited", "custom"}:
            theme_mode = "inherited"

        return {
            "id": screen_id,
            "name": name,
            "kind": "custom",
            "reports": report_ids[:10],
            "filter_ids": filter_ids,
            "display_filter_mappings": mappings,
            "filter_values": filter_values,
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
        if screen_id.startswith("builtin:"):
            raise ValidationError("Built-in screens cannot be deleted.")
        if not self.repos.screens.delete(screen_id):
            raise ValidationError("Screen not found.")
        state = self.repos.display.get()
        if state["active_screen_id"] == screen_id:
            state["active_screen_id"] = "builtin:whole_office"
        state["rotation_screen_ids"] = [item for item in state["rotation_screen_ids"] if item != screen_id]
        self.repos.display.save(state)
        self.repos.meta.bump("settings_version")
        return True

    @staticmethod
    def _same(value, expected):
        return str(value if value is not None else "").strip().casefold() == str(expected or "").strip().casefold()

    @staticmethod
    def _sort_value(value):
        if isinstance(value, (int, float)):
            return (0, float(value))
        text = str(value if value is not None else "").strip()
        try:
            return (0, float(text.replace(",", "").replace("$", "").replace("%", "")))
        except ValueError:
            return (1, text.casefold())

    def _active_mappings(self, screen, report_id, effective_values):
        result = []
        for mapping in screen.get("display_filter_mappings") or []:
            if str(mapping.get("report_id") or "") != report_id:
                continue
            filter_id = str(mapping.get("filter_id") or "")
            value = str(effective_values.get(filter_id) or "").strip()
            if value and value.casefold() != "all":
                result.append((mapping, value))
        return result

    def _section(self, screen, table, effective_values):
        report_id = str(table.get("report_id") or "")
        report = self.reports.get(report_id)
        fields = self.reports.fields(report_id)
        by_key = {str(field.get("key")): dict(field) for field in fields}
        columns = [key for key in table.get("columns") or [] if key in by_key]
        active_mappings = self._active_mappings(screen, report_id, effective_values)
        rows = []
        for raw in self.reports.rows(report_id):
            if all(self._same(raw.get(mapping["field"]), value) for mapping, value in active_mappings):
                rows.append(dict(raw))
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

    def _winning_team(self, sections):
        definitions = self.organization.definitions_for_api()
        by_name = {str(item.get("name") or "").strip().casefold(): item for item in definitions}
        for section in sections:
            for row in section.get("rows") or []:
                team_id = row.get("assigned_team_id") or row.get("team_id")
                if team_id:
                    try:
                        tid = int(team_id)
                    except Exception:
                        tid = None
                    if tid:
                        match = next((item for item in definitions if int(item.get("team_id") or 0) == tid), None)
                        if match:
                            return {"team_id": tid, "team_name": match.get("name") or ""}
                name = str(row.get("team") or "").strip()
                match = by_name.get(name.casefold()) if name else None
                if match:
                    return {"team_id": int(match["team_id"]), "team_name": match["name"]}
        return None

    def _filter_payload(self, screen, effective_values):
        definitions = {item["id"]: item for item in self.filters.list()}
        mappings = screen.get("display_filter_mappings") or []
        return [
            {
                "id": filter_id,
                "name": str(definitions.get(filter_id, {}).get("name") or filter_id),
                "value": str(effective_values.get(filter_id) or ""),
                "mappings": [dict(item) for item in mappings if str(item.get("filter_id")) == filter_id],
            }
            for filter_id in screen.get("filter_ids") or []
        ]

    def render_definition(self, screen, filter_values=None):
        effective_values = dict(screen.get("filter_values") or {})
        if isinstance(filter_values, dict):
            for filter_id in screen.get("filter_ids") or []:
                if filter_id in filter_values:
                    effective_values[filter_id] = str(filter_values[filter_id] or "").strip()[:300]
        sections = [
            self._section(screen, table, effective_values)
            for table in screen.get("tables") or []
        ]
        return {
            "mode": "custom_screen",
            "mode_label": screen["name"],
            "screen_id": screen["id"],
            "screen_name": screen["name"],
            "theme_mode": screen.get("theme_mode", "inherited"),
            "winning_team": self._winning_team(sections),
            "display_filters": self._filter_payload(screen, effective_values),
            "sections": sections,
        }

    def preview(self, incoming):
        return self.render_definition(self._normalize(incoming, screen_id="screen-preview"))

    def render(self, screen_id, filter_values=None, **kwargs):
        screen = self.get(screen_id)
        if screen.get("kind") == "builtin":
            return self.builtin.render(screen.get("mode"), **kwargs)
        return self.render_definition(screen, filter_values=filter_values)
