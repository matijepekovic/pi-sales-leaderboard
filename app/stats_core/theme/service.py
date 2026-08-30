from __future__ import annotations

import os
from pathlib import Path

from stats_core.theme.catalog import ALLOWED_BASES, ASSETS, LIBRARY_KEYS
from stats_core.theme.config import ThemeConfigMixin

MAX_ASSET_BYTES = 8 * 1024 * 1024


class ThemeService(ThemeConfigMixin):
    """Owns themes, reusable assets and protected applied assets.

    This replaces the old themes.py + v116/v119/v127 runtime patch chain. The
    public HTTP contract and persistent file locations stay the same.
    """

    def __init__(self, repos):
        self.repos = repos
        self.theme_repo = repos.themes
        self.library = repos.asset_library
        self.applied = repos.applied_assets

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
        item_id, _path = self.library.save_upload(
            asset_key, upload, ext, label or upload.filename or "Untitled"
        )
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
            valid = {
                str(item.get("url") or "")
                for item in self._builtin_library_items().get(asset_key, [])
            }
            if url not in valid:
                raise ValueError("Unknown preset.")
            path = self.library.resolve_builtin_url(url)
            if path:
                return path
        raise ValueError("Unknown preset.")

    def apply_asset(self, scope, asset_key, upload=None, library_id=None):
        normalized, team = self.parse_scope(scope)
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")

        if library_id:
            source = self._resolve_library_source(asset_key, library_id)
            _path, filename = self.applied.copy(normalized, asset_key, source)
        else:
            ext = self._checked_upload(upload)
            path, filename = self.applied.save_upload(normalized, asset_key, upload, ext)
            # The reusable library is convenience only; never fail the applied save.
            try:
                self.library.add_file(asset_key, path, upload.filename, ext)
            except Exception:
                pass

        settings = self.repos.settings.get()
        current = self._stored(team, settings)
        base = str(current.get("base") or "starter").strip().lower()
        if base not in ALLOWED_BASES:
            base = "starter"
        current["base"] = base
        current["enabled"] = True
        current["colors"] = self.clean_colors(current.get("colors"), base)
        current.setdefault("assets", {})[asset_key] = filename
        current["corner_settings"] = self.clean_corners(current.get("corner_settings"))
        version = self._save(team, current, settings)
        return version, self.effective_theme(normalized, self.repos.settings.get(), team)

    def reset_asset(self, scope, asset_key):
        normalized, team = self.parse_scope(scope)
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")
        self.applied.remove(normalized, asset_key)
        settings = self.repos.settings.get()
        current = self._stored(team, settings)
        assets = current.get("assets") if isinstance(current.get("assets"), dict) else {}
        assets = dict(assets)
        assets.pop(asset_key, None)
        current["assets"] = assets
        version = self._save(team, current, settings)
        return version, self.effective_theme(normalized, self.repos.settings.get(), team)

    def asset_path(self, scope, asset_key):
        normalized, team = self.parse_scope(scope, allow_inactive=True)
        if asset_key not in ASSETS:
            return None
        current = self._stored(team)
        assets = current.get("assets") if isinstance(current.get("assets"), dict) else {}
        return self.applied.path(normalized, assets.get(asset_key))
