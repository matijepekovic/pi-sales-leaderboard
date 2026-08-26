"""v119 neutral Starter theme pack.

Starter is the default for new/implicit team themes. Existing Classic and
migrated UNDISPUTED themes remain supported exactly as stored. The shipped
Starter artwork is only the seed: once a team saves/applies Starter, v116
materializes its SVG assets into the persistent applied-theme-assets store.
"""
from pathlib import Path

from flask import jsonify, request

from database import get_meta, get_settings
import themes

STARTER_COLORS = dict(themes.CLASSIC_COLORS)
ALLOWED_BASES = {"starter", "classic", "undisputed"}
STARTER_FILES = {
    "background": "background.svg",
    "hero": "hero.svg",
    "logo_small": "hero.svg",
    "row": "row.svg",
    "champion": "champion.svg",
    "medallion": "medallion.svg",
    "corner_tl": "corner-tl.svg",
    "corner_tr": "corner-tr.svg",
    "corner_bl": "corner-bl.svg",
    "corner_br": "corner-br.svg",
    "totals_mark": "totals-mark.svg",
}

_INSTALLED = False
_BASE_RESOLVE_LIBRARY_SOURCE = None


def _starter_source(asset_key):
    filename = STARTER_FILES.get(asset_key)
    if not filename:
        return None
    path = themes.BUILTIN_THEME_ROOT / "starter" / filename
    return path if path.exists() and path.is_file() else None


def _default_base(team=None):
    return "starter"


def _base_colors(base):
    base = str(base or "").strip().lower()
    if base == "starter":
        return dict(STARTER_COLORS)
    if base == "undisputed":
        return dict(themes.UNDISPUTED_COLORS)
    return dict(themes.CLASSIC_COLORS)


def _asset_url(scope, asset_key, config, base, version):
    assets = config.get("assets") if isinstance(config.get("assets"), dict) else {}
    filename = assets.get(asset_key)
    if filename:
        path = themes._asset_override_path(scope, filename)
        if path and path.exists():
            return f"/api/theme-assets/{scope}/{asset_key}?v={version}"

    if base == "starter":
        source = _starter_source(asset_key)
        if source:
            return f"/static/theme-packs/starter/{source.name}?v=119"

    # UNDISPUTED is legacy-only now. Its migrated explicit assets still work,
    # but there is deliberately no shipped fallback artwork anymore.
    return None


def _effective_theme(scope, settings=None, team=None):
    settings = settings or get_settings()
    config = themes._stored_config(settings, scope, team)
    base = str(config.get("base") or themes._default_base(team)).strip().lower()
    if base not in ALLOWED_BASES:
        base = "starter"

    enabled_default = base != "classic"
    enabled = bool(config.get("enabled", enabled_default))
    colors = themes._clean_colors(config.get("colors"), base)
    version = int(get_meta("settings_version", "0"))

    result = {
        "scope": scope,
        "base": base,
        "enabled": enabled,
        "colors": colors,
        "assets": {},
        "corner_settings": themes._effective_corner_settings(config),
        "hero_scale": themes._clean_hero_scale(config.get("hero_scale")),
        "row_stripe": themes._clean_row_stripe(config.get("row_stripe"), colors),
        "has_custom_assets": False,
    }
    assets_cfg = config.get("assets") if isinstance(config.get("assets"), dict) else {}
    for key in themes.ASSETS:
        result["assets"][key] = themes._asset_url(scope, key, config, base, version)
        if key in assets_cfg:
            result["has_custom_assets"] = True
    return result


def _manifest():
    return {
        "presets": [
            {"key": "starter", "label": "Starter"},
            {"key": "classic", "label": "Plain"},
            {"key": "undisputed", "label": "UNDISPUTED (existing)"},
        ],
        "colors": [
            {"key": "primary", "label": "Primary"},
            {"key": "primary_bright", "label": "Primary Bright"},
            {"key": "primary_dark", "label": "Primary Dark"},
            {"key": "secondary", "label": "Secondary"},
            {"key": "background", "label": "Background"},
            {"key": "panel", "label": "Panel"},
            {"key": "text", "label": "Text"},
            {"key": "muted", "label": "Muted Text"},
            {"key": "champion_text", "label": "Champion Text"},
        ],
        "assets": [
            {
                "key": key,
                "label": value["label"],
                "adjustable": bool(value.get("adjustable")),
            }
            for key, value in themes.ASSETS.items()
        ],
        "corner_controls": {
            "size": {"min": 50, "max": 600, "step": 5, "default": 100},
            "crop_x": {"min": 0, "max": 60, "step": 1, "default": 0},
            "crop_y": {"min": 0, "max": 60, "step": 1, "default": 0},
        },
        "theme_controls": {
            "hero_scale": {"min": 50, "max": 200, "step": 5, "default": 100},
            "row_stripe_strength": {"min": 0, "max": 100, "step": 5, "default": 0},
        },
    }


