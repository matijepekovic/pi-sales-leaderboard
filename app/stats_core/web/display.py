"""HTTP boundary for display playback configuration and rendering."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from stats_core.web.common import error_response


def blueprint(display, theme):
    bp = Blueprint("display_state", __name__)

    @bp.get("/api/display")
    def state():
        try:
            return jsonify({"ok": True, **display.state()})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/display")
    def save():
        try:
            return jsonify({"ok": True, **display.save(request.get_json(silent=True) or {})})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/display/render")
    def render():
        try:
            payload = display.render(request.args.get("screen_id"))
            screen_id = str(payload.get("screen_id") or "").strip()
            if screen_id:
                payload["theme"] = theme.effective_screen_theme(screen_id)
            else:
                payload["theme"] = None
            return jsonify({"ok": True, "payload": payload})
        except Exception as exc:
            return error_response(exc)

    return bp
