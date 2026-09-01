"""HTTP boundary for Sources and Reports."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(sources, reports):
    bp = Blueprint("data", __name__)

    @bp.get("/api/data/sources")
    def list_sources():
        try:
            return jsonify({"ok": True, "sources": sources.list()})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/data/sources")
    def create_source():
        try:
            return jsonify({"ok": True, "source": sources.save(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/data/sources/<source_id>")
    def get_source(source_id):
        try:
            return jsonify({"ok": True, "source": sources.get(source_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/data/sources/<source_id>")
    def update_source(source_id):
        body = dict(request.get_json(silent=True) or {})
        body["id"] = source_id
        try:
            return jsonify({"ok": True, "source": sources.save(body)})
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/data/sources/<source_id>")
    def delete_source(source_id):
        try:
            sources.delete(source_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/data/sources/<source_id>/test")
    def test_source(source_id):
        try:
            return jsonify({"ok": True, **sources.test(source_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/data/sources/<source_id>/report-values")
    def source_report_values(source_id):
        try:
            return jsonify({"ok": True, "values": sources.report_values_for(source_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/data/reports")
    def list_reports():
        try:
            return jsonify({"ok": True, "reports": reports.list(request.args.get("source_id"))})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/data/reports")
    def create_report():
        try:
            return jsonify({"ok": True, "report": reports.save(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/data/reports/<report_id>")
    def get_report(report_id):
        try:
            report = dict(reports.get(report_id))
            report["fields"] = reports.fields(report_id)
            report.update(reports.status(report_id))
            return jsonify({"ok": True, "report": report})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/data/reports/<report_id>")
    def update_report(report_id):
        body = dict(request.get_json(silent=True) or {})
        body["id"] = report_id
        try:
            return jsonify({"ok": True, "report": reports.save(body)})
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/data/reports/<report_id>")
    def delete_report(report_id):
        try:
            reports.delete(report_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/data/reports/<report_id>/rows")
    def report_rows(report_id):
        try:
            return jsonify({
                "ok": True,
                "fields": reports.fields(report_id),
                "rows": reports.rows(report_id),
                **reports.status(report_id),
            })
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/data/reports/<report_id>/inspect")
    def inspect_report(report_id):
        try:
            return jsonify({"ok": True, **reports.inspect(report_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/data/reports/<report_id>/refresh")
    def refresh_report(report_id):
        try:
            return jsonify({"ok": True, "result": sources.refresh_report(report_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/data/reports/<report_id>/columns")
    def report_columns(report_id):
        try:
            return jsonify({"ok": True, **sources.columns_for(report_id, request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/data/reports/<report_id>/test")
    def test_report(report_id):
        try:
            return jsonify({"ok": True, **sources.test_report(report_id, request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/data/reports/<report_id>/preview")
    def preview_report(report_id):
        try:
            return jsonify({"ok": True, **sources.preview_report(report_id, request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    return bp
