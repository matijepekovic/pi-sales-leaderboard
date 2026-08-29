from flask import Blueprint, jsonify, request
from stats_core.web.common import error_response


def blueprint(service):
    bp = Blueprint("tv", __name__)

    @bp.post("/api/tv/fullscreen")
    def fullscreen():
        try: return jsonify({"ok": True, **service.fullscreen()})
        except Exception as exc: return error_response(exc, 500)

    @bp.post("/api/tv/geometry")
    def report_geometry():
        body = request.get_json(silent=True) or {}
        try: return jsonify({"ok": True, **service.report_geometry(body.get("w"), body.get("h"))})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/tv/geometry")
    def geometry(): return jsonify({"ok": True, **service.geometry()})

    @bp.post("/api/tv/refresh")
    def refresh(): return jsonify({"ok": True, "tv_refresh_version": service.refresh()})

    @bp.post("/api/tv/restart")
    def restart(): return jsonify({"ok": True, **service.restart()})

    return bp
