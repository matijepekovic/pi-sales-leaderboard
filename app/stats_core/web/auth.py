from flask import Blueprint, jsonify, request, session
from stats_core.web.common import error_response


def blueprint(auth_service):
    bp = Blueprint("auth", __name__)

    @bp.get("/api/auth/status")
    def api_auth_status():
        return jsonify({"ok": True, "pin_set": auth_service.pin_is_set(), "unlocked": (not auth_service.pin_is_set() or bool(session.get("settings_unlocked")))})

    @bp.post("/api/auth/unlock")
    def api_auth_unlock():
        body = request.get_json(silent=True) or {}; stored = auth_service.pin_hash()
        if not stored: return jsonify({"ok": True, "unlocked": True})
        if not auth_service.verify_pin(str(body.get("pin") or ""), stored): return jsonify({"ok": False, "error": "Incorrect PIN."}), 401
        session["settings_unlocked"] = True; session.permanent = True
        return jsonify({"ok": True, "unlocked": True})

    @bp.post("/api/auth/lock")
    def api_auth_lock():
        session.pop("settings_unlocked", None); return jsonify({"ok": True, "unlocked": False})

    @bp.post("/api/auth/pin")
    def api_auth_set_pin():
        body = request.get_json(silent=True) or {}
        try: pin_set = auth_service.change_pin(body.get("current_pin"), body.get("new_pin"), bool(session.get("settings_unlocked")))
        except Exception as exc: return error_response(exc)
        if pin_set:
            session["settings_unlocked"] = True; session.permanent = True
        else: session.pop("settings_unlocked", None)
        return jsonify({"ok": True, "pin_set": pin_set})

    return bp
