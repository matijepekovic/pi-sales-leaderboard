"""Theme engine for the Pi sales leaderboard.

The app ships with built-in theme packs (starting with UNDISPUTED), while all
user-created themes and replacement/recolored assets live under the Pi's
persistent data directory so GitHub software updates never erase them.
"""
import json
import os
import re
import shutil
import time
import uuid
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

# A whole-sheet upload holding all four ornaments. It is a library-only key:
# the browser splits it into quadrants and applies those to the four corner
# assets, so the sheet itself is never a theme asset.
CORNER_SHEET_KEY = "corner_sheet"
LIBRARY_KEYS = set(ASSETS) | {CORNER_SHEET_KEY}

# Artwork the user has uploaded, tinted or recolored, kept so it can be reused
# on any team later. It cannot live in the theme folder: _remove_old_asset_files
# deletes the previous file every time an asset is replaced, which would erase
# the library on the next upload.
ASSET_LIBRARY_ROOT = (
    Path.home() / ".local" / "share" / "pi-tableau-leaderboard" / "asset-library"
)
BUILTIN_LIBRARY_ROOT = APP_DIR / "static" / "asset-library"
# The shipped catalog points at both the library folder and the theme packs,
# so a built-in preset may live under either. Both are read-only app content.
BUILTIN_URL_ROOTS = {
    "/static/asset-library/": BUILTIN_LIBRARY_ROOT,
    "/static/theme-packs/": APP_DIR / "static" / "theme-packs",
}
ITEM_ID_RE = re.compile(r"^[a-z0-9]{6,40}$")
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


def _checked_extension(filename):
    ext = Path(filename or "").suffix.lower()
    if ext not in VALID_EXTENSIONS:
        raise ValueError("Theme assets must be PNG, JPG, or WEBP.")
    return ext


def _checked_upload(field="asset"):
    upload = request.files.get(field)
    if not upload or not upload.filename:
        raise ValueError("Choose an image file.")
    ext = _checked_extension(upload.filename)
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > MAX_ASSET_BYTES:
        raise ValueError("Theme assets must be under 8 MB.")
    return upload, ext


# ------------------------------------------------------------------ library

def _library_key(asset_key):
    if asset_key not in LIBRARY_KEYS:
        raise ValueError("Unknown theme asset.")
    return asset_key


def _library_dir(asset_key):
    return ASSET_LIBRARY_ROOT / _library_key(asset_key)


def _read_library_index(asset_key):
    path = _library_dir(asset_key) / "index.json"
    try:
        rows = json.loads(path.read_text())
        return [r for r in rows if isinstance(r, dict) and ITEM_ID_RE.match(str(r.get("id", "")))]
    except Exception:
        return []


def _write_library_index(asset_key, rows):
    folder = _library_dir(asset_key)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.json").write_text(json.dumps(rows, indent=2))


def _library_item_path(asset_key, item_id):
    if not ITEM_ID_RE.match(str(item_id or "")):
        return None
    for row in _read_library_index(asset_key):
        if str(row.get("id")) == str(item_id):
            candidate = _library_dir(asset_key) / f"{item_id}{row.get('ext', '.png')}"
            return candidate if candidate.exists() else None
    return None


def _user_library_items(asset_key):
    items = []
    for row in _read_library_index(asset_key):
        item_id = str(row.get("id"))
        items.append({
            "id": f"user:{item_id}",
            "label": str(row.get("label") or item_id),
            "url": f"/api/asset-library/{asset_key}/{item_id}",
            "created": row.get("created", ""),
            "source": "user",
            "deletable": True,
        })
    items.sort(key=lambda r: str(r.get("created")), reverse=True)
    return items


def _builtin_library_items():
    """The shipped catalog, regrouped by the asset key each entry targets."""
    grouped = {}
    try:
        raw = json.loads((BUILTIN_LIBRARY_ROOT / "catalog.json").read_text())
    except Exception:
        return grouped
    for collection in raw.get("collections") or []:
        cname = str(collection.get("label") or collection.get("key") or "Built-in")
        for item in collection.get("items") or []:
            label = str(item.get("label") or item.get("key") or "Preset")
            for target_key, url in (item.get("targets") or {}).items():
                if target_key not in LIBRARY_KEYS or not str(url or "").strip():
                    continue
                grouped.setdefault(target_key, []).append({
                    "id": f"builtin:{url}",
                    "label": f"{cname} — {label}",
                    "url": url,
                    "source": "builtin",
                    "deletable": False,
                })
    return grouped


