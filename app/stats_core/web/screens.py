"""HTTP boundary for screen definitions and live previews."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(screens):
    bp = Blueprint("screens", __name__)

    @bp.get("/api/screens")
    def list_screens():
        try: return jsonify({"ok": True, "screens": screens.list()})
        except Exception as exc: return error_response(exc)

    @bp.post("/api/screens")
    def create_screen():
        try: return jsonify({"ok": True, "screen": screens.save(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/screens/<screen_id>")
    def get_screen(screen_id):
        try: return jsonify({"ok": True, "screen": screens.get(screen_id)})
        except Exception as exc: return error_response(exc)

    @bp.put("/api/screens/<screen_id>")
    def update_screen(screen_id):
        body = dict(request.get_json(silent=True) or {})
        body["id"] = screen_id
        try: return jsonify({"ok": True, "screen": screens.save(body)})
        except Exception as exc: return error_response(exc)

    @bp.delete("/api/screens/<screen_id>")
    def delete_screen(screen_id):
        try: screens.delete(screen_id); return jsonify({"ok": True})
        except Exception as exc: return error_response(exc)

    @bp.post("/api/screens/preview")
    def preview_unsaved():
        try: return jsonify({"ok": True, "payload": screens.preview(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/screens/<screen_id>/preview")
    def preview_saved(screen_id):
        try: return jsonify({"ok": True, "payload": screens.render(screen_id)})
        except Exception as exc: return error_response(exc)

    return bp
