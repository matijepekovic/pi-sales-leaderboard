"""Stats application composition root.

This is the only place where feature modules are assembled. Services depend on
explicit repositories/services; scheduler, QR, themes and Windows no longer
install each other through import-time side effects.
"""
from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session

import database
import tableau_scheduler
from stats_core.platform.windows import WindowsPlatform
from stats_core.repositories import Repositories, persistent_data_dir
from stats_core.runtime import Runtime
from stats_core.services.auth import AuthService
from stats_core.services.controls import ControlsService
from stats_core.services.leaderboard import LeaderboardService
from stats_core.services.organization import OrganizationService
from stats_core.services.product import ProductService
from stats_core.services.rep_refresh import RepRefreshService
from stats_core.services.scheduler import SchedulerService
from stats_core.services.settings import SettingsService
from stats_core.services.snapshot import DataSnapshotService
from stats_core.services.source import SourceService
from stats_core.services.tableau import TableauService
from stats_core.services.temporary_date import TemporaryDateService
from stats_core.services.theme import ThemeService
from stats_core.services.tv import TvService
from stats_core.services.version import VersionService
from stats_core.web import auth as auth_web
from stats_core.web import controls as controls_web
from stats_core.web import core as core_web
from stats_core.web import organization as organization_web
from stats_core.web import product as product_web
from stats_core.web import source as source_web
from stats_core.web import tv as tv_web


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
        if not runtime.auth.pin_is_set() or bool(session.get("settings_unlocked")):
            return None
        endpoint = request.endpoint or ""
        method = request.method.upper()
        path = request.path
        public = (
            endpoint in runtime.public_endpoints or endpoint == "static"
            or (method == "GET" and path.startswith("/static/"))
            or (method == "GET" and path.startswith("/api/theme-assets/"))
        )
        if public:
            return None
        if path.startswith("/api/"):
            return jsonify({"ok": False, "locked": True, "error": "Settings are locked. Enter your PIN."}), 401
        return render_template("settings.html")


def create_app(platform_name="windows", start_background=True):
    if platform_name != "windows":
        raise ValueError("Only the Windows reference platform is active during restructuring.")

    root = asset_root()
    app = Flask("stats", template_folder=str(root / "templates"), static_folder=str(root / "static"))
    app.config["JSON_SORT_KEYS"] = False

    database.init_db()
    repos = Repositories()
    settings = SettingsService(repos.settings, repos.meta)
    auth = AuthService(repos.settings, repos.meta)
    app.secret_key = auth.app_secret_key()

    version = VersionService(application_root())
    platform = WindowsPlatform(repos, persistent_data_dir(), version)
    organization = OrganizationService(repos, persistent_data_dir() / "team-logos")
    tableau = TableauService()
    rep_refresh = RepRefreshService(repos, tableau)
    rep_refresh.prepare()
    temporary_date = TemporaryDateService(repos, rep_refresh)
    products = ProductService(repos, temporary_date)
    snapshots = DataSnapshotService(repos, temporary_date)
    leaderboard = LeaderboardService(repos, organization, snapshots, products)
    source = SourceService(repos, rep_refresh, tableau)
    controls = ControlsService(repos, organization)
    scheduler = SchedulerService(repos, rep_refresh, products)
    theme = ThemeService()
    tv = TvService(repos, platform)

    public_endpoints = {
        "core.display", "core.health", "core.api_system_version",
        "core.api_config", "core.api_leaderboard",
        "auth.api_auth_status", "auth.api_auth_unlock",
        "organization.team_logo", "product.preview", "product.product_close",
        "tv.report_geometry", "themes.theme_asset",
    }
    runtime = Runtime(
        repos=repos, settings=settings, auth=auth, organization=organization,
        tableau=tableau, rep_refresh=rep_refresh, temporary_date=temporary_date,
        products=products, snapshots=snapshots, leaderboard=leaderboard,
        source=source, controls=controls, scheduler=scheduler, theme=theme,
        version=version, tv=tv, platform=platform, public_endpoints=public_endpoints,
    )
    app.extensions["stats_runtime"] = runtime

    app.register_blueprint(auth_web.blueprint(auth))
    app.register_blueprint(core_web.blueprint(runtime))
    app.register_blueprint(organization_web.blueprint(organization))
    app.register_blueprint(source_web.blueprint(source))
    app.register_blueprint(product_web.blueprint(products))
    app.register_blueprint(controls_web.blueprint(controls, temporary_date))
    app.register_blueprint(tv_web.blueprint(tv))

    theme.register(app)
    tableau_scheduler.configure(scheduler, products, autostart=start_background)
    platform.register(app, public_endpoints)
    _install_auth_gate(app, runtime)

    if start_background:
        scheduler.start()
        platform.start_remote_qr_refresh()
    return app
