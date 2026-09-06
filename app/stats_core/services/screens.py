"""Screen composition: place Widgets and supply scope, ranking and appearance context."""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError
from stats_core.screens.composition import clean_assets, clean_canvas, clean_fit, clean_layout, clean_timeframe


class ScreenService:
    """Screens never retrieve Reports or calculate Fields; they compose public contracts."""

    def __init__(self, repository, widgets, groups, themes, meta):
        self.repository = repository
        self.widgets = widgets
        self.groups = groups
        self.themes = themes
        self.meta = meta

    def list(self):
        return sorted(self.repository.list(), key=lambda item: str(item.get("name") or "").casefold())

    def get(self, screen_id):
        screen = self.repository.get(str(screen_id or "").strip())
        if not screen:
            raise ValidationError("Screen not found.")
        return screen

    def normalize(self, incoming, screen_id=None):
        if not isinstance(incoming, dict):
            raise ValidationError("Screen must be an object.")
        if any(key in incoming for key in ("reports", "tables", "filter_ids")):
            raise ValidationError("Screens use reusable Widgets. Choose a Widget to place on this Screen.")
        unexpected = set(incoming) - {"id", "name", "widgets", "canvas", "timeframe", "theme_mode", "theme_id", "theme_group_id", "theme_group_type_id", "winner_widget_id", "assets"}
        if unexpected:
            raise ValidationError(f"Screens do not own '{sorted(unexpected)[0]}'.")
        name = str(incoming.get("name") or "").strip()
        if not name or len(name) > 120:
            raise ValidationError("Screen name must contain between 1 and 120 characters.")
        raw_instances = incoming.get("widgets")
        if not isinstance(raw_instances, list) or not 1 <= len(raw_instances) <= 50:
            raise ValidationError("Choose between 1 and 50 Widgets for this Screen.")
        instances, seen = [], set()
        for raw in raw_instances:
            if not isinstance(raw, dict):
                raise ValidationError("Each placed Widget must be an object.")
            unexpected = set(raw) - {"id", "widget_id", "group_ids", "group_mode", "ranking", "timeframe", "field_variants", "identity_field_id", "layout", "fit"}
            if unexpected:
                raise ValidationError(f"A Screen placement does not own '{sorted(unexpected)[0]}'.")
            instance_id = str(raw.get("id") or f"instance-{uuid.uuid4().hex[:12]}").strip()
            if instance_id in seen:
                raise ValidationError("Each placed Widget needs its own identity.")
            seen.add(instance_id)
            widget_id = str(raw.get("widget_id") or "").strip()
            self.widgets.get(widget_id)
            group_ids = raw.get("group_ids", [])
            if not isinstance(group_ids, list) or len(group_ids) > 100:
                raise ValidationError("Choose a valid list of Groups.")
            group_ids = list(dict.fromkeys(str(value).strip() for value in group_ids))
            for group_id in group_ids:
                self.groups.get(group_id)
            group_mode = str(raw.get("group_mode") or "combine")
            if group_mode not in {"combine", "separate"}:
                raise ValidationError("Choose combined Groups or separate by Group.")
            context = self.widgets.validate_context(widget_id, {
                "group_ids": group_ids,
                "ranking": raw.get("ranking") or [],
                "timeframe": clean_timeframe(raw.get("timeframe")),
                "field_variants": raw.get("field_variants", []),
                "identity_field_id": str(raw.get("identity_field_id") or ""),
            })
            instances.append({
                "id": instance_id, "widget_id": widget_id, "group_ids": group_ids,
                "group_mode": group_mode, "ranking": context["ranking"],
                "timeframe": context.get("timeframe"), "layout": clean_layout(raw.get("layout")),
                "fit": clean_fit(raw.get("fit")),
                "field_variants": context.get("field_variants") or [],
                "identity_field_id": context.get("identity_field_id") or "",
            })
        theme_mode = str(incoming.get("theme_mode") or "inherited")
        if theme_mode not in {"inherited", "group", "custom"}:
            raise ValidationError("Choose a fixed Theme, a Group, or the winning member's Group.")
        group_id = str(incoming.get("theme_group_id") or "").strip() if theme_mode == "group" else ""
        type_id = str(incoming.get("theme_group_type_id") or "").strip() if theme_mode == "inherited" else ""
        if theme_mode == "group":
            self.groups.get(group_id)
        if type_id:
            self.groups.get_type(type_id)
        theme_id = str(incoming.get("theme_id") or "").strip()
        if theme_id:
            self.themes.get_theme(theme_id)
        winner_id = str(incoming.get("winner_widget_id") or instances[0]["id"]).strip()
        if winner_id not in seen:
            raise ValidationError("Choose a placed Widget to determine the winning Group.")
        assets = clean_assets(incoming.get("assets"), self.themes.asset_keys())
        if assets is None:
            inherited_layout = self.themes.effective_preview_theme(incoming).get("layout") or {}
            assets = clean_assets(inherited_layout.get("asset_slots") or [], self.themes.asset_keys())
        return {
            "id": str(screen_id or incoming.get("id") or f"screen-{uuid.uuid4().hex[:12]}"),
            "name": name, "widgets": instances, "canvas": clean_canvas(incoming.get("canvas")),
            "timeframe": clean_timeframe(incoming.get("timeframe")),
            "theme_mode": theme_mode, "theme_id": theme_id,
            "theme_group_id": group_id, "theme_group_type_id": type_id,
            "winner_widget_id": winner_id,
            "assets": assets,
        }

    def save(self, incoming):
        screen = self.normalize(incoming)
        self.repository.save(screen)
        self.meta.bump("settings_version")
        return screen

    def delete(self, screen_id):
        if not self.repository.delete(str(screen_id or "")):
            raise ValidationError("Screen not found.")
        self.meta.bump("settings_version")
        return True

    def widget_references(self, widget_id):
        return [screen["name"] for screen in self.list() if any(item.get("widget_id") == widget_id for item in screen.get("widgets", []))]

    def field_references(self, field_id):
        return [screen["name"] for screen in self.list() if any(
            item.get("identity_field_id") == field_id or any(
                rule.get("field_id") == field_id for rule in [*item.get("ranking", []), *item.get("field_variants", [])]
            ) for item in screen.get("widgets", []))]

    def field_consumers(self):
        """A placement's complete query, not unrelated Widgets pooled together."""
        consumers = []
        for screen in self.list():
            for instance in screen.get("widgets", []):
                field_ids = [*self.widgets.field_dependencies(instance["widget_id"]),
                             *[rule["field_id"] for rule in instance.get("ranking", [])],
                             *[variant["field_id"] for variant in instance.get("field_variants", [])],
                             instance.get("identity_field_id")]
                consumers.append({"name": f"Screen '{screen['name']}'",
                                  "field_ids": list(dict.fromkeys(value for value in field_ids if value))})
        return consumers

    def validate_widget_change(self, definition):
        for screen in self.list():
            for instance in screen.get("widgets", []):
                if instance.get("widget_id") != definition["id"]:
                    continue
                try:
                    self.widgets.validate_definition_context(definition, {
                        "group_ids": instance.get("group_ids") or [],
                        "ranking": instance.get("ranking") or [],
                        "field_variants": instance.get("field_variants") or [],
                        "identity_field_id": instance.get("identity_field_id") or "",
                    })
                except ValidationError as exc:
                    raise ValidationError(f"This change would invalidate Screen '{screen['name']}': {exc}") from exc

    def theme_references(self, theme_id):
        return [screen["name"] for screen in self.list() if screen.get("theme_id") == theme_id]

    def group_references(self, group_id):
        return [screen["name"] for screen in self.list() if screen.get("theme_group_id") == group_id or any(group_id in item.get("group_ids", []) for item in screen.get("widgets", []))]

    def group_type_references(self, type_id):
        return [screen["name"] for screen in self.list() if screen.get("theme_group_type_id") == type_id]

    def _instance(self, screen, instance):
        context = {"group_ids": instance["group_ids"], "ranking": instance["ranking"],
                   "timeframe": instance.get("timeframe") or screen.get("timeframe"),
                   "field_variants": instance.get("field_variants") or [],
                   "identity_field_id": instance.get("identity_field_id") or ""}
        combined = self.widgets.render(instance["widget_id"], context)
        selected = instance["group_ids"] if instance["group_mode"] == "separate" else []
        sections = []
        for index, group_id in enumerate(selected or [""]):
            payload = self.widgets.render(instance["widget_id"], {**context, "group_ids": [group_id]}) if group_id else combined
            layout = dict(instance["layout"])
            if selected:
                layout["width"] /= len(selected)
                layout["x"] += index * layout["width"]
            section = {**payload, "instance_id": instance["id"],
                       "section_id": f"{instance['id']}:{group_id}" if group_id else instance["id"],
                       "layout": layout, "fit": dict(instance["fit"])}
            if group_id:
                group = self.groups.get(group_id)
                section.update({"group_id": group_id, "group_name": group["name"], "name": f"{group['name']} · {payload['name']}"})
            sections.append(section)
        return sections, combined.get("rows") or []

    def render_definition(self, screen):
        if "widgets" not in screen:
            raise ValidationError("This saved Screen needs migration. Its original definition has been preserved.")
        sections, winner_rows = [], []
        for instance in screen["widgets"]:
            rendered, rows = self._instance(screen, instance)
            sections.extend(rendered)
            if instance["id"] == screen.get("winner_widget_id", screen["widgets"][0]["id"]):
                winner_rows = rows
        inherited_id, type_id = "", str(screen.get("theme_group_type_id") or "")
        if screen.get("theme_mode") == "inherited" and winner_rows and type_id:
            inherited_id = str((winner_rows[0].get("__group_ids") or {}).get(type_id) or "")
        inherited = self.groups.get(inherited_id) if inherited_id else {}
        theme = self.themes.effective_preview_theme(screen, inherited_id)
        assets = screen.get("assets")
        if assets is None:
            # Active compatibility for canonical Screens saved before asset placement.
            assets = (theme.get("layout") or {}).get("asset_slots") or []
        for section in sections:
            section_theme = theme
            if section.get("group_id") and screen.get("theme_mode") == "inherited":
                section_theme = self.themes.effective_group_theme(section["group_id"])
            section["theme"] = section_theme
        return {
            "mode": "screen", "screen_id": screen["id"], "screen_name": screen["name"],
            "canvas": screen.get("canvas") or {"width": 1920, "height": 1080},
            "theme_mode": screen.get("theme_mode", "inherited"), "theme_id": screen.get("theme_id", ""),
            "theme_group_id": screen.get("theme_group_id", ""), "theme_group_type_id": type_id,
            "inherited_theme_group_id": inherited_id, "inherited_theme_group_name": inherited.get("name", ""),
            "theme": theme, "sections": sections,
            "assets": assets,
        }

    def preview(self, incoming):
        return self.render_definition(self.normalize(incoming))

    def render(self, screen_id):
        return self.render_definition(self.get(screen_id))
