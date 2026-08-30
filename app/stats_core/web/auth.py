"""HTTP routes and the lock gate for settings authentication.

Both halves of authentication live here: the four `/api/auth/*` routes, and the
before-request gate that decides which endpoints a locked install may still
reach. The gate used to sit in the composition root, which meant the allowlist
was declared in one file and enforced in another.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

from stats_core.web.common import error_response

# Reachable while the settings PIN is locked. The display has to keep drawing
# on an unattended TV, and the phone needs enough to render its own PIN prompt.
CORE_PUBLIC_ENDPOINTS = frozenset({
    "core.display", "core.health", "core.api_system_version",
    "core.api_config", "core.api_leaderboard",
    "auth.api_auth_status", "auth.api_auth_unlock",
    "organization.team_logo", "product.preview", "product.product_close",
    "tv.report_geometry", "themes.theme_asset",
})


def install_gate(app, auth_service, public_endpoints):
    """Refuse locked requests that are not on the allowlist."""

    @app.before_request
    def settings_lock():
        if not auth_service.pin_is_set() or bool(session.get("settings_unlocked")):
            return None
        endpoint = request.endpoint or ""
        method = request.method.upper()
        path = request.path
        public = (
            endpoint in public_endpoints or endpoint == "static"
            or (method == "GET" and path.startswith("/static/"))
            or (method == "GET" and path.startswith("/api/theme-assets/"))
        )
        if public:
            return None
        if path.startswith("/api/"):
            return jsonify({
                "ok": False, "locked": True,
                "error": "Settings are locked. Enter your PIN.",
            }), 401
        return render_template("settings.html")

    return settings_lock


def blueprint(auth_service):
    bp = Blueprint("auth", __name__)

    @bp.get("/api/auth/status")
    def api_auth_status():
        pin_set = auth_service.pin_is_set()
        return jsonify({
            "ok": True,
            "pin_set": pin_set,
            "unlocked": not pin_set or bool(session.get("settings_unlocked")),
        })

    @bp.post("/api/auth/unlock")
    def api_auth_unlock():
        body = request.get_json(silent=True) or {}
        result = auth_service.attempt_unlock(
            body.get("pin"),
            client_key=request.remote_addr or "unknown",
        )

        if result.retry_after:
            return (
                jsonify({
                    "ok": False,
                    "error": "Too many incorrect PIN attempts. Try again shortly.",
                    "retry_after": result.retry_after,
                }),
                429,
                {"Retry-After": str(result.retry_after)},
            )
        if not result.unlocked:
            return jsonify({"ok": False, "error": "Incorrect PIN."}), 401

        session["settings_unlocked"] = True
        session.permanent = True
        return jsonify({"ok": True, "unlocked": True})

    @bp.post("/api/auth/lock")
    def api_auth_lock():
        session.pop("settings_unlocked", None)
        return jsonify({"ok": True, "unlocked": False})

    @bp.post("/api/auth/pin")
    def api_auth_set_pin():
        body = request.get_json(silent=True) or {}
        try:
            pin_set = auth_service.change_pin(
                body.get("current_pin"),
                body.get("new_pin"),
                already_unlocked=bool(session.get("settings_unlocked")),
            )
        except Exception as exc:
            return error_response(exc)

        if pin_set:
            session["settings_unlocked"] = True
            session.permanent = True
        else:
            session.pop("settings_unlocked", None)
        return jsonify({"ok": True, "pin_set": pin_set})

    return bp
