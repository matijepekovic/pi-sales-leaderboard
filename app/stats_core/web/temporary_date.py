"""Routes for the temporary data-window override.

These sat in the controls blueprint, which made the controls surface look like
it owned the reporting window. It does not -- this is a data concern that
happens to be reachable from the same settings page.
"""
from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(temporary_date):
    bp = Blueprint("temporary_date", __name__)

    @bp.get("/api/temporary-date-override")
    def temporary_state():
        return jsonify({"ok": True, "override": temporary_date.state()})

    @bp.post("/api/temporary-date-override")
    def temporary_apply():
        try:
            return jsonify({"ok": True, "override": temporary_date.activate(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc, default_status=502)

    @bp.delete("/api/temporary-date-override")
    def temporary_cancel():
        return jsonify({"ok": True, "override": temporary_date.cancel()})

    return bp
