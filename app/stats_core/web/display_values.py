"""HTTP boundary for user-manageable Display Values."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(display_values):
    bp = Blueprint("display_values", __name__)

    @bp.get("/api/display-values")
    def list_display_values():
        try:
            report_id = str(request.args.get("report_id") or "").strip() or None
            return jsonify({"ok": True, "display_values": display_values.list(report_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/display-values/<display_value_id>")
    def rename_display_value(display_value_id):
        try:
            item = display_values.rename(display_value_id, request.get_json(silent=True) or {})
            return jsonify({"ok": True, "display_value": item})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/display-values/<display_value_id>/values")
    def list_values(display_value_id):
        try:
            return jsonify({"ok": True, "values": display_values.values(display_value_id)})
        except Exception as exc:
            return error_response(exc)

    return bp
