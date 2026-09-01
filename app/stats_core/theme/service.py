"""Screen-owned visual themes and reusable asset library."""
from __future__ import annotations

import os
import re
from pathlib import Path

from stats_core.theme.catalog import (
    ALLOWED_BASES,
    ASSETS,
    CLASSIC_COLORS,
    CORNER_ASSET_KEYS,
    DEFAULT_CORNER_SETTINGS,
    LIBRARY_KEYS,
    STARTER_COLORS,
    STARTER_FILES,
)

MAX_ASSET_BYTES = 8 * 1024 * 1024
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeService:
    """Owns visual design for Screens.

    Theme has no knowledge of Sources, Reports, Filters, teams, products, or
    display modes. A Screen may use the bundled starter design or a custom
    Screen-specific design. Asset Manager remains a reusable visual resource.
    """

    def __init__(self, repos):
        self.repos = repos
        self.theme_repo = repos.themes
        self.library = repos.asset_library
        self.applied = repos.applied_assets

    def prepare(self):
        self.applied.root.mkdir(parents=True, exist_ok=True)
        return True

    def _screen(self, screen_id):
        screen = self.repos.screens.get(str(screen_id or "").strip())
        if not screen:
            raise ValueError("Screen not found.")
        return screen

    @staticmethod
    def _scope(screen_id):
        return f"screen-{str(screen_id).strip()}"

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
                {"key": key, "label": value["label"], "adjustable": bool(value.get("adjustable"))}
                for key, value in ASSETS.items()
            ],
        }

    def _default_asset_url(self, key, base):
        filename = STARTER_FILES.get(key) if base == "starter" else None
        return f"/static/theme-packs/starter/{filename}" if filename else None

    def effective_screen_theme(self, screen_id, settings=None):
        screen = self._screen(screen_id)
        settings = settings or self.repos.settings.get()
        custom = str(screen.get("theme_mode") or "inherited") == "custom"
        config = self.theme_repo.get(screen_id, settings) if custom else {}
        base = str(config.get("base") or "starter").lower()
        if base not in ALLOWED_BASES:
            base = "starter"
        colors = self.clean_colors(config.get("colors"), base)
        version = int(self.repos.meta.get("settings_version", "0") or 0)
        scope = self._scope(screen_id)
        assets_cfg = config.get("assets") if isinstance(config.get("assets"), dict) else {}
        assets = {}
        for key in ASSETS:
            filename = self.applied.safe_filename(assets_cfg.get(key))
            path = self.applied.path(scope, filename) if filename else None
            if custom and path and path.exists():
                assets[key] = f"/api/screen-theme-assets/{screen_id}/{key}?v={version}"
            else:
                assets[key] = self._default_asset_url(key, base)
        corners = self.clean_corners(config.get("corner_settings"))
        return {
            "scope": scope,
            "mode": "custom" if custom else "inherited",
            "base": base,
            "enabled": True,
            "colors": colors,
            "assets": assets,
            "corner_settings": {
                key: {**DEFAULT_CORNER_SETTINGS, **corners.get(key, {})}
                for key in CORNER_ASSET_KEYS
            },
            "hero_scale": self.bounded(config.get("hero_scale"), 100, 50, 200),
            "row_stripe": self.clean_stripe(config.get("row_stripe"), colors),
            "has_custom_assets": bool(assets_cfg),
        }

    def save_screen_theme(self, screen_id, incoming):
        self._screen(screen_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        settings = self.repos.settings.get()
        current = self.theme_repo.get(screen_id, settings)
        base = str(incoming.get("base") or current.get("base") or "starter").lower()
        if base not in ALLOWED_BASES:
            raise ValueError("Unknown theme preset.")
        current["base"] = base
        current["colors"] = self.clean_colors(incoming.get("colors", current.get("colors")), base)
        current["assets"] = dict(current.get("assets") or {})
        current["corner_settings"] = self.clean_corners(incoming.get("corner_settings", current.get("corner_settings")))
        current["hero_scale"] = self.bounded(incoming.get("hero_scale", current.get("hero_scale")), 100, 50, 200)
        current["row_stripe"] = self.clean_stripe(incoming.get("row_stripe", current.get("row_stripe")), current["colors"])
        version = self.theme_repo.save(screen_id, current, settings)
        return version, self.effective_screen_theme(screen_id)

    def reset_screen_theme(self, screen_id):
        self._screen(screen_id)
        scope = self._scope(screen_id)
        for key in ASSETS:
            self.applied.remove(scope, key)
        version = self.theme_repo.delete(screen_id)
        return version, self.effective_screen_theme(screen_id)

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

    def apply_screen_asset(self, screen_id, asset_key, upload=None, library_id=None):
        self._screen(screen_id)
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")
        scope = self._scope(screen_id)
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
        settings = self.repos.settings.get()
        current = self.theme_repo.get(screen_id, settings)
        current.setdefault("assets", {})[asset_key] = filename
        version = self.theme_repo.save(screen_id, current, settings)
        return version, self.effective_screen_theme(screen_id)

    def reset_screen_asset(self, screen_id, asset_key):
        self._screen(screen_id)
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")
        scope = self._scope(screen_id)
        self.applied.remove(scope, asset_key)
        settings = self.repos.settings.get()
        current = self.theme_repo.get(screen_id, settings)
        assets = dict(current.get("assets") or {})
        assets.pop(asset_key, None)
        current["assets"] = assets
        version = self.theme_repo.save(screen_id, current, settings)
        return version, self.effective_screen_theme(screen_id)

    def screen_asset_path(self, screen_id, asset_key):
        self._screen(screen_id)
        if asset_key not in ASSETS:
            return None
        current = self.theme_repo.get(screen_id)
        assets = current.get("assets") if isinstance(current.get("assets"), dict) else {}
        return self.applied.path(self._scope(screen_id), assets.get(asset_key))
