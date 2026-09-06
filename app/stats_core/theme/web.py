"""HTTP boundary for Screen themes and Asset Manager."""
from __future__ import annotations

from flask import Blueprint, abort, jsonify, request, send_file


def blueprint(service, groups):
    bp = Blueprint("themes", __name__)

    @bp.get("/api/theme-manifest")
    def theme_manifest():
        return jsonify({"ok": True, "manifest": service.manifest()})

    @bp.get("/api/themes")
    def list_themes():
        return jsonify({"ok": True, "themes": service.list_themes()})

    @bp.post("/api/themes/preview")
    def preview_appearance():
        try:
            incoming = request.get_json(silent=True) or {}
            group_id = str(incoming.get("group_id") or "")
            if group_id:
                groups.get(group_id)
            appearance = service.clean_group_appearance(incoming.get("appearance") or {})
            return jsonify({"ok": True, "theme": service.resolve_appearance(appearance, group_id)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.post("/api/themes")
    def create_theme():
        try:
            saved = service.save_theme(request.get_json(silent=True) or {})
            return jsonify({"ok": True, "definition": saved, "theme": service.effective_theme(saved["id"])})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.get("/api/themes/<theme_id>")
    def theme_resource(theme_id):
        try:
            return jsonify({"ok": True, "manifest": service.manifest(), "definition": service.get_theme(theme_id), "theme": service.effective_theme(theme_id)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.put("/api/themes/<theme_id>")
    def save_theme_resource(theme_id):
        try:
            incoming = dict(request.get_json(silent=True) or {})
            incoming["id"] = theme_id
            saved = service.save_theme(incoming)
            return jsonify({"ok": True, "definition": saved, "theme": service.effective_theme(theme_id)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.delete("/api/themes/<theme_id>")
    def delete_theme_resource(theme_id):
        try:
            service.delete_theme(theme_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.post("/api/themes/<theme_id>/assets/<asset_key>")
    def assign_theme_asset(theme_id, asset_key):
        try:
            definition = service.get_theme(theme_id)
            body = request.get_json(silent=True) or {}
            reference = service.asset_reference(asset_key, request.files.get("asset"), body.get("library_id"))
            definition["asset_bindings"] = {**definition.get("asset_bindings", {}), asset_key: reference}
            service.save_theme(definition)
            return jsonify({"ok": True, "theme": service.effective_theme(theme_id)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.delete("/api/themes/<theme_id>/assets/<asset_key>")
    def remove_theme_asset(theme_id, asset_key):
        try:
            definition = service.get_theme(theme_id)
            bindings = dict(definition.get("asset_bindings") or {})
            bindings.pop(asset_key, None)
            definition["asset_bindings"] = bindings
            service.save_theme(definition)
            return jsonify({"ok": True, "theme": service.effective_theme(theme_id)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

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

    @bp.get("/api/group-themes/<group_id>")
    def group_theme(group_id):
        try:
            return jsonify({"ok": True, "manifest": service.manifest(), "appearance": groups.appearance(group_id), "theme": service.effective_group_theme(group_id)})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.put("/api/group-themes/<group_id>")
    def save_group_theme(group_id):
        try:
            version, theme = groups.save_appearance(group_id, request.get_json(force=True) or {})
            return jsonify({"ok": True, "settings_version": version, "theme": theme})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.delete("/api/group-themes/<group_id>")
    def reset_group_theme(group_id):
        try:
            version, theme = groups.reset_appearance(group_id)
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

    @bp.post("/api/group-themes/<group_id>/assets/<asset_key>")
    def upload_group_theme_asset(group_id, asset_key):
        try:
            body = request.get_json(silent=True) if not request.files else None
            library_id = (body or {}).get("library_id") if isinstance(body, dict) else None
            upload = request.files.get("asset") if request.files else None
            version, theme = groups.apply_asset(
                group_id,
                asset_key,
                upload=upload,
                library_id=library_id,
            )
            return jsonify({"ok": True, "settings_version": version, "theme": theme})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.delete("/api/group-themes/<group_id>/assets/<asset_key>")
    def reset_group_theme_asset(group_id, asset_key):
        try:
            version, theme = groups.reset_asset(group_id, asset_key)
            return jsonify({"ok": True, "settings_version": version, "theme": theme})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    @bp.get("/api/group-theme-assets/<group_id>/<asset_key>")
    def group_theme_asset(group_id, asset_key):
        try:
            path = service.group_asset_path(group_id, asset_key)
        except Exception:
            path = None
        if not path or not path.exists():
            abort(404)
        return send_file(path, conditional=True)

    return bp
