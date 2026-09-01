"""HTTP boundary for user-manageable Display Filters."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(filters):
    bp = Blueprint("filters", __name__)

    @bp.get("/api/filters")
    def list_filters():
        try:
            return jsonify({"ok": True, "filters": filters.list()})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/filters")
    def create_filter():
        try:
            return jsonify({"ok": True, "filter": filters.save(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/filters/<filter_id>")
    def update_filter(filter_id):
        body = dict(request.get_json(silent=True) or {})
        body["id"] = filter_id
        try:
            return jsonify({"ok": True, "filter": filters.save(body)})
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/filters/<filter_id>")
    def delete_filter(filter_id):
        try:
            filters.delete(filter_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/filters/preview")
    def preview_filter():
        try:
            return jsonify({"ok": True, **filters.preview(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    return bp
