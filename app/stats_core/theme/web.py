"""HTTP boundary for Screen themes and Asset Manager."""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, request, send_file


def blueprint(service):
    bp = Blueprint("themes", __name__)

    @bp.get("/api/screen-themes/<screen_id>")
    def screen_theme(screen_id):
        try:
            return jsonify({"ok": True, "manifest": service.manifest(), "theme": service.effective_screen_theme(screen_id)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.put("/api/screen-themes/<screen_id>")
    def save_screen_theme(screen_id):
        try:
            version, theme = service.save_screen_theme(screen_id, request.get_json(force=True) or {})
            return jsonify({"ok": True, "settings_version": version, "theme": theme})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.delete("/api/screen-themes/<screen_id>")
    def reset_screen_theme(screen_id):
        try:
            version, theme = service.reset_screen_theme(screen_id)
            return jsonify({"ok": True, "settings_version": version, "theme": theme})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.get("/api/asset-library")
    def asset_library():
        return jsonify({"ok": True, "items": service.library_state()})

    @bp.post("/api/asset-library/<asset_key>")
    def add_library_item(asset_key):
        try:
            upload = request.files.get("asset")
            item_id, url = service.add_library_item(
                asset_key,
                upload,
                request.form.get("label") or getattr(upload, "filename", ""),
            )
            return jsonify({"ok": True, "id": f"user:{item_id}", "url": url})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.get("/api/asset-library/<asset_key>/<item_id>")
    def library_item(asset_key, item_id):
        try:
            path = service.library_item_path(asset_key, item_id)
        except Exception:
            path = None
        if not path:
            abort(404)
        return send_file(path, conditional=True)

    @bp.delete("/api/asset-library/<asset_key>/<item_id>")
    def delete_library_item(asset_key, item_id):
        try:
            service.delete_library_item(asset_key, item_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.post("/api/screen-themes/<screen_id>/assets/<asset_key>")
    def upload_screen_theme_asset(screen_id, asset_key):
        try:
            body = request.get_json(silent=True) if not request.files else None
            library_id = (body or {}).get("library_id") if isinstance(body, dict) else None
            upload = request.files.get("asset") if request.files else None
            version, theme = service.apply_screen_asset(
                screen_id,
                asset_key,
                upload=upload,
                library_id=library_id,
            )
            return jsonify({"ok": True, "settings_version": version, "theme": theme})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.delete("/api/screen-themes/<screen_id>/assets/<asset_key>")
    def reset_screen_theme_asset(screen_id, asset_key):
        try:
            version, theme = service.reset_screen_asset(screen_id, asset_key)
            return jsonify({"ok": True, "settings_version": version, "theme": theme})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.get("/api/screen-theme-assets/<screen_id>/<asset_key>")
    def screen_theme_asset(screen_id, asset_key):
        try:
            path = service.screen_asset_path(screen_id, asset_key)
        except Exception:
            path = None
        if not path or not path.exists():
            abort(404)
        return send_file(path, conditional=True)

    return bp
