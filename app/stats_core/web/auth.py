"""HTTP routes for settings authentication."""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from stats_core.web.common import error_response


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
