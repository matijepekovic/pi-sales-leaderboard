"""Theme engine for the Pi sales leaderboard.

The app ships with built-in theme packs (starting with UNDISPUTED), while all
user-created themes and replacement/recolored assets live under the Pi's
persistent data directory so GitHub software updates never erase them.
"""
import json
import os
import re
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, send_file

from database import (
    get_meta,
    get_settings,
    get_team_definitions,
    save_settings,
    set_meta,
)
from tableau_scheduler import start_tableau_scheduler


themes_blueprint = Blueprint("themes", __name__)

APP_DIR = Path(__file__).resolve().parent
BUILTIN_THEME_ROOT = APP_DIR / "static" / "theme-packs"
PERSISTENT_THEME_ROOT = (
    Path.home() / ".local" / "share" / "pi-tableau-leaderboard" / "themes"
)

ASSETS = {
    "background": {"label": "Background", "builtin": "bg.jpg"},
    "hero": {"label": "Hero / Header Art", "builtin": "hero.png"},
    "logo_small": {"label": "Logo Small", "builtin": "hero.png"},
    "row": {"label": "Leaderboard Row", "builtin": "row.jpg"},
    "champion": {"label": "Champion Row", "builtin": "champ.jpg"},
    "medallion": {"label": "Champion Medallion", "builtin": "medallion.png"},
    "corner_tl": {"label": "Top Left Corner", "builtin": "ctl.png", "adjustable": True},
    "corner_tr": {"label": "Top Right Corner", "builtin": "ctr.png", "adjustable": True},
    "corner_bl": {"label": "Bottom Left Corner", "builtin": "cbl.png", "adjustable": True},
    "corner_br": {"label": "Bottom Right Corner", "builtin": "cbr.png", "adjustable": True},
    "totals_mark": {"label": "Totals Mark", "builtin": "totmark.png"},
}

CORNER_ASSET_KEYS = ("corner_tl", "corner_tr", "corner_bl", "corner_br")
DEFAULT_CORNER_SETTINGS = {"size": 100.0, "crop_x": 0.0, "crop_y": 0.0}

UNDISPUTED_COLORS = {
    "primary": "#c58a2a",
    "primary_bright": "#e1ad48",
    "primary_dark": "#6f4612",
    "secondary": "#8b130c",
    "background": "#070706",
    "panel": "#11100d",
    "text": "#e8d6ad",
    "muted": "#a3946f",
    "champion_text": "#f7e7ae",
}

CLASSIC_COLORS = {
    "primary": "#d8b34a",
    "primary_bright": "#e6c760",
    "primary_dark": "#705b20",
    "secondary": "#303030",
    "background": "#080808",
    "panel": "#111111",
    "text": "#f5f5f5",
    "muted": "#9c9c9c",
    "champion_text": "#ffffff",
}

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_ASSET_BYTES = 8 * 1024 * 1024


def _theme_store(settings):
    raw = settings.get("theme_config")
    if not isinstance(raw, dict):
        raw = {}
    teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
    return {"teams": dict(teams)}


def _save_store(settings, store):
    settings["theme_config"] = store
    save_settings(settings)
    version = int(get_meta("settings_version", "0")) + 1
    set_meta("settings_version", version)
    return version


def _team_lookup(include_inactive=False):
    return {
        int(team["team_id"]): team
        for team in get_team_definitions(include_inactive=include_inactive)
    }


def _parse_scope(scope, allow_inactive=False):
    scope = str(scope or "").strip().lower()
    if scope == "office":
        raise ValueError("Whole Office inherits the theme of its #1 rep's team and cannot have its own theme.")
    if scope.startswith("team-"):
        try:
            team_id = int(scope.split("-", 1)[1])
        except Exception:
            raise ValueError("Invalid team theme scope.")
        team = _team_lookup(include_inactive=allow_inactive).get(team_id)
        if not team:
            raise ValueError("Team not found.")
        return f"team-{team_id}", team
    raise ValueError("Theme scope must be team-<id>.")


def _default_base(team=None):
    # UNDISPUTED gets its matching design automatically the first time the
    # theme system is installed. Every other team starts Classic.
    if team and str(team.get("name") or "").strip().lower() == "undisputed":
        return "undisputed"
    return "classic"


def _stored_config(settings, scope, team=None):
    store = _theme_store(settings)
    return dict(store["teams"].get(str(int(team["team_id"])), {}))


def _set_config(settings, scope, team, config):
    store = _theme_store(settings)
    store["teams"][str(int(team["team_id"]))] = config
    return _save_store(settings, store)


def _base_colors(base):
    return dict(UNDISPUTED_COLORS if base == "undisputed" else CLASSIC_COLORS)


def _clean_colors(incoming, base):
    colors = _base_colors(base)
    if isinstance(incoming, dict):
        for key in colors:
            value = str(incoming.get(key) or "").strip()
            if value and COLOR_RE.match(value):
                colors[key] = value.lower()
    return colors


