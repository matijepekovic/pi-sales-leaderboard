"""Reusable Theme resources, asset library, and supplied appearance resolution."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from stats_core.theme.appearance import STYLE_KEYS, clean_widget_styles, merge_style

from stats_core.theme.catalog import (
    ALLOWED_BASES,
    ASSETS,
    CLASSIC_COLORS,
    CORNER_ASSET_KEYS,
    DEFAULT_LAYOUT,
    DEFAULT_CORNER_SETTINGS,
    LIBRARY_KEYS,
    PLANNABLE_ASSET_KEYS,
    STARTER_COLORS,
    STARTER_FILES,
)

MAX_ASSET_BYTES = 8 * 1024 * 1024
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeService:
    """Own Theme resources and resolve Group-owned choices through a contract.

    Existing Screen-specific Theme records remain an active saved-data format.
    Layout is read only as a legacy fallback; Screen owns current placement.
    """

    def __init__(self, repos, group_context=None, theme_usage=None, asset_usage=None, screen_context=None):
        self.repos = repos
        self.theme_repo = repos.themes
        self.library = repos.asset_library
        self.applied = repos.applied_assets
        self.group_context = group_context
        self.theme_usage = theme_usage
        self.asset_usage = asset_usage
        self.screen_context = screen_context

    def prepare(self):
        self.applied.root.mkdir(parents=True, exist_ok=True)
        return True

    @staticmethod
    def _percent(value, default, low=0.0, high=100.0):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = float(default)
        return round(min(max(value, low), high), 2)

    def clean_layout(self, incoming):
        """Normalize the shared resolution-independent Theme canvas."""
        raw = incoming if isinstance(incoming, dict) else {}
        content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
        defaults = DEFAULT_LAYOUT["content"]
        x = self._percent(content.get("x"), defaults["x"], 0, 90)
        y = self._percent(content.get("y"), defaults["y"], 0, 90)
        width = self._percent(content.get("width"), defaults["width"], 10, 100 - x)
        height = self._percent(content.get("height"), defaults["height"], 10, 100 - y)
        slots, used = [], set()
        for item in raw.get("asset_slots") if isinstance(raw.get("asset_slots"), list) else []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if key not in PLANNABLE_ASSET_KEYS or key in used:
                continue
            slot_x = self._percent(item.get("x"), 5, 0, 98)
            slot_y = self._percent(item.get("y"), 5, 0, 98)
            used.add(key)
            slots.append({
                "key": key,
                "x": slot_x,
                "y": slot_y,
                "width": self._percent(item.get("width"), 15, 2, 100 - slot_x),
                "height": self._percent(item.get("height"), 15, 2, 100 - slot_y),
                "fit": "cover" if str(item.get("fit") or "contain") == "cover" else "contain",
            })
        return {
            "auto_fit": bool(raw.get("auto_fit", DEFAULT_LAYOUT["auto_fit"])),
            "content": {"x": x, "y": y, "width": width, "height": height},
            "asset_slots": slots[:12],
        }

    def _shared_layout(self, settings):
        stored = self.theme_repo.get_layout(settings)
        if stored:
            return self.clean_layout(stored)
        return self.clean_layout(DEFAULT_LAYOUT)

    def _screen(self, screen_id):
        if self.screen_context is None:
            raise ValueError("Screen context provider is not configured.")
        screen = self.screen_context(str(screen_id or "").strip())
        if not screen:
            raise ValueError("Screen not found.")
        return screen

    def _group_appearance(self, group_id):
        if self.group_context is None:
            raise ValueError("Group appearance provider is not configured.")
        return self.group_context(str(group_id or "").strip())

    def legacy_group_appearance(self, group_id):
        """Read the active legacy Theme format without changing saved artwork."""
        config = self.theme_repo.get_group(group_id)
        return {
            "theme_id": str(config.get("base") or "starter"),
            "asset_bindings": {key: f"applied:{value}" for key, value in (config.get("assets") or {}).items()},
            "style": {key: value for key, value in config.items() if key in STYLE_KEYS},
            "widget_styles": {},
        }

    def list_themes(self):
        builtins = [{"id": base, "name": label, "base": base, "builtin": True} for base, label in (("starter", "Starter"), ("classic", "Plain"))]
        return builtins + sorted(self.theme_repo.list_named(), key=lambda item: str(item.get("name") or "").casefold())

    def get_theme(self, theme_id):
        theme_id = str(theme_id or "starter").strip()
        if theme_id in ALLOWED_BASES:
            return {"id": theme_id, "name": "Starter" if theme_id == "starter" else "Plain", "base": theme_id, "builtin": True, "asset_bindings": {}}
        theme = self.theme_repo.get_named(theme_id)
        if not theme:
            raise ValueError("Theme not found.")
        return theme

    def _style_colors(self, raw):
        if not isinstance(raw, dict):
            return {}
        return {key: str(value).lower() for key, value in raw.items() if key in CLASSIC_COLORS and COLOR_RE.match(str(value))}

    def clean_style(self, raw):
        if not isinstance(raw, dict):
            raise ValueError("Style must be an object.")
        if set(raw) - STYLE_KEYS:
            raise ValueError("Group style can contain visual settings only.")
        result = {}
        if "colors" in raw:
            result["colors"] = self._style_colors(raw["colors"])
        if "corner_settings" in raw:
            result["corner_settings"] = self.clean_corners(raw["corner_settings"])
        if "hero_scale" in raw:
            result["hero_scale"] = self.bounded(raw["hero_scale"], 100, 50, 200)
        if "row_stripe" in raw:
            result["row_stripe"] = self.clean_stripe(raw["row_stripe"], result.get("colors"))
        return result

    def clean_asset_bindings(self, raw, allow_applied=False):
        if not isinstance(raw, dict):
            raise ValueError("Asset bindings must be an object.")
        result = {}
        for key, value in raw.items():
            if key not in ASSETS:
                raise ValueError("Unknown theme asset.")
            reference = str(value or "").strip()
            if not reference:
                continue
            if allow_applied and reference.startswith("applied:"):
                if not self.applied.safe_filename(reference[8:]):
                    raise ValueError("Invalid saved asset reference.")
            else:
                self._resolve_library_source(key, reference)
            result[key] = reference
        return result

    def clean_group_appearance(self, raw):
        raw = raw if isinstance(raw, dict) else {}
        theme_id = str(raw.get("theme_id") or "starter").strip()
        self.get_theme(theme_id)
        return {
            "theme_id": theme_id,
            "asset_bindings": self.clean_asset_bindings(raw.get("asset_bindings") or {}, allow_applied=True),
            "style": self.clean_style(raw.get("style") or {}),
            "widget_styles": clean_widget_styles(raw.get("widget_styles") or {}, self._style_colors),
        }

    def save_theme(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        theme_id = str(incoming.get("id") or "").strip() or f"theme-{uuid.uuid4().hex[:12]}"
        if theme_id in ALLOWED_BASES:
            raise ValueError("Save a custom Theme to change a built-in Theme.")
        existing = self.theme_repo.get_named(theme_id) or {}
        name = str(incoming.get("name") or existing.get("name") or "").strip()[:120]
        if not name:
            raise ValueError("Theme name is required.")
        config = self._clean_theme_config(existing, incoming)
        config.pop("assets", None)
        bindings = dict(incoming.get("asset_bindings", existing.get("asset_bindings", {})))
        copy_from = incoming.get("copy_from") or {}
        for asset_key, reference in list(bindings.items()):
            if not str(reference).startswith("applied:"):
                continue
            if copy_from.get("owner") == "group":
                owner_id = str(copy_from.get("id") or "")
                source_appearance = self._group_appearance(owner_id)
                if (source_appearance.get("asset_bindings") or {}).get(asset_key) != reference:
                    raise ValueError("That Group does not own this saved asset.")
                path = self.group_asset_path(owner_id, asset_key)
            elif copy_from.get("owner") == "screen":
                owner_id = str(copy_from.get("id") or "")
                self._screen(owner_id)
                path = self.screen_asset_path(owner_id, asset_key)
            else:
                raise ValueError("Choose the saved artwork owner when copying this Theme.")
            if not path or not path.exists():
                raise ValueError("Saved artwork is missing.")
            builtin = next((item for item in self._builtin_library_items().get(asset_key, [])
                            if (source := self.library.resolve_builtin_url(item["url"]))
                            and self.applied.sha256(source) == self.applied.sha256(path)), None)
            if builtin:
                bindings[asset_key] = builtin["id"]
            else:
                item_id = self.library.add_file(asset_key, path, f"{name} - {asset_key}")
                if not item_id:
                    raise ValueError("This older artwork must be replaced with a supported library asset before copying it.")
                bindings[asset_key] = f"user:{item_id}"
        config.update({"id": theme_id, "name": name, "builtin": False,
                       "asset_bindings": self.clean_asset_bindings(bindings)})
        self.theme_repo.save_named(config)
        return config

    def delete_theme(self, theme_id):
        theme = self.get_theme(theme_id)
        if theme.get("builtin"):
            raise ValueError("Built-in Themes cannot be deleted.")
        references = list(self.theme_usage(theme_id) if self.theme_usage else [])
        if references:
            raise ValueError(f"This Theme is used by {references[0]}. Choose another Theme there first.")
        self.theme_repo.delete_named(theme_id)
        return theme

    def resolve_appearance(self, appearance, group_id="", mode="group"):
        """Resolve supplied Group choices through Theme/Asset owners only."""
        appearance = appearance or {}
        theme = self.get_theme(appearance.get("theme_id") or "starter")
        config = merge_style(theme, appearance.get("style") or {})
        resolved = self._effective_theme(config, self._group_scope(group_id) if group_id else f"theme-{theme['id']}", mode, f"/api/group-theme-assets/{group_id}")
        bindings = {**theme.get("asset_bindings", {}), **appearance.get("asset_bindings", {})}
        for key, reference in bindings.items():
            if key not in ASSETS:
                continue
            if reference.startswith("applied:"):
                path = self.applied.path(self._group_scope(group_id), reference[8:])
                if path and path.exists():
                    resolved["assets"][key] = f"/api/group-theme-assets/{group_id}/{key}?v={self.repos.meta.get('settings_version', '0')}"
            elif reference.startswith("builtin:"):
                resolved["assets"][key] = reference[8:]
            elif reference.startswith("user:"):
                resolved["assets"][key] = f"/api/asset-library/{key}/{reference[5:]}"
        resolved["theme_id"] = theme["id"]
        resolved["name"] = theme["name"]
        if group_id:
            resolved["group_id"] = group_id
        resolved["asset_bindings"] = dict(appearance.get("asset_bindings") or {})
        resolved["effective_asset_bindings"] = dict(bindings)
        resolved["widget_styles"] = dict(appearance.get("widget_styles") or {})
        resolved["has_custom_assets"] = bool(bindings)
        return resolved

    def effective_theme(self, theme_id):
        return self.resolve_appearance({"theme_id": theme_id}, mode="theme")

    @staticmethod
    def _screen_scope(screen_id):
        return f"screen-{str(screen_id).strip()}"

    @staticmethod
    def _group_scope(group_id):
        return f"group-{str(group_id).strip()}"

    @staticmethod
    def bounded(value, default, low, high):
        try:
            value = float(value)
        except Exception:
            value = float(default)
        return round(min(max(value, low), high), 2)

    @staticmethod
    def base_colors(base):
        return dict(STARTER_COLORS if base == "starter" else CLASSIC_COLORS)

    def clean_colors(self, incoming, base):
        colors = self.base_colors(base)
        if isinstance(incoming, dict):
            for key in colors:
                value = str(incoming.get(key) or "").strip()
                if COLOR_RE.match(value):
                    colors[key] = value.lower()
        return colors

    def clean_corners(self, incoming):
        if not isinstance(incoming, dict):
            return {}
        out = {}
        for key in CORNER_ASSET_KEYS:
            row = incoming.get(key)
            if not isinstance(row, dict):
                continue
            out[key] = {
                "size": self.bounded(row.get("size"), 100, 50, 600),
                "crop_x": self.bounded(row.get("crop_x"), 0, 0, 60),
                "crop_y": self.bounded(row.get("crop_y"), 0, 0, 60),
            }
        return out

    def clean_stripe(self, incoming, colors):
        color = str((colors or {}).get("primary") or "#d8b34a").lower()
        strength = 0.0
        if isinstance(incoming, dict):
            candidate = str(incoming.get("color") or "").strip()
            if COLOR_RE.match(candidate):
                color = candidate.lower()
            strength = self.bounded(incoming.get("strength"), 0, 0, 100)
        return {"color": color, "strength": strength}

    def manifest(self):
        return {
            "presets": [
                {"key": "starter", "label": "Starter"},
                {"key": "classic", "label": "Plain"},
            ],
            "colors": [
                {"key": key, "label": label}
                for key, label in (
                    ("primary", "Primary"),
                    ("primary_bright", "Primary Bright"),
                    ("primary_dark", "Primary Dark"),
                    ("secondary", "Secondary"),
                    ("background", "Background"),
                    ("panel", "Panel"),
                    ("text", "Text"),
                    ("muted", "Muted Text"),
                    ("champion_text", "Champion Text"),
                )
            ],
            "assets": [
                {
                    "key": key,
                    "label": value["label"],
                    "adjustable": bool(value.get("adjustable")),
                    "placeable": key in PLANNABLE_ASSET_KEYS,
                }
                for key, value in ASSETS.items()
            ],
        }

    def _default_asset_url(self, key, base):
        filename = STARTER_FILES.get(key) if base == "starter" else None
        return f"/static/theme-packs/starter/{filename}" if filename else None

    def _effective_theme(self, config, scope, mode, asset_url):
        config = config if isinstance(config, dict) else {}
        base = str(config.get("base") or "starter").lower()
        if base not in ALLOWED_BASES:
            base = "starter"
        colors = self.clean_colors(config.get("colors"), base)
        version = int(self.repos.meta.get("settings_version", "0") or 0)
        assets_cfg = config.get("assets") if isinstance(config.get("assets"), dict) else {}
        assets = {}
        for key in ASSETS:
            filename = self.applied.safe_filename(assets_cfg.get(key))
            path = self.applied.path(scope, filename) if filename else None
            if path and path.exists():
                assets[key] = f"{asset_url}/{key}?v={version}"
            else:
                assets[key] = self._default_asset_url(key, base)
        corners = self.clean_corners(config.get("corner_settings"))
        return {
            "scope": scope,
            "mode": mode,
            "base": base,
            "enabled": True,
            "colors": colors,
            "assets": assets,
            "layout": self._shared_layout(self.repos.settings.get()),
            "corner_settings": {
                key: {**DEFAULT_CORNER_SETTINGS, **corners.get(key, {})}
                for key in CORNER_ASSET_KEYS
            },
            "hero_scale": self.bounded(config.get("hero_scale"), 100, 50, 200),
            "row_stripe": self.clean_stripe(config.get("row_stripe"), colors),
            "has_custom_assets": bool(assets_cfg),
            "effective_asset_bindings": {key: f"applied:{value}" for key, value in assets_cfg.items()},
        }

    @staticmethod
    def asset_keys():
        """Slot identities available for Screen-level asset placement."""
        return list(PLANNABLE_ASSET_KEYS)

    def effective_screen_theme(self, screen_id, settings=None, inherited_group_id=""):
        screen = self._screen(screen_id)
        settings = settings or self.repos.settings.get()
        mode = str(screen.get("theme_mode") or "inherited")
        if mode == "group":
            group_id = str(screen.get("theme_group_id") or "").strip()
            return self.effective_group_theme(group_id, settings)
        if mode == "inherited" and inherited_group_id:
            group_id = str(inherited_group_id).strip()
            theme = self.effective_group_theme(group_id, settings)
            theme["mode"] = "inherited"
            theme["inherited_group_id"] = group_id
            return theme
        if screen.get("theme_id"):
            return self.effective_theme(screen["theme_id"])
        config = self.theme_repo.get(screen_id, settings) if mode == "custom" else {}
        return self._effective_theme(
            config,
            self._screen_scope(screen_id),
            "custom" if mode == "custom" else "inherited",
            f"/api/screen-theme-assets/{screen_id}",
        )

    def effective_group_theme(self, group_id, settings=None, group_context=None):
        appearance = group_context if group_context is not None else self._group_appearance(group_id)
        return self.resolve_appearance(appearance, group_id)

    def effective_preview_theme(self, screen, inherited_group_id=""):
        """Resolve Theme values for an unsaved Screen definition."""
        screen = screen if isinstance(screen, dict) else {}
        mode = str(screen.get("theme_mode") or "inherited")
        group_id = str(
            inherited_group_id
            if mode == "inherited"
            else screen.get("theme_group_id") if mode == "group"
            else ""
        ).strip()
        if group_id:
            theme = self.effective_group_theme(group_id)
            if mode == "inherited":
                theme["mode"] = "inherited"
                theme["inherited_group_id"] = group_id
            return theme
        if screen.get("theme_id"):
            return self.effective_theme(screen["theme_id"])
        screen_id = str(screen.get("id") or "").strip()
        if mode == "custom" and screen_id:
            try:
                self._screen(screen_id)
            except ValueError:
                pass
            else:
                return self.effective_screen_theme(screen_id)
        return self._effective_theme(
            {}, self._screen_scope("preview"), mode, "/api/screen-theme-assets/preview"
        )

    def _clean_theme_config(self, current, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        current = dict(current or {})
        base = str(incoming.get("base") or current.get("base") or "starter").lower()
        if base not in ALLOWED_BASES:
            raise ValueError("Unknown theme preset.")
        current["base"] = base
        current["colors"] = self.clean_colors(incoming.get("colors", current.get("colors")), base)
        current["assets"] = dict(current.get("assets") or {})
        current["corner_settings"] = self.clean_corners(incoming.get("corner_settings", current.get("corner_settings")))
        current["hero_scale"] = self.bounded(incoming.get("hero_scale", current.get("hero_scale")), 100, 50, 200)
        current["row_stripe"] = self.clean_stripe(incoming.get("row_stripe", current.get("row_stripe")), current["colors"])
        return current

    def save_screen_theme(self, screen_id, incoming):
        self._screen(screen_id)
        settings = self.repos.settings.get()
        current = self._clean_theme_config(self.theme_repo.get(screen_id, settings), incoming)
        version = self.theme_repo.save(screen_id, current, settings)
        return version, self.effective_screen_theme(screen_id)

    def reset_screen_theme(self, screen_id):
        self._screen(screen_id)
        scope = self._screen_scope(screen_id)
        for key in ASSETS:
            self.applied.remove(scope, key)
        version = self.theme_repo.delete(screen_id)
        return version, self.effective_screen_theme(screen_id)

    def purge_group_theme(self, group_id):
        """Remove a deleted Group's theme configuration and applied assets."""
        scope = self._group_scope(group_id)
        for key in ASSETS:
            self.applied.remove(scope, key)
        return self.theme_repo.delete_group(group_id)

    @staticmethod
    def _library_key(asset_key):
        asset_key = str(asset_key or "").strip()
        if asset_key not in LIBRARY_KEYS:
            raise ValueError("Unknown theme asset.")
        return asset_key

    @staticmethod
    def _checked_upload(upload):
        if not upload or not getattr(upload, "filename", ""):
            raise ValueError("Choose an image file.")
        ext = Path(upload.filename).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("Theme assets must be PNG, JPG, or WEBP.")
        upload.stream.seek(0, os.SEEK_END)
        size = upload.stream.tell()
        upload.stream.seek(0)
        if size > MAX_ASSET_BYTES:
            raise ValueError("Theme assets must be under 8 MB.")
        return ext

    def _builtin_library_items(self):
        grouped = {}
        raw = self.library.builtin_catalog()
        for collection in raw.get("collections") or []:
            collection_label = str(collection.get("label") or collection.get("key") or "Built-in")
            for item in collection.get("items") or []:
                label = str(item.get("label") or item.get("key") or "Preset")
                for target_key, url in (item.get("targets") or {}).items():
                    if target_key not in LIBRARY_KEYS or not str(url or "").strip():
                        continue
                    grouped.setdefault(target_key, []).append({
                        "id": f"builtin:{url}",
                        "label": f"{collection_label} — {label}",
                        "url": url,
                        "source": "builtin",
                        "deletable": False,
                    })
        return grouped

    def _user_library_items(self, asset_key):
        items = []
        for row in self.library.read_index(asset_key):
            item_id = str(row.get("id") or "")
            if not item_id or self.library.item_path(asset_key, item_id) is None:
                continue
            items.append({
                "id": f"user:{item_id}",
                "label": str(row.get("label") or item_id),
                "url": f"/api/asset-library/{asset_key}/{item_id}",
                "created": row.get("created", ""),
                "source": "user",
                "deletable": True,
            })
        items.sort(key=lambda row: str(row.get("created") or ""), reverse=True)
        return items

    def library_state(self):
        builtin = self._builtin_library_items()
        return {
            key: builtin.get(key, []) + self._user_library_items(key)
            for key in sorted(LIBRARY_KEYS)
        }

    def add_library_item(self, asset_key, upload, label=""):
        asset_key = self._library_key(asset_key)
        ext = self._checked_upload(upload)
        item_id, _path = self.library.save_upload(asset_key, upload, ext, label or upload.filename or "Untitled")
        return item_id, f"/api/asset-library/{asset_key}/{item_id}"

    def library_item_path(self, asset_key, item_id):
        self._library_key(asset_key)
        return self.library.item_path(asset_key, item_id)

    def delete_library_item(self, asset_key, item_id):
        asset_key = self._library_key(asset_key)
        reference = f"user:{item_id}"
        uses = list(self.asset_usage(reference) if self.asset_usage else [])
        uses.extend(str(item.get("name") or item.get("id")) for item in self.theme_repo.list_named() if reference in (item.get("asset_bindings") or {}).values())
        if uses:
            raise ValueError(f"This asset is used by {uses[0]}. Replace it there first.")
        if not self.library.delete(asset_key, item_id):
            raise ValueError("That saved item is no longer available.")

    def _resolve_library_source(self, asset_key, library_id):
        asset_key = self._library_key(asset_key)
        raw = str(library_id or "").strip()
        if raw.startswith("user:"):
            path = self.library.item_path(asset_key, raw[5:])
            if path:
                return path
            raise ValueError("That saved item is no longer available.")
        if raw.startswith("builtin:"):
            url = raw[8:]
            valid = {str(item.get("url") or "") for item in self._builtin_library_items().get(asset_key, [])}
            if url not in valid:
                raise ValueError("Unknown preset.")
            path = self.library.resolve_builtin_url(url)
            if path:
                return path
        raise ValueError("Unknown preset.")

    def _apply_owner_asset(self, scope, current, save, effective, asset_key, upload=None, library_id=None):
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")
        if library_id:
            source = self._resolve_library_source(asset_key, library_id)
            _path, filename = self.applied.copy(scope, asset_key, source)
        else:
            ext = self._checked_upload(upload)
            path, filename = self.applied.save_upload(scope, asset_key, upload, ext)
            try:
                self.library.add_file(asset_key, path, upload.filename, ext)
            except Exception:
                pass
        current = dict(current or {})
        current.setdefault("assets", {})[asset_key] = filename
        version = save(current)
        return version, effective()

    def _reset_owner_asset(self, scope, current, save, effective, asset_key):
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")
        self.applied.remove(scope, asset_key)
        current = dict(current or {})
        assets = dict(current.get("assets") or {})
        assets.pop(asset_key, None)
        current["assets"] = assets
        version = save(current)
        return version, effective()

    def apply_screen_asset(self, screen_id, asset_key, upload=None, library_id=None):
        self._screen(screen_id)
        settings = self.repos.settings.get()
        return self._apply_owner_asset(
            self._screen_scope(screen_id),
            self.theme_repo.get(screen_id, settings),
            lambda current: self.theme_repo.save(screen_id, current, settings),
            lambda: self.effective_screen_theme(screen_id),
            asset_key,
            upload,
            library_id,
        )

    def reset_screen_asset(self, screen_id, asset_key):
        self._screen(screen_id)
        settings = self.repos.settings.get()
        return self._reset_owner_asset(
            self._screen_scope(screen_id),
            self.theme_repo.get(screen_id, settings),
            lambda current: self.theme_repo.save(screen_id, current, settings),
            lambda: self.effective_screen_theme(screen_id),
            asset_key,
        )

    def screen_asset_path(self, screen_id, asset_key):
        self._screen(screen_id)
        if asset_key not in ASSETS:
            return None
        current = self.theme_repo.get(screen_id)
        assets = current.get("assets") if isinstance(current.get("assets"), dict) else {}
        return self.applied.path(self._screen_scope(screen_id), assets.get(asset_key))

    def group_asset_path(self, group_id, asset_key):
        appearance = self._group_appearance(group_id)
        if asset_key not in ASSETS:
            return None
        reference = str((appearance.get("asset_bindings") or {}).get(asset_key) or "")
        if reference.startswith("applied:"):
            return self.applied.path(self._group_scope(group_id), reference[8:])
        return self._resolve_library_source(asset_key, reference) if reference else None

    def asset_reference(self, asset_key, upload=None, library_id=None):
        if library_id:
            self._resolve_library_source(asset_key, library_id)
            return str(library_id)
        item_id, _url = self.add_library_item(asset_key, upload)
        return f"user:{item_id}"
