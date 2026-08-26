"""Production-only feature gates.

Keep unfinished views visible in Settings, but prevent them from being activated
or placed in the physical screen rotation. Development/main does not import this
module, so the office Pi keeps every feature available.
"""
import sys

from flask import jsonify, request

from database import get_meta, get_settings, save_settings, set_meta
import keyboard_controls_v112

COMING_EVENTUALLY = "Coming eventually"
DISABLED_VIEW_MODES = {"team_vs_team", "all_teams"}
_INSTALLED = False
_BASE_CONFIG = None
_BASE_SAVE_CONFIG = None
_BASE_GET_MODE_PAYLOAD = None


def _bump_settings_version():
    try:
        value = int(get_meta("settings_version", "0") or 0) + 1
    except Exception:
        value = 1
    set_meta("settings_version", value)


def _sanitize_saved_settings():
    settings = get_settings()
    changed = False

    if str(settings.get("active_mode") or "whole_office").strip() != "whole_office":
        settings["active_mode"] = "whole_office"
        changed = True

    raw = settings.get("keyboard_cycle_views")
    if isinstance(raw, list):
        cleaned = [
            str(value)
            for value in raw
            if str(value).strip() not in DISABLED_VIEW_MODES
        ]
        if cleaned != [str(value) for value in raw]:
            settings["keyboard_cycle_views"] = cleaned or ["whole_office"]
            changed = True

    if changed:
        save_settings(settings)
        _bump_settings_version()
    return changed


def _patch_rotation_choices():
    keyboard_controls_v112.FIXED_VIEWS = tuple(
        value
        for value in keyboard_controls_v112.FIXED_VIEWS
        if value not in DISABLED_VIEW_MODES
    )


def _patch_config_read(app):
    """Give the TV only production-allowed rotation choices.

    The TV's physical-control script reads keyboard_cycle_views directly from
    /api/config. When the user has never saved a custom rotation, supply the
    current allowed list dynamically so Team vs Team and All Teams can never be
    reached by Previous/Next, while new Per-Team screens still appear normally.
    """
    global _BASE_CONFIG
    if _BASE_CONFIG is not None:
        return
    _BASE_CONFIG = app.view_functions.get("api_config")
    if _BASE_CONFIG is None:
        return

    def production_config():
        response = _BASE_CONFIG()
        data = response.get_json() or {}
        settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        settings["active_mode"] = "whole_office"

        available = keyboard_controls_v112._available_views()
        raw = settings.get("keyboard_cycle_views")
        if isinstance(raw, list) and raw:
            settings["keyboard_cycle_views"] = [
                str(value) for value in raw if str(value) in available
            ] or ["whole_office"]
        else:
            settings["keyboard_cycle_views"] = list(available)

        data["settings"] = settings
        return jsonify(data)

    app.view_functions["api_config"] = production_config


def _patch_config_save(app):
    global _BASE_SAVE_CONFIG
    if _BASE_SAVE_CONFIG is not None:
        return
    _BASE_SAVE_CONFIG = app.view_functions.get("api_save_config")
    if _BASE_SAVE_CONFIG is None:
        return

    def production_save_config():
        body = request.get_json(silent=True) or {}
        if isinstance(body, dict) and "active_mode" in body:
            requested = str(body.get("active_mode") or "").strip()
            if requested != "whole_office":
                return jsonify({"ok": False, "error": COMING_EVENTUALLY}), 409
        return _BASE_SAVE_CONFIG()

    app.view_functions["api_save_config"] = production_save_config


def _patch_disabled_view_rendering():
    global _BASE_GET_MODE_PAYLOAD
    if _BASE_GET_MODE_PAYLOAD is not None:
        return

    server_module = sys.modules.get("server") or sys.modules.get("__main__")
    if server_module is None:
        return
    _BASE_GET_MODE_PAYLOAD = getattr(server_module, "get_mode_payload", None)
    if _BASE_GET_MODE_PAYLOAD is None:
        return

    def production_get_mode_payload(
        mode=None, sort_metric_override=None, team_vs_team_override=None
    ):
        raw = str(mode or "").strip()
        parsed = raw.split("::", 1)[0]
        if parsed in DISABLED_VIEW_MODES:
            mode = "whole_office"
        return _BASE_GET_MODE_PAYLOAD(
            mode,
            sort_metric_override=sort_metric_override,
            team_vs_team_override=team_vs_team_override,
        )

    server_module.get_mode_payload = production_get_mode_payload


def _patch_temporary_date(app):
    endpoint = "api_temporary_date_override_v113"
    if endpoint not in app.view_functions:
        return

    def coming_eventually():
        return jsonify({"ok": False, "error": COMING_EVENTUALLY}), 409

    app.view_functions[endpoint] = coming_eventually


def install(app):
    global _INSTALLED
    if _INSTALLED:
        return False

    _patch_rotation_choices()
    _sanitize_saved_settings()
    _patch_config_read(app)
    _patch_config_save(app)
    _patch_disabled_view_rendering()
    _patch_temporary_date(app)
    _INSTALLED = True
    return True
