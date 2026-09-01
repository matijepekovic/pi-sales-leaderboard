"""HTTP routes for settings authentication."""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from stats_core.web.common import error_response

UNLOCK_SESSION_KEY = "settings_unlock_marker"
LEGACY_UNLOCK_SESSION_KEY = "settings_unlocked"


def _is_unlocked(auth_service):
    return auth_service.session_is_unlocked(session.get(UNLOCK_SESSION_KEY))


def _set_unlocked(auth_service):
    session.pop(LEGACY_UNLOCK_SESSION_KEY, None)
    session[UNLOCK_SESSION_KEY] = auth_service.session_marker()
    session.permanent = False


def _clear_unlocked():
    session.pop(UNLOCK_SESSION_KEY, None)
    session.pop(LEGACY_UNLOCK_SESSION_KEY, None)


def blueprint(auth_service):
    bp = Blueprint("auth", __name__)

    @bp.get("/api/auth/status")
    def api_auth_status():
        pin_set = auth_service.pin_is_set()
        return jsonify({
            "ok": True,
            "pin_set": pin_set,
            "unlocked": not pin_set or _is_unlocked(auth_service),
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

        _set_unlocked(auth_service)
        return jsonify({"ok": True, "unlocked": True})

    @bp.post("/api/auth/lock")
    def api_auth_lock():
        _clear_unlocked()
        return jsonify({"ok": True, "unlocked": False})

    @bp.post("/api/auth/pin")
    def api_auth_set_pin():
        body = request.get_json(silent=True) or {}
        try:
            pin_set = auth_service.change_pin(
                body.get("current_pin"),
                body.get("new_pin"),
                already_unlocked=_is_unlocked(auth_service),
            )
        except Exception as exc:
            return error_response(exc)

        if pin_set:
            _set_unlocked(auth_service)
        else:
            _clear_unlocked()
        return jsonify({"ok": True, "pin_set": pin_set})

    return bp
