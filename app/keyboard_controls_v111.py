"""v111 keyboard screen-rotation settings.

The TV reads these values from the existing public /api/config payload. Writes
stay behind the normal Settings PIN because this route is not public.
"""
from flask import jsonify, request

from database import get_meta, get_settings, get_team_definitions, save_settings, set_meta

_ENDPOINT = "api_keyboard_controls_v111"
DEFAULT_KEYS = {"previous": "ArrowLeft", "next": "ArrowRight"}
FIXED_VIEWS = ("whole_office", "team_vs_team", "all_teams")


def _available_views():
    views = list(FIXED_VIEWS)
    for team in get_team_definitions():
        name = str(team.get("name") or "").strip()
        if name:
            views.append(f"per_team::{name}")
    return views


def _normalize_key(value):
    raw = str(value or "")
    if raw == " ":
        return " "
    value = raw.strip()
    aliases = {
        "left": "ArrowLeft", "arrowleft": "ArrowLeft",
        "right": "ArrowRight", "arrowright": "ArrowRight",
        "up": "ArrowUp", "arrowup": "ArrowUp",
        "down": "ArrowDown", "arrowdown": "ArrowDown",
        "pageup": "PageUp", "pagedown": "PageDown",
        "enter": "Enter", "return": "Enter",
        "space": " ", "spacebar": " ",
        "tab": "Tab", "escape": "Escape", "esc": "Escape",
    }
    lowered = value.lower()
    if lowered in aliases:
        return aliases[lowered]
    if len(value) == 1:
        return value.lower()
    return value[:32]


def current_config(settings=None):
    settings = settings or get_settings()
    available = _available_views()
    raw_views = settings.get("keyboard_cycle_views")
    if isinstance(raw_views, list):
        views = [str(v) for v in raw_views if str(v) in available]
    else:
        views = list(available)
    if not views:
        views = list(available[:1])

    raw_keys = settings.get("keyboard_cycle_keys")
    raw_keys = raw_keys if isinstance(raw_keys, dict) else {}
    previous = _normalize_key(raw_keys.get("previous") or DEFAULT_KEYS["previous"])
    next_key = _normalize_key(raw_keys.get("next") or DEFAULT_KEYS["next"])
    if not previous:
        previous = DEFAULT_KEYS["previous"]
    if not next_key or next_key == previous:
        next_key = DEFAULT_KEYS["next"]
    return {"views": views, "keys": {"previous": previous, "next": next_key}}


def _save():
    body = request.get_json(force=True, silent=True) or {}
    settings = get_settings()
    available = _available_views()

    if "views" in body:
        if not isinstance(body.get("views"), list):
            return jsonify({"ok": False, "error": "Screens must be a list."}), 400
        selected = []
        for raw in body["views"]:
            value = str(raw)
            if value in available and value not in selected:
                selected.append(value)
        if not selected:
            return jsonify({"ok": False, "error": "Select at least one screen."}), 400
        settings["keyboard_cycle_views"] = selected

    if "keys" in body:
        raw_keys = body.get("keys")
        if not isinstance(raw_keys, dict):
            return jsonify({"ok": False, "error": "Map Keys must be an object."}), 400
        current = current_config(settings)["keys"]
        previous = _normalize_key(raw_keys.get("previous") or current["previous"])
        next_key = _normalize_key(raw_keys.get("next") or current["next"])
        if not previous or not next_key:
            return jsonify({"ok": False, "error": "Both screen keys are required."}), 400
        if previous == next_key:
            return jsonify({"ok": False, "error": "Previous and Next must use different keys."}), 400
        settings["keyboard_cycle_keys"] = {"previous": previous, "next": next_key}

    save_settings(settings)
    set_meta("settings_version", int(get_meta("settings_version", "0")) + 1)
    return jsonify({"ok": True, "keyboard": current_config(settings)})


def install_routes(app):
    if _ENDPOINT in app.view_functions:
        return False
    app.add_url_rule(
        "/api/keyboard-controls",
        endpoint=_ENDPOINT,
        view_func=_save,
        methods=["POST"],
    )
    return True
