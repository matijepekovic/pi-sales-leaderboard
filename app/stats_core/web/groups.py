"""HTTP boundary for generic Groups."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(groups):
    bp = Blueprint("groups", __name__)

    @bp.get("/api/group-types")
    def list_group_types():
        try:
            return jsonify({"ok": True, "group_types": groups.list_types()})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/group-types")
    def create_group_type():
        try:
            return jsonify({"ok": True, "group_type": groups.save_type(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/group-types/<type_id>")
    def update_group_type(type_id):
        body = dict(request.get_json(silent=True) or {})
        body["id"] = type_id
        try:
            return jsonify({"ok": True, "group_type": groups.save_type(body)})
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/group-types/<type_id>")
    def delete_group_type(type_id):
        try:
            groups.delete_type(type_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/group-types/<type_id>/rows")
    def group_type_rows(type_id):
        try:
            return jsonify({
                "ok": True,
                **groups.rows_for_type(
                    type_id,
                    request.args.get("report_id"),
                    request.args.get("member_field"),
                ),
            })
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/groups")
    def list_groups():
        try:
            return jsonify({"ok": True, "groups": groups.list()})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/groups")
    def create_group():
        try:
            return jsonify({"ok": True, "group": groups.save(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/groups/<group_id>")
    def update_group(group_id):
        body = dict(request.get_json(silent=True) or {})
        body["id"] = group_id
        try:
            return jsonify({"ok": True, "group": groups.save(body)})
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/groups/<group_id>")
    def delete_group(group_id):
        try:
            groups.delete(group_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/groups/<group_id>/appearance")
    def group_appearance(group_id):
        try:
            return jsonify({"ok": True, "appearance": groups.appearance(group_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/groups/<group_id>/appearance")
    def save_group_appearance(group_id):
        try:
            version, theme = groups.save_appearance(group_id, request.get_json(silent=True) or {})
            return jsonify({"ok": True, "settings_version": version, "appearance": groups.appearance(group_id), "theme": theme})
        except Exception as exc:
            return error_response(exc)

    return bp