def _resolve_library_source(asset_key, library_id):
    """A library id -> a readable file on disk. Never escapes its root."""
    raw = str(library_id or "").strip()
    if raw.startswith("user:"):
        path = _library_item_path(asset_key, raw[5:])
        if not path:
            raise ValueError("That saved item is no longer available.")
        return path
    if raw.startswith("builtin:"):
        url = raw[8:].split("?", 1)[0]
        for prefix, root in BUILTIN_URL_ROOTS.items():
            if not url.startswith(prefix):
                continue
            candidate = (root / url[len(prefix):]).resolve()
            # Must sit inside its own root: blocks ../ escapes outright.
            if root.resolve() not in candidate.parents:
                break
            if not candidate.exists() or candidate.suffix.lower() not in VALID_EXTENSIONS:
                break
            return candidate
    raise ValueError("Unknown preset.")


def _file_into_library(asset_key, source_path, label, ext):
    """Keep a copy of artwork so it can be reused on any team, forever."""
    try:
        item_id = uuid.uuid4().hex[:16]
        folder = _library_dir(asset_key)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, folder / f"{item_id}{ext}")
        rows = _read_library_index(asset_key)
        rows.insert(0, {
            "id": item_id,
            "label": str(label or "Untitled")[:120],
            "ext": ext,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        _write_library_index(asset_key, rows[:200])
        return item_id
    except Exception:
        # The library is a convenience; never fail the actual save because of it.
        return ""


@themes_blueprint.get("/api/asset-library")
def asset_library():
    builtin = _builtin_library_items()
    return jsonify({
        "ok": True,
        "items": {
            key: builtin.get(key, []) + _user_library_items(key)
            for key in sorted(LIBRARY_KEYS)
        },
    })


@themes_blueprint.post("/api/asset-library/<asset_key>")
def add_library_item(asset_key):
    try:
        _library_key(asset_key)
        upload, ext = _checked_upload()
        folder = _library_dir(asset_key)
        folder.mkdir(parents=True, exist_ok=True)
        item_id = uuid.uuid4().hex[:16]
        upload.save(folder / f"{item_id}{ext}")
        rows = _read_library_index(asset_key)
        rows.insert(0, {
            "id": item_id,
            "label": str(request.form.get("label") or upload.filename or "Untitled")[:120],
            "ext": ext,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        _write_library_index(asset_key, rows[:200])
        return jsonify({"ok": True, "id": f"user:{item_id}",
                        "url": f"/api/asset-library/{asset_key}/{item_id}"})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@themes_blueprint.get("/api/asset-library/<asset_key>/<item_id>")
def library_item(asset_key, item_id):
    try:
        _library_key(asset_key)
    except Exception:
        abort(404)
    path = _library_item_path(asset_key, item_id)
    if not path:
        abort(404)
    return send_file(path, conditional=True)


@themes_blueprint.delete("/api/asset-library/<asset_key>/<item_id>")
def delete_library_item(asset_key, item_id):
    try:
        _library_key(asset_key)
        path = _library_item_path(asset_key, item_id)
        if not path:
            raise ValueError("That saved item is no longer available.")
        path.unlink(missing_ok=True)
        _write_library_index(
            asset_key,
            [r for r in _read_library_index(asset_key) if str(r.get("id")) != str(item_id)],
        )
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@themes_blueprint.post("/api/themes/<scope>/assets/<asset_key>")
def upload_theme_asset(scope, asset_key):
    try:
        normalized_scope, team = _parse_scope(scope)
        if asset_key not in ASSETS:
            raise ValueError("Unknown theme asset.")

        # Applying something already on the Pi is a server-side copy: the phone
        # never re-uploads bytes it has already sent once.
        body = request.get_json(silent=True) if not request.files else None
        library_id = (body or {}).get("library_id") if isinstance(body, dict) else None

        if library_id:
            source = _resolve_library_source(asset_key, library_id)
            ext = source.suffix.lower()
        else:
            upload, ext = _checked_upload()
            source = None

        folder = PERSISTENT_THEME_ROOT / normalized_scope
        folder.mkdir(parents=True, exist_ok=True)
        _remove_old_asset_files(normalized_scope, asset_key)
        filename = f"{asset_key}{ext}"
        path = folder / filename
        if source is not None:
            shutil.copyfile(source, path)
        else:
            upload.save(path)
            _file_into_library(asset_key, path, upload.filename, ext)

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
