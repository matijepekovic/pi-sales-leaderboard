"""Windows-only persistent visual Theme Builder transforms."""
from __future__ import annotations

import threading

from flask import jsonify, request

STORE_KEY = "theme_visual_transforms"
ASSET_KEYS = {
    "background",
    "hero",
    "row",
    "champion",
    "medallion",
    "corner_tl",
    "corner_tr",
    "corner_bl",
    "corner_br",
    "totals_mark",
}
DEFAULT_TRANSFORM = {
    "x": 0.0,
    "y": 0.0,
    "scale_x": 100.0,
    "scale_y": 100.0,
    "rotation": 0.0,
    "opacity": 100.0,
}
_LOCK = threading.RLock()


def _bounded(value, default, minimum, maximum):
    try:
        value = float(value)
    except Exception:
        value = float(default)
    return round(min(max(value, minimum), maximum), 2)


def clean_transform(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "x": _bounded(raw.get("x"), 0, -300, 300),
        "y": _bounded(raw.get("y"), 0, -300, 300),
        "scale_x": _bounded(raw.get("scale_x"), 100, 20, 500),
        "scale_y": _bounded(raw.get("scale_y"), 100, 20, 500),
        "rotation": _bounded(raw.get("rotation"), 0, -180, 180),
        "opacity": _bounded(raw.get("opacity"), 100, 0, 100),
    }


def _valid_team_ids(organization_repo):
    return {
        int(team["team_id"])
        for team in organization_repo.definitions()
    }


def _store(settings_repo, settings=None):
    settings = settings or settings_repo.get()
    raw = settings.get(STORE_KEY)
    teams = (
        raw.get("teams")
        if isinstance(raw, dict) and isinstance(raw.get("teams"), dict)
        else {}
    )
    cleaned = {}
    for team_id, assets in teams.items():
        if not isinstance(assets, dict):
            continue
        cleaned[str(team_id)] = {
            key: clean_transform(value)
            for key, value in assets.items()
            if key in ASSET_KEYS and isinstance(value, dict)
        }
    return {"teams": cleaned}


def _save(repos, settings, store):
    settings[STORE_KEY] = store
    repos.settings.save(settings)
    return repos.meta.bump("settings_version")


def install(app, repos, public_endpoints=None):
    if "windows_theme_transforms" in app.view_functions:
        return

    def get_transforms():
        return jsonify({
            "ok": True,
            "defaults": dict(DEFAULT_TRANSFORM),
            "teams": _store(repos.settings)["teams"],
        })

    def save_transform(team_id):
        team_id = int(team_id)
        if team_id not in _valid_team_ids(repos.organization):
            return jsonify({"ok": False, "error": "Team not found."}), 404

        body = request.get_json(silent=True) or {}
        key = str(body.get("asset") or "").strip()
        if key not in ASSET_KEYS:
            return jsonify({"ok": False, "error": "Unknown theme asset."}), 400

        transform = clean_transform(body.get("transform"))
        with _LOCK:
            settings = repos.settings.get()
            store = _store(repos.settings, settings)
            team = store["teams"].setdefault(str(team_id), {})
            team[key] = transform
            version = _save(repos, settings, store)

        return jsonify({
            "ok": True,
            "team_id": team_id,
            "asset": key,
            "transform": transform,
            "settings_version": version,
        })

    def reset_transform(team_id, asset_key):
        team_id = int(team_id)
        key = str(asset_key or "").strip()
        if key not in ASSET_KEYS:
            return jsonify({"ok": False, "error": "Unknown theme asset."}), 400

        with _LOCK:
            settings = repos.settings.get()
            store = _store(repos.settings, settings)
            team = store["teams"].get(str(team_id), {})
            team.pop(key, None)
            if not team:
                store["teams"].pop(str(team_id), None)
            version = _save(repos, settings, store)

        return jsonify({
            "ok": True,
            "team_id": team_id,
            "asset": key,
            "transform": dict(DEFAULT_TRANSFORM),
            "settings_version": version,
        })

    app.add_url_rule(
        "/api/windows/theme-transforms",
        endpoint="windows_theme_transforms",
        view_func=get_transforms,
        methods=["GET"],
    )
    app.add_url_rule(
        "/api/windows/theme-transforms/<int:team_id>",
        endpoint="windows_theme_transform_save",
        view_func=save_transform,
        methods=["PUT"],
    )
    app.add_url_rule(
        "/api/windows/theme-transforms/<int:team_id>/<asset_key>",
        endpoint="windows_theme_transform_reset",
        view_func=reset_transform,
        methods=["DELETE"],
    )
    if public_endpoints is not None:
        public_endpoints.add("windows_theme_transforms")
