"""Production feature-access policy.

Phase 1 keeps every feature that already exists in the application available for
Windows testing.  The policy stays centralized here so a later entitlement
phase can allow/deny individual features without deleting or rebuilding them.

This module also keeps the production-only connection-default cleanup from the
Phase 0/1.0.18 baseline.  That cleanup is not a feature restriction.
"""
import sys

from flask import jsonify, request

from database import get_meta, get_settings, save_settings, set_meta
import keyboard_controls_v112
from sources import tableau_configured

COMING_EVENTUALLY = "Coming eventually"

# Central Phase 1 access policy.  Keep all existing functionality unlocked for
# testing.  Later phases can replace these booleans with entitlement results
# while feature code continues to ask only whether a feature is allowed.
FEATURE_ACCESS = {
    "whole_office": True,
    "per_team": True,
    "team_vs_team": True,
    "all_teams": True,
    "product_close": True,
    "temporary_date": True,
    "themes": True,
    "theme_editor": True,
    "controls": True,
    "settings": True,
}

_INSTALLED = False
_BASE_CONFIG = None
_BASE_SAVE_CONFIG = None
_BASE_GET_MODE_PAYLOAD = None


def can_use(feature):
    """Return whether one existing product feature is currently accessible."""
    return bool(FEATURE_ACCESS.get(str(feature or "").strip(), False))


def feature_access_snapshot():
    """Expose a copy for the Settings UI without allowing client mutation."""
    return dict(FEATURE_ACCESS)


def _feature_for_view(value):
    raw = str(value or "").strip()
    if raw.startswith("per_team::"):
        return "per_team"
    return raw.split("::", 1)[0]


def _view_allowed(value):
    feature = _feature_for_view(value)
    return can_use(feature) if feature else False


def _remove_compiled_connection_defaults():
    """Fresh production installs must never inherit one office's connection.

    Saved customer connection values still live in settings and still win.
    Only the old compiled fallback is removed, so an unconfigured install shows
    blank fields with examples instead of somebody else's server/site/token.
    """
    for key in ("server", "site", "pat_name"):
        tableau_configured.DEFAULTS[key] = ""


def _bump_settings_version():
    try:
        value = int(get_meta("settings_version", "0") or 0) + 1
    except Exception:
        value = 1
    set_meta("settings_version", value)


def _sanitize_saved_settings():
    """Remove only selections that the central policy explicitly disallows."""
    settings = get_settings()
    changed = False

    active = str(settings.get("active_mode") or "whole_office").strip()
    if not _view_allowed(active):
        settings["active_mode"] = "whole_office"
        changed = True

    raw = settings.get("keyboard_cycle_views")
    if isinstance(raw, list):
        cleaned = [str(value) for value in raw if _view_allowed(value)]
        current = [str(value) for value in raw]
        if cleaned != current:
            settings["keyboard_cycle_views"] = cleaned or ["whole_office"]
            changed = True

    if changed:
        save_settings(settings)
        _bump_settings_version()
    return changed


def _patch_rotation_choices():
    """Keep fixed rotation choices aligned with the central access policy."""
    keyboard_controls_v112.FIXED_VIEWS = tuple(
        value for value in keyboard_controls_v112.FIXED_VIEWS if _view_allowed(value)
    )


def _patch_config_read(app):
    """Publish feature access and filter only explicitly restricted screens."""
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

        # This is response-only metadata. api_save_config ignores unknown keys,
        # so the browser cannot persist or change the server-side access policy.
        settings["feature_access"] = feature_access_snapshot()

        active = str(settings.get("active_mode") or "whole_office").strip()
        if not _view_allowed(active):
            settings["active_mode"] = "whole_office"

        available = [
            value for value in keyboard_controls_v112._available_views()
            if _view_allowed(value)
        ]
        raw = settings.get("keyboard_cycle_views")
        if isinstance(raw, list) and raw:
            settings["keyboard_cycle_views"] = [
                str(value) for value in raw if str(value) in available
            ] or list(available[:1])
        else:
            settings["keyboard_cycle_views"] = list(available)

        data["settings"] = settings
        return jsonify(data)

    app.view_functions["api_config"] = production_config


def _patch_config_save(app):
    """Reject a screen only when the central policy says it is unavailable."""
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
            if requested and not _view_allowed(requested):
                return jsonify({"ok": False, "error": COMING_EVENTUALLY}), 409
        return _BASE_SAVE_CONFIG()

    app.view_functions["api_save_config"] = production_save_config


def _patch_disabled_view_rendering():
    """Keep a server-side failsafe for any future restricted screen."""
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
        if raw and not _view_allowed(raw):
            mode = "whole_office"
        return _BASE_GET_MODE_PAYLOAD(
            mode,
            sort_metric_override=sort_metric_override,
            team_vs_team_override=team_vs_team_override,
        )

    server_module.get_mode_payload = production_get_mode_payload


def _patch_temporary_date(app):
    """Preserve the old route gate, but activate it only when policy denies it."""
    if can_use("temporary_date"):
        return

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

    _remove_compiled_connection_defaults()
    _patch_rotation_choices()
    _sanitize_saved_settings()
    _patch_config_read(app)
    _patch_config_save(app)
    _patch_disabled_view_rendering()
    _patch_temporary_date(app)
    _INSTALLED = True
    return True
