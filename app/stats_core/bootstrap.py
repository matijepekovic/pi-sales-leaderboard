"""Stats application composition root.

This is the only place where repositories, source adapters, services and HTTP
boundaries are assembled. Product modules do not construct or monkey-patch one
another at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from sources.tableau_adapter import TableauAdapter
from stats_core.paths import prepare_data_dir
from stats_core.platform.windows import WindowsPlatform
from stats_core.repositories import Repositories
from stats_core.runtime import Runtime
from stats_core.services.auth import AuthService
from stats_core.services.display import DisplayService
from stats_core.services.filters import FilterService
from stats_core.services.reports import ReportService
from stats_core.services.screens import ScreenService
from stats_core.services.settings import SettingsService
from stats_core.services.source import SourceService
from stats_core.services.version import VersionService
from stats_core.theme import ThemeService
from stats_core.theme import web as theme_web
from stats_core.web import auth as auth_web
from stats_core.web import core as core_web
from stats_core.web import data as data_web
from stats_core.web import display as display_web
from stats_core.web import filters as filters_web
from stats_core.web import screens as screens_web


def application_root():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def asset_root():
    root = application_root()
    return root if getattr(sys, "frozen", False) else root / "app"


def _install_auth_gate(app, runtime):
    @app.before_request
    def settings_lock():
        if not runtime.auth.pin_is_set() or auth_web.session_is_unlocked(runtime.auth):
            return None
        endpoint = request.endpoint or ""
        method = request.method.upper()
        path = request.path
        public = (
            endpoint in runtime.public_endpoints
            or endpoint == "static"
            or (method == "GET" and path.startswith("/static/"))
            or (method == "GET" and path.startswith("/api/screen-theme-assets/"))
        )
        if public:
            return None
        if path.startswith("/api/"):
            return jsonify({"ok": False, "locked": True, "error": "Settings are locked. Enter your PIN."}), 401
        return render_template("settings.html")


def create_app(platform_name="windows", start_background=True):
    if platform_name != "windows":
        raise ValueError("Only the Windows reference platform is active.")

    root = asset_root()
    data_root = prepare_data_dir()
    app = Flask("stats", template_folder=str(root / "templates"), static_folder=str(root / "static"))
    app.config["JSON_SORT_KEYS"] = False

    Repositories.initialize()
    repos = Repositories(static_root=root / "static", data_root=data_root)
    settings = SettingsService(repos.settings, repos.meta)
    auth = AuthService(repos.settings, repos.meta)
    app.secret_key = auth.app_secret_key()

    version = VersionService(application_root())
    platform = WindowsPlatform(repos, data_root, version)

    adapters = {"tableau": TableauAdapter()}
    reports = ReportService(repos, adapters)
    source = SourceService(repos, reports, adapters)
    source.prepare()
    reports.prepare()

    filters = FilterService(repos, reports)
    screens = ScreenService(repos, reports, filters)
    display = DisplayService(repos, screens)
    display.prepare()

    theme = ThemeService(repos)
    theme.prepare()

    public_endpoints = {
        "core.display",
        "core.health",
        "core.api_system_version",
        "core.api_state",
        "auth.api_auth_status",
        "auth.api_auth_unlock",
        "display_state.render",
        "themes.screen_theme_asset",
    }
    runtime = Runtime(
        repos=repos,
        settings=settings,
        auth=auth,
        source=source,
        reports=reports,
        filters=filters,
        screens=screens,
        display=display,
        theme=theme,
        version=version,
        platform=platform,
        public_endpoints=public_endpoints,
    )
    app.extensions["stats_runtime"] = runtime

    app.register_blueprint(auth_web.blueprint(auth))
    app.register_blueprint(core_web.blueprint(runtime))
    app.register_blueprint(data_web.blueprint(source, reports))
    app.register_blueprint(filters_web.blueprint(filters))
    app.register_blueprint(screens_web.blueprint(screens))
    app.register_blueprint(display_web.blueprint(display, theme))
    app.register_blueprint(theme_web.blueprint(theme))

    platform.register(app, public_endpoints)
    _install_auth_gate(app, runtime)
    if start_background:
        platform.start_remote_qr_refresh()
    return app
