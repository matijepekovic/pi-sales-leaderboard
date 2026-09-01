"""Screen composition over normalized report contracts."""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError

_OPERATORS = {"equals", "not_equals", "contains", "not_contains"}


class ScreenService:
    def __init__(self, repos, reports, builtin_registry, organization):
        self.repos = repos
        self.reports = reports
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
                    "id": f"builtin:per_team:{name}", "name": name, "kind": "builtin",
                    "mode": f"per_team::{name}", "theme_mode": "inherited",
                })
        return rows

    def list(self): return self._builtin_definitions() + self.repos.screens.list()

    def get(self, screen_id):
        key = str(screen_id or "").strip()
        builtin = next((row for row in self._builtin_definitions() if row["id"] == key), None)
        if builtin: return builtin
        screen = self.repos.screens.get(key)
        if not screen: raise ValidationError("Screen not found.")
        return screen

    @staticmethod
    def _clean_filters(raw):
        rows = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict): continue
            field = str(item.get("field") or "").strip()[:200]
            if not field: continue
            scope = str(item.get("scope") or "screen").strip().lower()
            if scope not in {"screen", "report"}: scope = "screen"
            operator = str(item.get("operator") or "equals").strip().lower()
            if operator not in _OPERATORS: operator = "equals"
            rows.append({
                "scope": scope,
                "report_id": str(item.get("report_id") or "").strip() if scope == "report" else "",
                "field": field, "operator": operator, "value": str(item.get("value") or "")[:300],
            })
        return rows[:50]

    def _clean_tables(self, raw, report_ids):
        tables, seen = [], set()
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict): continue
            report_id = str(item.get("report_id") or "").strip()
            if report_id not in report_ids or report_id in seen: continue
            seen.add(report_id)
            fields = self.reports.fields(report_id)
            valid = {str(field.get("key")) for field in fields}
            columns = [str(value) for value in (item.get("columns") or []) if str(value) in valid]
            if not columns: columns = [str(field.get("key")) for field in fields[:8]]
            sort_field = str(item.get("sort_field") or "").strip()
            if sort_field not in valid: sort_field = ""
            direction = str(item.get("sort_direction") or "desc").lower()
            if direction not in {"asc", "desc"}: direction = "desc"
            try: limit = min(max(int(item.get("limit") or 100), 1), 500)
            except Exception: limit = 100
            tables.append({
                "report_id": report_id, "columns": list(dict.fromkeys(columns))[:30],
                "sort_field": sort_field, "sort_direction": direction, "limit": limit,
            })
        for report_id in report_ids:
            if report_id not in seen:
                fields = self.reports.fields(report_id)
                tables.append({
                    "report_id": report_id,
                    "columns": [str(field.get("key")) for field in fields[:8]],
                    "sort_field": "", "sort_direction": "desc", "limit": 100,
                })
        return tables

    def _normalize(self, incoming, screen_id=None):
        incoming = incoming if isinstance(incoming, dict) else {}
        screen_id = str(screen_id or incoming.get("id") or "").strip() or f"screen-{uuid.uuid4().hex[:12]}"
        if screen_id.startswith("builtin:"): raise ValidationError("Built-in screens cannot be replaced.")
        name = str(incoming.get("name") or "Untitled Screen").strip()[:120]
        if not name: raise ValidationError("Screen name is required.")
        report_ids = []
        for value in incoming.get("reports") if isinstance(incoming.get("reports"), list) else []:
            report_id = str(value or "").strip()
            if report_id and report_id not in report_ids:
                self.reports.get(report_id)
                report_ids.append(report_id)
        if not report_ids: raise ValidationError("Choose at least one report for this screen.")
        theme_mode = str(incoming.get("theme_mode") or "inherited").strip().lower()
        if theme_mode not in {"inherited", "custom"}: theme_mode = "inherited"
        return {
            "id": screen_id, "name": name, "kind": "custom", "reports": report_ids[:10],
            "filters": self._clean_filters(incoming.get("filters")),
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
        if screen_id.startswith("builtin:"): raise ValidationError("Built-in screens cannot be deleted.")
        if not self.repos.screens.delete(screen_id): raise ValidationError("Screen not found.")
        state = self.repos.display.get()
        if state["active_screen_id"] == screen_id: state["active_screen_id"] = "builtin:whole_office"
        state["rotation_screen_ids"] = [item for item in state["rotation_screen_ids"] if item != screen_id]
        self.repos.display.save(state)
        self.repos.meta.bump("settings_version")
        return True

    @staticmethod
    def _match(value, operator, expected):
        left, right = str(value if value is not None else ""), str(expected if expected is not None else "")
        if operator == "equals": return left.casefold() == right.casefold()
        if operator == "not_equals": return left.casefold() != right.casefold()
        if operator == "contains": return right.casefold() in left.casefold()
        if operator == "not_contains": return right.casefold() not in left.casefold()
        return True

    def _filters_for(self, screen, report_id, field_keys):
        result = []
        for item in screen.get("filters") or []:
            if str(item.get("field")) not in field_keys: continue
            if str(item.get("scope") or "screen") == "report" and str(item.get("report_id") or "") != report_id: continue
            result.append(item)
        return result

    @staticmethod
    def _sort_value(value):
        if isinstance(value, (int, float)): return (0, float(value))
        text = str(value if value is not None else "").strip()
        try: return (0, float(text.replace(",", "").replace("$", "").replace("%", "")))
        except ValueError: return (1, text.casefold())

    def _section(self, screen, table):
        report_id = str(table.get("report_id") or "")
        report = self.reports.get(report_id)
        fields = self.reports.fields(report_id)
        by_key = {str(field.get("key")): dict(field) for field in fields}
        columns = [key for key in table.get("columns") or [] if key in by_key]
        filters = self._filters_for(screen, report_id, set(by_key))
        rows = [
            dict(raw) for raw in self.reports.rows(report_id)
            if all(self._match(raw.get(item["field"]), item["operator"], item["value"]) for item in filters)
        ]
        sort_field = str(table.get("sort_field") or "")
        if sort_field in by_key:
            rows.sort(key=lambda row: self._sort_value(row.get(sort_field)), reverse=str(table.get("sort_direction") or "desc") == "desc")
        limit = int(table.get("limit") or 100)
        return {
            "report_id": report_id, "report_name": str(report.get("name") or report_id),
            "fields": [by_key[key] for key in columns], "rows": rows[:limit], "total_rows": len(rows),
            "sort_field": sort_field, "sort_direction": str(table.get("sort_direction") or "desc"),
        }

    def _winning_team(self, sections):
        definitions = self.organization.definitions_for_api()
        by_name = {str(item.get("name") or "").strip().casefold(): item for item in definitions}
        for section in sections:
            for row in section.get("rows") or []:
                team_id = row.get("assigned_team_id") or row.get("team_id")
                if team_id:
                    try: tid = int(team_id)
                    except Exception: tid = None
                    if tid:
                        match = next((item for item in definitions if int(item.get("team_id") or 0) == tid), None)
                        if match: return {"team_id": tid, "team_name": match.get("name") or ""}
                name = str(row.get("team") or "").strip()
                match = by_name.get(name.casefold()) if name else None
                if match: return {"team_id": int(match["team_id"]), "team_name": match["name"]}
        return None

    def render_definition(self, screen):
        sections = [self._section(screen, table) for table in screen.get("tables") or []]
        return {
            "mode": "custom_screen", "mode_label": screen["name"],
            "screen_id": screen["id"], "screen_name": screen["name"],
            "theme_mode": screen.get("theme_mode", "inherited"),
            "winning_team": self._winning_team(sections), "sections": sections,
        }

    def preview(self, incoming):
        return self.render_definition(self._normalize(incoming, screen_id="screen-preview"))

    def render(self, screen_id, **kwargs):
        screen = self.get(screen_id)
        if screen.get("kind") == "builtin": return self.builtin.render(screen.get("mode"), **kwargs)
        return self.render_definition(screen)
