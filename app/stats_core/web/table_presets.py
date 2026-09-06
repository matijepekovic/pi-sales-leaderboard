"""HTTP boundary for reusable table presets."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(presets):
    bp = Blueprint("table_presets", __name__)

    @bp.get("/api/table-presets")
    def list_presets():
        try:
            return jsonify({
                "ok": True,
                "table_presets": presets.list(request.args.get("report_id")),
            })
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/table-presets")
    def create_preset():
        try:
            return jsonify({
                "ok": True,
                "table_preset": presets.save(request.get_json(silent=True) or {}),
            })
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/table-presets/<preset_id>")
    def update_preset(preset_id):
        try:
            return jsonify({
                "ok": True,
                "table_preset": presets.save(request.get_json(silent=True) or {}, preset_id),
            })
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/table-presets/<preset_id>")
    def delete_preset(preset_id):
        try:
            presets.delete(preset_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    return bp
