"""Small platform-neutral HTTP shell for Stats."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template


def blueprint(runtime):
    bp = Blueprint("core", __name__)

    @bp.get("/")
    def display():
        return render_template("display.html")

    @bp.get("/settings")
    def settings_page():
        return render_template("settings.html")

    @bp.get("/health")
    def health():
        return jsonify({"ok": True})

    @bp.get("/api/system/version")
    def api_system_version():
        return jsonify({"ok": True, "version": runtime.version.current()})

    @bp.get("/api/state")
    def api_state():
        meta = runtime.repos.meta
        display_state = runtime.display.state()
        return jsonify({
            "ok": True,
            "data_version": int(meta.get("data_version", "0") or 0),
            "settings_version": int(meta.get("settings_version", "0") or 0),
            "active_screen_id": display_state.get("active_screen_id", ""),
            "current_screen_id": display_state.get("current_screen_id", ""),
        })

    return bp
