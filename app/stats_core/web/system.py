"""Update-channel routes.

The URLs are the same on every host; only the answers are host-specific, so the
routes live in core and the platform supplies what they say. They kept their
original endpoint names because the settings page and the auth allowlist both
address them by name.
"""
from __future__ import annotations

from flask import Blueprint, jsonify


def blueprint(platform):
    bp = Blueprint("system", __name__)

    def source_update():
        payload, status = platform.apply_source_update()
        return jsonify(payload), status

    bp.add_url_rule(
        "/api/github/status",
        endpoint="api_github_status",
        methods=["GET"],
        view_func=lambda: jsonify(platform.update_channel()),
    )
    bp.add_url_rule(
        "/api/github/check",
        endpoint="api_github_check",
        methods=["POST"],
        view_func=source_update,
    )
    bp.add_url_rule(
        "/api/system/update",
        endpoint="api_system_update",
        methods=["POST"],
        view_func=source_update,
    )
    return bp
