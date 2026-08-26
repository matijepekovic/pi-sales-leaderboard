"""v112 configurable physical controls for screen and measuring-stat actions.

The remote uses dropdowns instead of key capture so the controls work cleanly
from a phone. Keyboard keys and mouse inputs share one mapping model.
"""
from flask import jsonify, request

from database import get_meta, get_settings, get_team_definitions, save_settings, set_meta

_ENDPOINT = "api_keyboard_controls_v112"
ACTIONS = ("previous", "next", "pair", "sort_prev", "sort_next")
DEFAULT_KEYS = {
    "previous": "ArrowLeft",
    "next": "ArrowRight",
    "pair": "ArrowUp",
    "sort_prev": "MouseWheelUp",
    "sort_next": "MouseWheelDown",
}
FIXED_VIEWS = ("whole_office", "team_vs_team", "all_teams")

ALLOWED_INPUTS = (
    "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
    *tuple(chr(code) for code in range(ord("a"), ord("z") + 1)),
    *tuple(str(n) for n in range(10)),
    "PageUp", "PageDown", "Home", "End", "Enter", " ", "[", "]",
    "MouseWheelUp", "MouseWheelDown",
    "MouseLeft", "MouseRight", "MouseMiddle",
)
_ALLOWED_SET = set(ALLOWED_INPUTS)


def _available_views():
    views = list(FIXED_VIEWS)
    for team in get_team_definitions():
        name = str(team.get("name") or "").strip()
        if name:
            views.append(f"per_team::{name}")
    return views


def _normalize_input(value):
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
        "home": "Home", "end": "End",
        "enter": "Enter", "return": "Enter",
        "space": " ", "spacebar": " ",
        "mousewheelup": "MouseWheelUp", "wheelup": "MouseWheelUp",
        "mousewheeldown": "MouseWheelDown", "wheeldown": "MouseWheelDown",
        "mouseleft": "MouseLeft", "leftclick": "MouseLeft",
        "mouseright": "MouseRight", "rightclick": "MouseRight",
        "mousemiddle": "MouseMiddle", "middleclick": "MouseMiddle",
    }
    lowered = value.lower()
    if lowered in aliases:
        return aliases[lowered]
    if len(value) == 1:
        value = value.lower()
    return value if value in _ALLOWED_SET else ""


def _clean_keys(settings):
    raw = settings.get("keyboard_cycle_keys")
    raw = raw if isinstance(raw, dict) else {}
    cleaned = {}
    used = set()

    for action in ACTIONS:
        candidate = _normalize_input(raw.get(action)) or DEFAULT_KEYS[action]
        if candidate in used:
            candidate = DEFAULT_KEYS[action]
        if candidate in used:
            candidate = next(value for value in ALLOWED_INPUTS if value not in used)
        cleaned[action] = candidate
        used.add(candidate)
    return cleaned


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

    return {"views": views, "keys": _clean_keys(settings)}


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
        current = _clean_keys(settings)
        keys = {}
        for action in ACTIONS:
            value = _normalize_input(raw_keys.get(action)) or current[action]
            if value not in _ALLOWED_SET:
                return jsonify({"ok": False, "error": "Choose an input from the dropdown."}), 400
            keys[action] = value
        if len(set(keys.values())) != len(keys):
            return jsonify({"ok": False, "error": "Each control must use a different input."}), 400
        settings["keyboard_cycle_keys"] = keys

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
