from flask import Blueprint, jsonify, render_template, request

from stats_core.config import METRIC_DEFS
from stats_core.services.settings import NON_DISPLAY_METRICS
from stats_core.web.common import error_response


def blueprint(runtime):
    bp = Blueprint("core", __name__)

    @bp.get("/")
    def display(): return render_template("display.html")

    @bp.get("/settings")
    def settings_page(): return render_template("settings.html")

    @bp.get("/health")
    def health(): return jsonify({"ok": True})

    @bp.get("/api/system/version")
    def api_system_version(): return jsonify({"ok": True, "version": runtime.version.current()})

    @bp.get("/api/state")
    def api_state():
        settings = runtime.settings.get(); meta = runtime.repos.meta; display_state = runtime.repos.display.get()
        return jsonify({
            "data_version": int(meta.get("data_version", "0") or 0),
            "settings_version": int(meta.get("settings_version", "0") or 0),
            "organization_version": int(meta.get("organization_version", "0") or 0),
            "tv_refresh_version": int(meta.get("tv_refresh_version", "0") or 0),
            "app_restart_version": int(meta.get("app_restart_version", "0") or 0),
            "active_screen_id": display_state["active_screen_id"],
            "last_source_refresh": meta.get("last_source_refresh", ""),
            "source_status": meta.get("source_status", "sample"),
        })

    @bp.get("/api/config")
    def api_config():
        settings = runtime.settings.public(); keyboard = runtime.controls.current(runtime.settings.get())
        settings["keyboard_cycle_views"] = keyboard["views"]; settings["keyboard_cycle_keys"] = keyboard["keys"]
        return jsonify({
            "settings": settings,
            "metrics": [{"key": k, "label": l, "type": t} for k,l,t in METRIC_DEFS if k not in NON_DISPLAY_METRICS],
            "modes": runtime.screens.modes(), "screens": runtime.screens.list(), "display": runtime.display.state(),
            "teams": runtime.repos.organization.list_team_names(), "team_definitions": runtime.organization.definitions_for_api(),
            "leader_candidates": runtime.organization.leader_candidates(), "reps": runtime.organization.rep_summaries(),
        })

    @bp.put("/api/config")
    def api_save_config():
        try:
            saved = runtime.settings.update(request.get_json(silent=True) or {})
            return jsonify({"ok": True, "settings": runtime.settings.public(saved)})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/leaderboard")
    def api_leaderboard():
        mode = request.args.get("mode"); screen_id = request.args.get("screen_id")
        sort_override = request.args.get("sort_metric"); pair = request.args.getlist("team"); settings = runtime.settings.get()
        render_args = {"sort_metric_override": sort_override, "team_pair": pair[:2] if pair else None}
        if screen_id: payload = runtime.display.render(screen_id, **render_args)
        elif mode: payload = runtime.screens.render_mode(mode, **render_args)
        else: payload = runtime.display.render(**render_args)

        custom = payload.get("mode") == "custom_screen"
        numeric_sort_metrics = {k for k,_l,t in METRIC_DEFS if t in ("number","percent","currency") and k != "rank"}
        effective_sort = ""
        if not custom:
            effective_sort = sort_override
            if effective_sort not in numeric_sort_metrics: effective_sort = (settings.get("sort_metric") or {}).get(payload["mode"], "net_split")

        preview = runtime.preview.state(); meta = runtime.repos.meta
        payload.update({
            "title": settings.get("title", "SALES LEADERBOARD"), "subtitle": settings.get("subtitle", ""),
            "sort_metric": effective_sort, "rank_direction": "desc", "currency_symbol": settings.get("currency_symbol", "$"),
            "data_version": int(meta.get("data_version", "0") or 0) + int(preview.get("seq", 0) or 0) * 1000000,
            "preview": preview, "settings_version": int(meta.get("settings_version", "0") or 0),
            "organization_version": int(meta.get("organization_version", "0") or 0),
            "tv_refresh_version": int(meta.get("tv_refresh_version", "0") or 0),
            "app_restart_version": int(meta.get("app_restart_version", "0") or 0),
            "metric_types": {k:t for k,_l,t in METRIC_DEFS}, "metric_labels": {k:l for k,l,_t in METRIC_DEFS},
            "number_font_scale": 100 if custom else int((settings.get("number_font_scale") or {}).get(payload["mode"], 100)),
        })
        payload["theme_state"] = runtime.theme.display_state(settings)
        if custom and payload.get("theme_mode") == "custom":
            payload["screen_theme"] = runtime.theme.effective_screen_theme(payload["screen_id"], settings)
        return jsonify(payload)

    return bp
