"""Reusable table presentation for Reports and their named Groups."""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError


class TablePresetService:
    """Own table column order and default sorting shared across Screens."""

    def __init__(self, repos, reports, fields):
        self.repos = repos
        self.reports = reports
        self.fields = fields

    def list(self, report_id=None):
        report_id = str(report_id or "").strip()
        rows = self.repos.table_presets.list()
        if report_id:
            self.reports.get(report_id)
            rows = [item for item in rows if str(item.get("report_id") or "") == report_id]
        return sorted(
            (dict(item) for item in rows),
            key=lambda item: (
                str(item.get("report_id") or ""),
                str(item.get("name") or "").casefold(),
            ),
        )

    def get(self, preset_id):
        preset = self.repos.table_presets.get(str(preset_id or "").strip())
        if not preset:
            raise ValidationError("Table Preset not found.")
        return dict(preset)

    def _clean_values(self, report_id, incoming, default_all=True):
        self.reports.get(report_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        catalog = self.fields.fields(report_id)
        by_key = {str(field.get("key") or ""): field for field in catalog}
        columns = [
            str(value) for value in (incoming.get("columns") or [])
            if str(value) in by_key
        ]
        columns = list(dict.fromkeys(columns))[:50]
        if not columns and default_all:
            columns = [key for key in by_key][:50]
        if not columns:
            raise ValidationError("A Table Preset must contain at least one Field.")

        sort_field = str(incoming.get("sort_field") or "").strip()
        if sort_field not in by_key or by_key.get(sort_field, {}).get("kind") == "table":
            sort_field = ""
        direction = str(incoming.get("sort_direction") or "desc").strip().lower()
        if direction not in {"asc", "desc"}:
            direction = "desc"
        return {
            "columns": columns,
            "sort_field": sort_field,
            "sort_direction": direction,
        }

    def resolve(self, report_id, incoming, default_all=True):
        """Return effective table settings, resolving a linked preset if present."""
        incoming = incoming if isinstance(incoming, dict) else {}
        preset_id = str(incoming.get("preset_id") or "").strip()
        if not preset_id:
            return self._clean_values(report_id, incoming, default_all)
        preset = self.get(preset_id)
        if str(preset.get("report_id") or "") != str(report_id):
            raise ValidationError("This Table Preset belongs to a different Report.")
        return {**self._clean_values(report_id, preset, default_all), "preset_id": preset_id}

    def save(self, incoming, preset_id=""):
        incoming = incoming if isinstance(incoming, dict) else {}
        preset_id = str(preset_id or incoming.get("id") or "").strip() or f"table-preset-{uuid.uuid4().hex[:12]}"
        existing = self.repos.table_presets.get(preset_id) or {}
        report_id = str(incoming.get("report_id") or existing.get("report_id") or "").strip()
        if existing and str(existing.get("report_id") or "") != report_id:
            raise ValidationError("A Table Preset cannot be moved to another Report.")
        self.reports.get(report_id)
        name = str(incoming.get("name") or existing.get("name") or "").strip()[:120]
        if not name:
            raise ValidationError("Table Preset name is required.")
        if any(
            str(item.get("id") or "") != preset_id
            and str(item.get("report_id") or "") == report_id
            and str(item.get("name") or "").strip().casefold() == name.casefold()
            for item in self.repos.table_presets.list()
        ):
            raise ValidationError("This Report already has a Table Preset with that name.")
        values = self._clean_values(report_id, incoming, default_all=False)
        preset = {
            "id": preset_id,
            "report_id": report_id,
            "name": name,
            **values,
        }
        self.repos.table_presets.save(preset)
        self.repos.meta.bump("settings_version")
        return preset

    def delete(self, preset_id):
        preset = self.get(preset_id)
        used_by = [
            str(screen.get("name") or screen.get("id") or "Screen")
            for screen in self.repos.screens.list()
            if any(
                str(table.get("preset_id") or "") == str(preset_id)
                for table in screen.get("tables") or []
            )
        ]
        if used_by:
            raise ValidationError(f"This Table Preset is used by {used_by[0]}. Detach it there first.")
        if not self.repos.table_presets.delete(preset_id):
            raise ValidationError("Table Preset not found.")
        self.repos.meta.bump("settings_version")
        return preset
