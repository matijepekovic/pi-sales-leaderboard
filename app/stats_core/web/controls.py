from flask import Blueprint, jsonify, request
from stats_core.web.common import error_response


def blueprint(controls, temporary_date):
    bp = Blueprint("controls", __name__)

    @bp.post("/api/keyboard-controls")
    def keyboard():
        try: return jsonify({"ok": True, "keyboard": controls.save(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc)

    @bp.post("/api/qr-overlay")
    def qr():
        try: return jsonify({"ok": True, "qr_overlay": controls.save_qr(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/temporary-date-override")
    def temporary_state(): return jsonify({"ok": True, "override": temporary_date.state()})

    @bp.post("/api/temporary-date-override")
    def temporary_apply():
        try: return jsonify({"ok": True, "override": temporary_date.activate(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc, default_status=502)

    @bp.delete("/api/temporary-date-override")
    def temporary_cancel(): return jsonify({"ok": True, "override": temporary_date.cancel()})

    return bp
