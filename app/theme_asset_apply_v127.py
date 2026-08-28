"""v127 reliable theme asset apply path.

The original asset endpoint predates the Starter base. Applying or recoloring an
asset could therefore coerce a Starter theme back to Classic, and setdefault on
the enabled flag meant an already-disabled theme stayed disabled after editing.

Keep the existing asset/library/storage helpers, including v116 permanent
applied-asset storage, but make the saved theme state match the user's action:
editing artwork preserves the current valid base and activates the theme.
"""
from __future__ import annotations

import shutil

from flask import jsonify, request

from database import get_settings
import themes

_INSTALLED = False
ALLOWED_BASES = {"starter", "classic", "undisputed"}


def _upload_theme_asset(scope, asset_key):
    try:
        normalized_scope, team = themes._parse_scope(scope)
        if asset_key not in themes.ASSETS:
            raise ValueError("Unknown theme asset.")

        body = request.get_json(silent=True) if not request.files else None
        library_id = (body or {}).get("library_id") if isinstance(body, dict) else None

        if library_id:
            source = themes._resolve_library_source(asset_key, library_id)
            ext = source.suffix.lower()
            upload = None
        else:
            upload, ext = themes._checked_upload()
            source = None

        # v116 changes PERSISTENT_THEME_ROOT to the protected applied-assets
        # folder during startup. Use the live value rather than a copied path.
        folder = themes.PERSISTENT_THEME_ROOT / normalized_scope
        folder.mkdir(parents=True, exist_ok=True)
        themes._remove_old_asset_files(normalized_scope, asset_key)
        filename = f"{asset_key}{ext}"
        path = folder / filename

        if source is not None:
            shutil.copyfile(source, path)
        else:
            upload.save(path)
            themes._file_into_library(asset_key, path, upload.filename, ext)

        settings = get_settings()
        current = themes._stored_config(settings, normalized_scope, team)
        base = str(
            current.get("base") or themes._default_base(team) or "starter"
        ).strip().lower()
        if base not in ALLOWED_BASES:
            base = "starter"

        current["base"] = base
        # An artwork edit is an explicit request to use this design. Do not
        # leave the newly-edited theme disabled because of an older checkbox.
        current["enabled"] = True
        current["colors"] = themes._clean_colors(current.get("colors"), base)
        current.setdefault("assets", {})[asset_key] = filename
        current["corner_settings"] = themes._clean_corner_settings(
            current.get("corner_settings")
        )

        version = themes._set_config(settings, normalized_scope, team, current)
        return jsonify({
            "ok": True,
            "settings_version": version,
            "theme": themes.effective_theme(normalized_scope, get_settings(), team),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def install(app):
    global _INSTALLED
    if _INSTALLED:
        return False
    endpoint = "themes.upload_theme_asset"
    if endpoint not in app.view_functions:
        return False
    app.view_functions[endpoint] = _upload_theme_asset
    _INSTALLED = True
    return True