def _bounded_number(value, default, minimum, maximum):
    try:
        value = float(value)
    except Exception:
        return float(default)
    return round(min(max(value, minimum), maximum), 2)


def _clean_corner_settings(incoming):
    cleaned = {}
    if not isinstance(incoming, dict):
        return cleaned
    for key in CORNER_ASSET_KEYS:
        raw = incoming.get(key)
        if not isinstance(raw, dict):
            continue
        cleaned[key] = {
            "size": _bounded_number(raw.get("size"), 100, 50, 250),
            "crop_x": _bounded_number(raw.get("crop_x"), 0, 0, 60),
            "crop_y": _bounded_number(raw.get("crop_y"), 0, 0, 60),
        }
    return cleaned


def _effective_corner_settings(config):
    stored = _clean_corner_settings(config.get("corner_settings"))
    return {
        key: {**DEFAULT_CORNER_SETTINGS, **stored.get(key, {})}
        for key in CORNER_ASSET_KEYS
    }


def _asset_override_path(scope, filename):
    if not filename:
        return None
    filename = Path(str(filename)).name
    path = PERSISTENT_THEME_ROOT / scope / filename
    try:
        path.resolve().relative_to((PERSISTENT_THEME_ROOT / scope).resolve())
    except Exception:
        return None
    return path


def _asset_url(scope, asset_key, config, base, version):
    assets = config.get("assets") if isinstance(config.get("assets"), dict) else {}
    filename = assets.get(asset_key)
    if filename:
        path = _asset_override_path(scope, filename)
        if path and path.exists():
            return f"/api/theme-assets/{scope}/{asset_key}?v={version}"
    if base == "undisputed":
        builtin = ASSETS[asset_key]["builtin"]
        return f"/static/theme-packs/undisputed/{builtin}?v=1"
    return None


def effective_theme(scope, settings=None, team=None):
    settings = settings or get_settings()
    config = _stored_config(settings, scope, team)
    base = str(config.get("base") or _default_base(team)).strip().lower()
    if base not in {"classic", "undisputed"}:
        base = "classic"

    enabled_default = base != "classic"
    enabled = bool(config.get("enabled", enabled_default))
    colors = _clean_colors(config.get("colors"), base)
    version = int(get_meta("settings_version", "0"))

    result = {
        "scope": scope,
        "base": base,
        "enabled": enabled,
        "colors": colors,
        "assets": {},
        "corner_settings": _effective_corner_settings(config),
        "has_custom_assets": False,
    }
    assets_cfg = config.get("assets") if isinstance(config.get("assets"), dict) else {}
    for key in ASSETS:
        result["assets"][key] = _asset_url(scope, key, config, base, version)
        if key in assets_cfg:
            result["has_custom_assets"] = True
    return result


def display_theme_state(settings=None):
    settings = settings or get_settings()
    teams = get_team_definitions()
    team_state = {}
    by_name = {}
    for team in teams:
        team_id = int(team["team_id"])
        theme = effective_theme(f"team-{team_id}", settings=settings, team=team)
        theme["team_id"] = team_id
        theme["team_name"] = team["name"]
        team_state[str(team_id)] = theme
        by_name[str(team["name"]).strip().lower()] = theme

    return {
        "teams": team_state,
        "by_name": by_name,
    }


def _public_team_rows():
    rows = []
    for team in get_team_definitions():
        rows.append({
            "team_id": int(team["team_id"]),
            "name": team["name"],
            "logo_url": (
                f"/api/teams/{int(team['team_id'])}/logo?"
                f"v={int(get_meta('organization_version', '0'))}"
                if team.get("logo_path") else None
            ),
        })
    return rows


def _manifest():
    return {
        "presets": [
            {"key": "classic", "label": "Classic"},
            {"key": "undisputed", "label": "UNDISPUTED"},
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
            for key, value in ASSETS.items()
        ],
        "corner_controls": {
            "size": {"min": 50, "max": 250, "step": 5, "default": 100},
            "crop_x": {"min": 0, "max": 60, "step": 1, "default": 0},
            "crop_y": {"min": 0, "max": 60, "step": 1, "default": 0},
        },
    }


@themes_blueprint.before_app_request
def ensure_tableau_schedule_worker():
    # init_db() has completed by the time Flask serves its first request.
    start_tableau_scheduler()


@themes_blueprint.get("/api/themes")
def themes_state():
    settings = get_settings()
    return jsonify({
        "ok": True,
        "manifest": _manifest(),
        "themes": display_theme_state(settings),
        "teams": _public_team_rows(),
    })


