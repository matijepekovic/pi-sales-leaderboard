"""v110 remote controls for QR overlay size and position.

The settings page is PIN-protected, so this save route intentionally remains
behind the normal settings lock. The public TV reads the stored values through
the already-public /api/config endpoint.
"""
from flask import jsonify, request

from database import get_meta, get_settings, save_settings, set_meta
import keyboard_controls_v112
import product_controls_v115
import temporary_date_v113

# v113+: layer temporary date rows underneath the existing mapping preview.
# This happens during import, before the first display request is served.
temporary_date_v113.install()

DEFAULT_SIZE = 68
DEFAULT_X = 100.0
DEFAULT_Y = 0.0
MIN_SIZE = 36
MAX_SIZE = 180
_ENDPOINT = "api_qr_overlay_v110"


def _bounded_float(value, default, minimum, maximum):
    try:
        value = float(value)
    except Exception:
        value = float(default)
    return min(max(value, minimum), maximum)


def current_config(settings=None):
    settings = settings or get_settings()
    return {
        "size": int(round(_bounded_float(
            settings.get("qr_overlay_size"), DEFAULT_SIZE, MIN_SIZE, MAX_SIZE
        ))),
        "x": round(_bounded_float(
            settings.get("qr_overlay_x"), DEFAULT_X, 0.0, 100.0
        ), 2),
        "y": round(_bounded_float(
            settings.get("qr_overlay_y"), DEFAULT_Y, 0.0, 100.0
        ), 2),
    }


def _save():
    body = request.get_json(force=True, silent=True) or {}
    settings = get_settings()
    config = {
        "size": int(round(_bounded_float(
            body.get("size"), settings.get("qr_overlay_size", DEFAULT_SIZE),
            MIN_SIZE, MAX_SIZE
        ))),
        "x": round(_bounded_float(
            body.get("x"), settings.get("qr_overlay_x", DEFAULT_X),
            0.0, 100.0
        ), 2),
        "y": round(_bounded_float(
            body.get("y"), settings.get("qr_overlay_y", DEFAULT_Y),
            0.0, 100.0
        ), 2),
    }
    settings["qr_overlay_size"] = config["size"]
    settings["qr_overlay_x"] = config["x"]
    settings["qr_overlay_y"] = config["y"]
    save_settings(settings)
    set_meta("settings_version", int(get_meta("settings_version", "0")) + 1)
    return jsonify({"ok": True, "qr_overlay": config})


def install_routes(app):
    """Attach PIN-protected appliance-control routes during startup."""
    changed = False

    # v116 must load here rather than at module import time. tableau_scheduler
    # imports this module before themes.py has finished loading, so an eager
    # import would create a themes <-> scheduler circular import. By this point
    # server.py has registered the theme blueprint and initialized the DB.
    try:
        import applied_theme_assets_v116
        if applied_theme_assets_v116.install(app):
            changed = True
    except Exception as exc:
        set_meta("v116_applied_theme_assets_status", f"Migration startup failed: {exc}")

    # v117 audits the actual Pi filesystem after v116 has had a chance to
    # migrate/switch the theme store. It intentionally still installs when the
    # v116 migration failed so the remote can report NOT SAFE instead of hiding
    # the problem.
    try:
        import theme_asset_audit_v117
        if theme_asset_audit_v117.install(app):
            changed = True
    except Exception as exc:
        set_meta("v117_theme_asset_audit_status", f"Audit startup failed: {exc}")

    if _ENDPOINT not in app.view_functions:
        app.add_url_rule(
            "/api/qr-overlay",
            endpoint=_ENDPOINT,
            view_func=_save,
            methods=["POST"],
        )
        changed = True
    if keyboard_controls_v112.install_routes(app):
        changed = True
    if temporary_date_v113.install_routes(app):
        changed = True
    if product_controls_v115.install_routes(app):
        changed = True
    return changed
