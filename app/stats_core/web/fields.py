"""HTTP boundary for the centralized Fields catalog."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(fields):
    bp = Blueprint("fields", __name__)

    @bp.get("/api/fields/catalog")
    def global_field_catalog():
        try:
            return jsonify({"ok": True, "reports": fields.catalog_all()})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/fields")
    def field_reports():
        try:
            reports = []
            for report in fields.reports.list():
                item = dict(report)
                item["fields"] = fields.fields(item["id"])
                reports.append(item)
            return jsonify({"ok": True, "reports": reports})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/fields/compatibility")
    def field_compatibility():
        try:
            incoming = request.get_json(silent=True) or {}
            return jsonify({"ok": True, **fields.compatibility(incoming.get("field_ids"))})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/fields/identity-options")
    def identity_options():
        try:
            incoming = request.get_json(silent=True) or {}
            return jsonify({"ok": True, "fields": fields.identity_fields(incoming.get("field_ids"))})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/fields/matches")
    def matching_rules():
        try:
            return jsonify({"ok": True, "rules": fields.matching_rules()})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/fields/matches/preview")
    def preview_matching():
        try:
            incoming = request.get_json(silent=True) or {}
            return jsonify({"ok": True, **fields.preview_matching(incoming, str(incoming.get("id") or ""))})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/fields/matches")
    def create_matching():
        try:
            return jsonify({"ok": True, "rule": fields.save_matching(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/fields/matches/<rule_id>")
    def update_matching(rule_id):
        try:
            return jsonify({"ok": True, "rule": fields.save_matching(request.get_json(silent=True) or {}, rule_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/fields/matches/<rule_id>")
    def delete_matching(rule_id):
        try:
            fields.delete_matching(rule_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/fields/<report_id>")
    def field_catalog(report_id):
        try:
            return jsonify({"ok": True, **fields.catalog(report_id, request.args.get("sample_limit", 8))})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/fields/<report_id>")
    def create_field(report_id):
        try:
            return jsonify({"ok": True, "field": fields.save(report_id, request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/fields/<report_id>/preview")
    def preview_calculated_field(report_id):
        try:
            return jsonify({"ok": True, "payload": fields.preview_calculated(
                report_id, request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/fields/<report_id>/<field_key>")
    def update_field(report_id, field_key):
        try:
            return jsonify({
                "ok": True,
                "field": fields.save(report_id, request.get_json(silent=True) or {}, field_key),
            })
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/fields/<report_id>/<field_key>")
    def delete_field(report_id, field_key):
        try:
            fields.delete(report_id, field_key)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    return bp