@themes_blueprint.put("/api/themes/<scope>")
def save_theme(scope):
    try:
        normalized_scope, team = _parse_scope(scope)
        incoming = request.get_json(force=True) or {}
        settings = get_settings()
        current = _stored_config(settings, normalized_scope, team)

        base = str(incoming.get("base") or current.get("base") or _default_base(team)).lower()
        if base not in {"classic", "undisputed"}:
            raise ValueError("Unknown theme preset.")

        current["base"] = base
        if isinstance(incoming.get("enabled"), bool):
            current["enabled"] = incoming["enabled"]
        else:
            current.setdefault("enabled", base != "classic")
        current["colors"] = _clean_colors(incoming.get("colors", current.get("colors")), base)
        current.setdefault("assets", {})

        existing_corners = _clean_corner_settings(current.get("corner_settings"))
        if isinstance(incoming.get("corner_settings"), dict):
            existing_corners.update(_clean_corner_settings(incoming.get("corner_settings")))
        current["corner_settings"] = existing_corners

        version = _set_config(settings, normalized_scope, team, current)
        return jsonify({
            "ok": True,
            "settings_version": version,
            "theme": effective_theme(normalized_scope, get_settings(), team),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@themes_blueprint.delete("/api/themes/<scope>")
def reset_theme(scope):
    try:
        normalized_scope, team = _parse_scope(scope)
        settings = get_settings()
        # Reset means Classic explicitly, including for the UNDISPUTED team.
        config = {
            "base": "classic",
            "enabled": False,
            "colors": dict(CLASSIC_COLORS),
            "assets": {},
            "corner_settings": {},
        }
        version = _set_config(settings, normalized_scope, team, config)
        return jsonify({
            "ok": True,
            "settings_version": version,
            "theme": effective_theme(normalized_scope, get_settings(), team),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


def _remove_old_asset_files(scope, asset_key):
    folder = PERSISTENT_THEME_ROOT / scope
    for ext in VALID_EXTENSIONS:
        for candidate in folder.glob(f"{asset_key}*{ext}"):
            try:
                candidate.unlink()
            except Exception:
                pass


@themes_blueprint.post("/api/themes/<scope>/assets/<asset_key>")
def upload_theme_asset(scope, asset_key):
    try:
        normalized_scope, team = _parse_scope(scope)
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")

        upload = request.files.get("asset")
        if not upload or not upload.filename:
            raise ValueError("Choose an image file.")
        ext = Path(upload.filename).suffix.lower()
        if ext not in VALID_EXTENSIONS:
            raise ValueError("Theme assets must be PNG, JPG, or WEBP.")

        upload.stream.seek(0, os.SEEK_END)
        size = upload.stream.tell()
        upload.stream.seek(0)
        if size > MAX_ASSET_BYTES:
            raise ValueError("Theme assets must be under 8 MB.")

        folder = PERSISTENT_THEME_ROOT / normalized_scope
        folder.mkdir(parents=True, exist_ok=True)
        _remove_old_asset_files(normalized_scope, asset_key)
        filename = f"{asset_key}{ext}"
        path = folder / filename
        upload.save(path)

        settings = get_settings()
        current = _stored_config(settings, normalized_scope, team)
        base = str(current.get("base") or _default_base(team)).lower()
        if base not in {"classic", "undisputed"}:
            base = "classic"
        current["base"] = base
        current.setdefault("enabled", True)
        current["colors"] = _clean_colors(current.get("colors"), base)
        current.setdefault("assets", {})[asset_key] = filename
        current["corner_settings"] = _clean_corner_settings(current.get("corner_settings"))
        version = _set_config(settings, normalized_scope, team, current)

        return jsonify({
            "ok": True,
            "settings_version": version,
            "theme": effective_theme(normalized_scope, get_settings(), team),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@themes_blueprint.delete("/api/themes/<scope>/assets/<asset_key>")
def reset_theme_asset(scope, asset_key):
    try:
        normalized_scope, team = _parse_scope(scope)
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")
        _remove_old_asset_files(normalized_scope, asset_key)

        settings = get_settings()
        current = _stored_config(settings, normalized_scope, team)
        assets = current.get("assets") if isinstance(current.get("assets"), dict) else {}
        assets.pop(asset_key, None)
        current["assets"] = assets
        version = _set_config(settings, normalized_scope, team, current)
        return jsonify({
            "ok": True,
            "settings_version": version,
            "theme": effective_theme(normalized_scope, get_settings(), team),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@themes_blueprint.get("/api/theme-assets/<scope>/<asset_key>")
def theme_asset(scope, asset_key):
    """Public custom-theme asset endpoint used by the kiosk TV."""
    try:
        normalized_scope, team = _parse_scope(scope, allow_inactive=True)
    except Exception:
        abort(404)
    if asset_key not in ASSETS:
        abort(404)

    settings = get_settings()
    current = _stored_config(settings, normalized_scope, team)
    assets = current.get("assets") if isinstance(current.get("assets"), dict) else {}
    path = _asset_override_path(normalized_scope, assets.get(asset_key))
    if not path or not path.exists():
        abort(404)
    return send_file(path, conditional=True)
