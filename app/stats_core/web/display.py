"""HTTP boundary for display playback configuration."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(display):
    bp = Blueprint("display_state", __name__)

    @bp.get("/api/display")
    def state():
        try: return jsonify({"ok": True, **display.state()})
        except Exception as exc: return error_response(exc)

    @bp.put("/api/display")
    def save():
        try: return jsonify({"ok": True, **display.save(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc)

    return bp
