from flask import Blueprint, abort, jsonify, request, send_file
from stats_core.web.common import error_response


def blueprint(service):
    bp = Blueprint("organization", __name__)

    @bp.get("/api/organization")
    def organization_snapshot():
        """Normalized organization contract for Settings clients."""
        return jsonify({
            "ok": True,
            "teams": service.definitions_for_api(),
            "reps": service.rep_summaries(),
        })

    @bp.post("/api/team-builder/save")
    def save_builder():
        try:
            team_id = service.save_builder(request.get_json(silent=True) or {})
            return jsonify({"ok": True, "team_id": team_id, "team_definitions": service.definitions_for_api(), "teams": service.repos.organization.list_team_names()})
        except Exception as exc: return error_response(exc)

    @bp.post("/api/teams/<int:team_id>/logo")
    def upload_logo(team_id):
        try: return jsonify({"ok": True, "logo_url": service.save_logo(team_id, request.files.get("logo"))})
        except Exception as exc: return error_response(exc)

    @bp.delete("/api/teams/<int:team_id>/logo")
    def delete_logo(team_id):
        try: service.delete_logo(team_id); return jsonify({"ok": True})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/teams/<int:team_id>/logo")
    def team_logo(team_id):
        path = service.logo_path(team_id)
        if path is None or not path.exists(): abort(404)
        return send_file(path, conditional=True)

    @bp.post("/api/teams")
    def create_team():
        try:
            team_id = service.create((request.get_json(silent=True) or {}).get("name"))
            return jsonify({"ok": True, "team_id": team_id, "teams": service.repos.organization.definitions()})
        except Exception as exc: return error_response(exc)

    @bp.put("/api/teams/<int:team_id>")
    def rename_team(team_id):
        try: service.rename(team_id, (request.get_json(silent=True) or {}).get("name")); return jsonify({"ok": True, "teams": service.repos.organization.definitions()})
        except Exception as exc: return error_response(exc)

    @bp.delete("/api/teams/<int:team_id>")
    def delete_team(team_id):
        try:
            result = service.delete_team(team_id, (request.get_json(silent=True) or {}).get("reassignments", []))
            return jsonify({"ok": True, "deleted_team": result["name"], "reassigned_reps": result["member_count"], "team_definitions": service.definitions_for_api(), "teams": service.repos.organization.list_team_names()})
        except Exception as exc: return error_response(exc)

    @bp.put("/api/teams/<int:team_id>/leader")
    def set_leader(team_id):
        body = request.get_json(silent=True) or {}
        try:
            lead_id = service.set_leader(team_id, body.get("lead_name"), body.get("lead_role", "Sales Manager"))
            return jsonify({"ok": True, "lead_id": lead_id, "teams": service.repos.organization.definitions()})
        except Exception as exc: return error_response(exc)

    @bp.delete("/api/team-leads/<int:lead_id>")
    def delete_leader(lead_id):
        try: service.delete_leader(lead_id); return jsonify({"ok": True, "teams": service.repos.organization.definitions()})
        except Exception as exc: return error_response(exc)

    @bp.put("/api/rep-team-assignments")
    def assignments():
        body = request.get_json(silent=True) or {}
        try:
            service.assign_reps(body.get("assignments", []))
            return jsonify({"ok": True, "teams": service.repos.organization.list_team_names(), "team_definitions": service.definitions_for_api(), "reps": service.rep_summaries()})
        except Exception as exc: return error_response(exc)

    return bp
