"""v119 asset-route compatibility for the Starter base."""
import shutil

from flask import jsonify, request

from database import get_settings
import themes

ALLOWED_BASES = {"starter", "classic", "undisputed"}
_INSTALLED = False


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
        else:
            upload, ext = themes._checked_upload()
            source = None

        folder = themes.PERSISTENT_THEME_ROOT / normalized_scope
        folder.mkdir(parents=True, exist_ok=True)
        themes._remove_old_asset_files(normalized_scope, asset_key)
        # Starter built-ins are SVG; remove a stale SVG too when the user
        # replaces it with a raster upload.
        for candidate in folder.glob(f"{asset_key}*.svg"):
            try:
                candidate.unlink()
            except Exception:
                pass

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
            current.get("base") or themes._default_base(team)
        ).strip().lower()
        if base not in ALLOWED_BASES:
            base = "starter"
        current["base"] = base
        current.setdefault("enabled", True)
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
    if "themes.upload_theme_asset" in app.view_functions:
        app.view_functions["themes.upload_theme_asset"] = _upload_theme_asset
    _INSTALLED = True
    return True