def _save_theme(scope):
    try:
        normalized_scope, team = themes._parse_scope(scope)
        incoming = request.get_json(force=True) or {}
        settings = get_settings()
        current = themes._stored_config(settings, normalized_scope, team)

        base = str(
            incoming.get("base") or current.get("base") or themes._default_base(team)
        ).strip().lower()
        if base not in ALLOWED_BASES:
            raise ValueError("Unknown theme preset.")

        current["base"] = base
        if isinstance(incoming.get("enabled"), bool):
            current["enabled"] = incoming["enabled"]
        else:
            current.setdefault("enabled", base != "classic")
        current["colors"] = themes._clean_colors(
            incoming.get("colors", current.get("colors")), base
        )
        current.setdefault("assets", {})

        existing_corners = themes._clean_corner_settings(current.get("corner_settings"))
        if isinstance(incoming.get("corner_settings"), dict):
            existing_corners.update(
                themes._clean_corner_settings(incoming.get("corner_settings"))
            )
        current["corner_settings"] = existing_corners
        current["hero_scale"] = themes._clean_hero_scale(
            incoming.get("hero_scale", current.get("hero_scale"))
        )
        current["row_stripe"] = themes._clean_row_stripe(
            incoming.get("row_stripe", current.get("row_stripe")),
            current.get("colors"),
        )

        version = themes._set_config(settings, normalized_scope, team, current)
        return jsonify({
            "ok": True,
            "settings_version": version,
            "theme": themes.effective_theme(normalized_scope, get_settings(), team),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def _reset_theme(scope):
    try:
        normalized_scope, team = themes._parse_scope(scope)
        settings = get_settings()
        config = {
            "base": "starter",
            "enabled": True,
            "colors": dict(STARTER_COLORS),
            "assets": {},
            "corner_settings": {},
            "hero_scale": 100.0,
            "row_stripe": {
                "color": STARTER_COLORS["primary"],
                "strength": 0.0,
            },
        }
        version = themes._set_config(settings, normalized_scope, team, config)
        return jsonify({
            "ok": True,
            "settings_version": version,
            "theme": themes.effective_theme(normalized_scope, get_settings(), team),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def _patch_builtin_library_resolution():
    global _BASE_RESOLVE_LIBRARY_SOURCE
    if _BASE_RESOLVE_LIBRARY_SOURCE is not None:
        return
    _BASE_RESOLVE_LIBRARY_SOURCE = themes._resolve_library_source

    def resolve_v119(asset_key, library_id):
        raw = str(library_id or "").strip()
        prefix = "builtin:/static/theme-packs/starter/"
        if raw.startswith(prefix):
            filename = Path(raw[len(prefix):].split("?", 1)[0]).name
            expected = STARTER_FILES.get(asset_key)
            if filename != expected:
                raise ValueError("Unknown Starter preset.")
            source = _starter_source(asset_key)
            if not source:
                raise ValueError("That Starter asset is unavailable.")
            return source
        return _BASE_RESOLVE_LIBRARY_SOURCE(asset_key, library_id)

    themes._resolve_library_source = resolve_v119


def _patch_v116():
    """Teach the persistent-applied-asset layer about Starter SVGs."""
    try:
        import applied_theme_assets_v116 as applied
    except Exception:
        return

    def safe_filename_v119(value):
        filename = Path(str(value or "")).name
        ext = Path(filename).suffix.lower()
        if not filename or ext not in (set(themes.VALID_EXTENSIONS) | {".svg"}):
            return ""
        return filename

    def builtin_source_v119(base, asset_key):
        if base != "starter":
            return None
        return _starter_source(asset_key)

    def materialize_v119(scope, team, config, initial_migration=False):
        result = dict(config or {})
        base = str(result.get("base") or themes._default_base(team)).strip().lower()
        if base not in ALLOWED_BASES:
            base = "starter"
        result["base"] = base

        raw_assets = result.get("assets") if isinstance(result.get("assets"), dict) else {}
        assets = dict(raw_assets)
        changed = assets != raw_assets

        for asset_key in themes.ASSETS:
            configured = safe_filename_v119(assets.get(asset_key))
            destination = (
                applied.APPLIED_THEME_ASSET_ROOT / scope / configured
                if configured else None
            )
            if destination is not None and destination.exists() and not initial_migration:
                continue

            legacy_source = None
            if configured:
                candidate = applied.LEGACY_THEME_ROOT / scope / configured
                if candidate.exists() and candidate.is_file():
                    legacy_source = candidate

            if legacy_source is not None:
                applied._copy_verified(
                    legacy_source,
                    destination,
                    replace_existing=bool(initial_migration),
                )
                continue

            builtin = builtin_source_v119(base, asset_key)
            if builtin is not None:
                ext = builtin.suffix.lower()
                filename = f"{asset_key}{ext}"
                target = applied.APPLIED_THEME_ASSET_ROOT / scope / filename
                applied._copy_verified(
                    builtin,
                    target,
                    replace_existing=bool(initial_migration),
                )
                if assets.get(asset_key) != filename:
                    assets[asset_key] = filename
                    changed = True

        result["assets"] = assets
        return result, changed

    applied._safe_filename = safe_filename_v119
    applied._builtin_source = builtin_source_v119
    applied._materialize_config = materialize_v119

    # Materialize Starter now for any team that had never explicitly saved a
    # theme. Existing Classic/UNDISPUTED configs are left exactly as stored.
    try:
        applied.ensure_all_applied_assets(initial_migration=False)
    except Exception:
        pass


def install(app):
    global _INSTALLED
    if _INSTALLED:
        return False

    themes._default_base = _default_base
    themes._base_colors = _base_colors
    themes._asset_url = _asset_url
    themes.effective_theme = _effective_theme
    themes._manifest = _manifest
    _patch_builtin_library_resolution()
    _patch_v116()

    # The blueprint is already registered when appliance controls install.
    # Replace only the two handlers whose old code hard-coded the old presets.
    if "themes.save_theme" in app.view_functions:
        app.view_functions["themes.save_theme"] = _save_theme
    if "themes.reset_theme" in app.view_functions:
        app.view_functions["themes.reset_theme"] = _reset_theme

    _INSTALLED = True
    return True
