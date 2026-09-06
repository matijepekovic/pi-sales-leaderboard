"""One-time conversion of stored Report tables to referenced Widget instances.

This service runs at composition time. Normal Screen evaluation never executes
the legacy data pipeline, and failed conversions retain their original data.
"""
from __future__ import annotations

import json
import math
import uuid

from stats_core.errors import ValidationError
from stats_core.screens.composition import clean_assets


class ScreenMigration:
    def __init__(self, screens_repository, widgets_service, fields_service,
                 groups_service, table_presets_service, filters_service, layout_defaults=None, asset_keys=()):
        self.screens = screens_repository
        self.widgets = widgets_service
        self.fields = fields_service
        self.groups = groups_service
        self.table_presets = table_presets_service
        self.filters = filters_service
        self.layout_defaults = layout_defaults
        self.asset_keys = asset_keys

    @staticmethod
    def _identity(prefix, value):
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return prefix + uuid.uuid5(uuid.NAMESPACE_URL, "stats:legacy-screen:" + serialized).hex

    def _tables(self, screen):
        raw = screen.get("tables", [])
        if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
            raise ValidationError("Stored Screen tables are invalid.")
        reports = screen.get("reports") or []
        groups = screen.get("group_ids") or []
        if not isinstance(reports, list) or not isinstance(groups, list):
            raise ValidationError("Stored Screen data selection is invalid.")
        tables = [dict(table) for table in raw]
        seen_reports = {str(table.get("report_id") or "") for table in tables if not table.get("group_id")}
        seen_groups = {str(table.get("group_id") or "") for table in tables}
        tables.extend({"report_id": report_id} for report_id in reports if str(report_id) not in seen_reports)
        tables.extend({"group_id": group_id} for group_id in groups if str(group_id) not in seen_groups)
        if not tables:
            raise ValidationError("Stored Screen has no tables to migrate.")
        return tables

    def _rules(self, report_id, filter_ids):
        rules = []
        if not isinstance(filter_ids, list):
            raise ValidationError("Stored Screen Filters are invalid.")
        for filter_id in filter_ids:
            definition = self.filters.get(filter_id)
            for rule in definition.get("rules") or []:
                if str(rule.get("report_id") or "") != report_id:
                    continue
                field_id = self.fields.ids_for_report(report_id, [rule.get("field")])[0]
                rules.append({"field_id": field_id, "operator": rule.get("operator"), "value": rule.get("value")})
        # Rules are ANDed; equivalent order/duplicates should reuse one Widget.
        unique = {json.dumps(rule, sort_keys=True, separators=(",", ":")): rule for rule in rules}
        return [unique[key] for key in sorted(unique)]

    def _theme_layout(self, screen):
        if isinstance(screen.get("layout"), dict):
            return screen["layout"]
        supplied = self.layout_defaults(screen) if callable(self.layout_defaults) else self.layout_defaults
        return supplied if isinstance(supplied, dict) else {}

    def _layout(self, screen, count, supplied=None):
        supplied = self._theme_layout(screen) if supplied is None else supplied
        content = supplied.get("content") if isinstance(supplied.get("content"), dict) else supplied
        def percentage(key, fallback):
            try:
                value = float(content.get(key, fallback))
            except (TypeError, ValueError):
                raise ValidationError("Theme content area is invalid.") from None
            if not math.isfinite(value):
                raise ValidationError("Theme content area is invalid.")
            return value
        x, y, width, height = (percentage(key, fallback) for key, fallback in (("x", 5), ("y", 5), ("width", 90), ("height", 90)))
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 100 or y + height > 100:
            raise ValidationError("Theme content area must fit within the Screen.")
        columns = math.ceil(math.sqrt(count))
        rows = math.ceil(count / columns)
        gap = min(2, width / (columns * 4), height / (rows * 4))
        cell_width = (width - gap * (columns - 1)) / columns
        cell_height = (height - gap * (rows - 1)) / rows
        return [
            {"x": round(x + (index % columns) * (cell_width + gap), 4),
             "y": round(y + (index // columns) * (cell_height + gap), 4),
             "width": round(cell_width, 4), "height": round(cell_height, 4)}
            for index in range(count)
        ]

    def _assets(self, screen, layout):
        raw = screen.get("assets") if "assets" in screen else layout.get("asset_slots", [])
        if raw is None:
            raw = layout.get("asset_slots", [])
        if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
            raise ValidationError("Stored Theme asset placement is invalid.")
        slots = [{**item, "id": item.get("id") or self._identity("asset-", [screen["id"], index, item.get("key")])}
                 for index, item in enumerate(raw)]
        allowed = self.asset_keys() if callable(self.asset_keys) else self.asset_keys
        return clean_assets(slots, allowed)

    def _plan(self, original):
        screen_id = str(original.get("id") or "")
        if not screen_id:
            raise ValidationError("Stored Screen id is missing.")
        tables = self._tables(original)
        theme_layout = self._theme_layout(original)
        rectangles = self._layout(original, len(tables), theme_layout)
        assets = self._assets(original, theme_layout)
        current_widgets = {widget["id"]: widget for widget in self.widgets.list()}
        names = {str(widget["name"]).casefold() for widget in current_widgets.values()}
        definitions = {}
        instances = []
        for index, table in enumerate(tables):
            group_id = str(table.get("group_id") or "")
            if group_id:
                group = self.groups.get(group_id)
                report_id = str(self.groups.get_type(group["type_id"]).get("report_id") or "")
            else:
                report_id = str(table.get("report_id") or "")
            if not report_id:
                raise ValidationError("A stored table has no valid Field dataset.")
            preset_id = str(table.get("preset_id") or "")
            preset = self.table_presets.get(preset_id) if preset_id else {}
            if preset and str(preset.get("report_id") or "") != report_id:
                raise ValidationError("A stored Table Preset belongs to another dataset.")
            settings = preset or table
            keys = settings.get("columns")
            if keys is None or keys == []:
                keys = [field["key"] for field in self.fields.fields(report_id)]
            if not isinstance(keys, list):
                raise ValidationError("Stored table columns are invalid.")
            field_ids = self.fields.ids_for_report(report_id, keys)
            rules = self._rules(report_id, original.get("filter_ids") or [])
            identity = {"preset_id": preset_id, "origin": None if preset_id else [screen_id, index],
                        "field_ids": field_ids, "filters": rules}
            widget_id = self._identity("widget-", identity)
            if widget_id in current_widgets:
                existing = current_widgets[widget_id]
                if existing.get("kind") != "table" or existing.get("field_ids") != field_ids or existing.get("filters") != rules:
                    raise ValidationError("A Widget from an earlier migration attempt was edited. Resolve it before retrying.")
            elif widget_id not in definitions:
                base_name = str(preset.get("name") or f"{original.get('name') or screen_id} table {index + 1}")[:100]
                if rules:
                    base_name += " (filtered)"
                name, suffix = base_name, 2
                while name.casefold() in names:
                    name = f"{base_name} ({suffix})"
                    suffix += 1
                names.add(name.casefold())
                definitions[widget_id] = self.widgets.normalize({"id": widget_id, "name": name, "kind": "table", "field_ids": field_ids, "filters": rules})
            sort_key = str(settings.get("sort_field") or "")
            ranking = []
            if sort_key:
                sort_id = self.fields.ids_for_report(report_id, [sort_key])[0]
                direction = str(settings.get("sort_direction") or "desc")
                if direction not in {"asc", "desc"}:
                    raise ValidationError("Stored table sort direction is invalid.")
                metadata = self.fields.resolve([sort_id])[0]
                if metadata.get("kind") == "table" or metadata.get("type") == "asset":
                    raise ValidationError("Stored sorting requires a numeric or text Field.")
                ranking.append({"field_id": sort_id, "direction": direction})
            instances.append({
                "id": self._identity("instance-", [screen_id, index]), "widget_id": widget_id,
                "group_ids": [group_id] if group_id else [], "group_mode": "combine", "ranking": ranking,
                "timeframe": None, "layout": rectangles[index],
                "fit": {"rows": 10, "font_size": 20, "padding": 8},
            })
        converted = {
            "id": screen_id, "name": str(original.get("name") or screen_id),
            "widgets": instances, "canvas": {"width": 1920, "height": 1080},
            "assets": assets,
            "theme_mode": str(original.get("theme_mode") or "inherited"),
            "theme_group_id": str(original.get("theme_group_id") or ""),
            "theme_group_type_id": str(original.get("theme_group_type_id") or ""),
            "theme_id": str(original.get("theme_id") or ""),
            "winner_widget_id": instances[0]["id"], "timeframe": None,
        }
        return converted, list(definitions.values())

    def run(self):
        result = {"migrated": [], "errors": []}
        for original in self.screens.list():
            if "widgets" in original:
                continue
            try:
                converted, definitions = self._plan(original)
                self.screens.backup_legacy(original)
                for definition in definitions:
                    self.widgets.save(definition)
                self.screens.save(converted)
                result["migrated"].append(original["id"])
            except Exception as exc:
                result["errors"].append({"screen_id": str(original.get("id") or ""),
                                         "name": str(original.get("name") or ""), "error": str(exc)})
        return result
