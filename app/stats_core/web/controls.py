from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(controls):
    bp = Blueprint("controls", __name__)

    @bp.get("/api/keyboard-controls")
    def keyboard_vocabulary():
        # The display asks for the action names, the key map and the screen
        # list rather than carrying its own copy of each.
        return jsonify({"ok": True, "keyboard": controls.vocabulary()})

    @bp.post("/api/keyboard-controls")
    def keyboard():
        try:
            return jsonify({"ok": True, "keyboard": controls.save(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/controls/action")
    def dispatch_action():
        body = request.get_json(silent=True) or {}
        try:
            return jsonify({"ok": True, "state": controls.dispatch(str(body.get("action") or ""))})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/controls/state")
    def action_state():
        return jsonify({"ok": True, "state": controls.screen_controller.state()})

    @bp.delete("/api/controls/action")
    def release_action():
        return jsonify({"ok": True, "state": controls.release()})

    @bp.post("/api/qr-overlay")
    def qr():
        try:
            return jsonify({"ok": True, "qr_overlay": controls.save_qr(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    return bp
