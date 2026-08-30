from flask import Blueprint, jsonify, render_template, request

from stats_core.metrics import METRIC_DEFS
from stats_core.services.settings import NON_DISPLAY_METRICS
from stats_core.web.common import error_response


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
        settings = runtime.settings.get()
        meta = runtime.repos.meta
        return jsonify({
            "data_version": int(meta.get("data_version", "0") or 0),
            "settings_version": int(meta.get("settings_version", "0") or 0),
            "organization_version": int(meta.get("organization_version", "0") or 0),
            "tv_refresh_version": int(meta.get("tv_refresh_version", "0") or 0),
            "app_restart_version": int(meta.get("app_restart_version", "0") or 0),
            "active_mode": settings.get("active_mode", "whole_office"),
            "last_source_refresh": meta.get("last_source_refresh", ""),
            "source_status": meta.get("source_status", "sample"),
        })

    @bp.get("/api/config")
    def api_config():
        settings = runtime.settings.public()
        keyboard = runtime.controls.current(runtime.settings.get())
        settings["keyboard_cycle_views"] = keyboard["views"]
        settings["keyboard_cycle_keys"] = keyboard["keys"]
        return jsonify({
            "settings": settings,
            "metrics": [
                {"key": key, "label": label, "type": typ}
                for key, label, typ in METRIC_DEFS if key not in NON_DISPLAY_METRICS
            ],
            "modes": runtime.screens.modes(),
            "teams": runtime.repos.organization.list_team_names(),
            "team_definitions": runtime.organization.definitions_for_api(),
            "leader_candidates": runtime.organization.leader_candidates(),
            "reps": runtime.organization.rep_summaries(),
        })

    @bp.put("/api/config")
    def api_save_config():
        try:
            saved = runtime.settings.update(request.get_json(silent=True) or {})
            return jsonify({"ok": True, "settings": runtime.settings.public(saved)})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/leaderboard")
    def api_leaderboard():
        mode = request.args.get("mode")
        sort_override = request.args.get("sort_metric")
        pair = request.args.getlist("team")
        settings = runtime.settings.get()
        payload = runtime.screens.render(
            mode,
            sort_metric_override=sort_override,
            team_pair=pair[:2] if pair else None,
        )
        numeric_sort_metrics = {
            key for key, _label, typ in METRIC_DEFS
            if typ in ("number", "percent", "currency") and key != "rank"
        }
        effective_sort = sort_override
        if effective_sort not in numeric_sort_metrics:
            effective_sort = (settings.get("sort_metric") or {}).get(payload["mode"], "net_split")
        preview = runtime.preview.state()
        meta = runtime.repos.meta
        payload.update({
            "title": settings.get("title", "SALES LEADERBOARD"),
            "subtitle": settings.get("subtitle", ""),
            "sort_metric": effective_sort,
            "rank_direction": "desc",
            "currency_symbol": settings.get("currency_symbol", "$"),
            "data_version": int(meta.get("data_version", "0") or 0)
                + int(preview.get("seq", 0) or 0) * 1000000,
            "preview": preview,
            "settings_version": int(meta.get("settings_version", "0") or 0),
            "organization_version": int(meta.get("organization_version", "0") or 0),
            "tv_refresh_version": int(meta.get("tv_refresh_version", "0") or 0),
            "app_restart_version": int(meta.get("app_restart_version", "0") or 0),
            "metric_types": {key: typ for key, _label, typ in METRIC_DEFS},
            "metric_labels": {key: label for key, label, _typ in METRIC_DEFS},
            "number_font_scale": int(
                (settings.get("number_font_scale") or {}).get(payload["mode"], 100)
            ),
        })
        payload["theme_state"] = runtime.theme.display_state(settings)
        return jsonify(payload)

    return bp
