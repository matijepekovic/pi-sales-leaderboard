"""Stats application composition root.

This is the only place where product domains, platform adapters and HTTP
blueprints are assembled. Feature modules do not install or monkey-patch one
another at runtime.
"""
from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask

from stats_core.paths import prepare_data_dir
from stats_core.platform import create_platform
from stats_core.repositories import Repositories
from stats_core.runtime import Runtime
from stats_core.screens.registry import ScreenRegistry
from stats_core.services.auth import AuthService
from stats_core.services.controls import ControlsService
from stats_core.services.leaderboard import LeaderboardService
from stats_core.services.organization import OrganizationService
from stats_core.services.preview import PreviewService
from stats_core.services.product import ProductService
from stats_core.services.product_refresh import ProductRefreshService
from stats_core.services.pull_policy import RepPullPolicy
from stats_core.services.rep_refresh import RepRefreshService
from stats_core.services.scheduler import SchedulerService
from stats_core.services.settings import SettingsService
from stats_core.services.snapshot import DataSnapshotService
from stats_core.services.source import SourceService
from stats_core.services.tableau import TableauService
from stats_core.services.temporary_date import TemporaryDateService
from stats_core.services.tv import TvService
from stats_core.services.version import VersionService
from stats_core.theme import ThemeService
from stats_core.theme import web as theme_web
from stats_core.web import auth as auth_web
from stats_core.web import controls as controls_web
from stats_core.web import core as core_web
from stats_core.web import organization as organization_web
from stats_core.web import product as product_web
from stats_core.web import source as source_web
from stats_core.web import system as system_web
from stats_core.web import tv as tv_web


def application_root():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def asset_root():
    root = application_root()
    return root if getattr(sys, "frozen", False) else root / "app"


def create_app(platform_name="windows", start_background=True):
    root = asset_root()
    data_root = prepare_data_dir()
    app = Flask(
        "stats",
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
    )
    app.config["JSON_SORT_KEYS"] = False

    Repositories.initialize()
    repos = Repositories(static_root=root / "static", data_root=data_root)
    auth = AuthService(repos.settings, repos.meta)
    settings = SettingsService(repos.settings, repos.meta, auth)
    app.secret_key = auth.app_secret_key()

    version = VersionService(application_root())
    platform = create_platform(platform_name, repos, data_root, version)
    organization = OrganizationService(repos, data_root / "team-logos")
    tableau = TableauService()
    pull_policy = RepPullPolicy(repos, tableau)
    rep_refresh = RepRefreshService(repos, tableau, pull_policy)
    rep_refresh.prepare()

    temporary_date = TemporaryDateService(repos, rep_refresh)
    product_refresh = ProductRefreshService(repos, temporary_date)
    products = ProductService(repos, temporary_date, product_refresh)
    preview = PreviewService()
    snapshots = DataSnapshotService(repos, preview, temporary_date)
    leaderboard = LeaderboardService(repos, organization, snapshots)
    screens = ScreenRegistry(leaderboard, products, organization)
    source = SourceService(repos, rep_refresh, preview, tableau)
    controls = ControlsService(repos, screens)
    scheduler = SchedulerService(repos, rep_refresh, products)
    theme = ThemeService(repos)
    theme.prepare()
    tv = TvService(repos, platform)

    public_endpoints = set(auth_web.CORE_PUBLIC_ENDPOINTS) | set(platform.public_endpoints)
    runtime = Runtime(
        repos=repos,
        settings=settings,
        auth=auth,
        organization=organization,
        tableau=tableau,
        pull_policy=pull_policy,
        rep_refresh=rep_refresh,
        temporary_date=temporary_date,
        product_refresh=product_refresh,
        products=products,
        preview=preview,
        snapshots=snapshots,
        leaderboard=leaderboard,
        screens=screens,
        source=source,
        controls=controls,
        scheduler=scheduler,
        theme=theme,
        version=version,
        tv=tv,
        platform=platform,
        public_endpoints=public_endpoints,
    )
    app.extensions["stats_runtime"] = runtime

    app.register_blueprint(auth_web.blueprint(auth))
    app.register_blueprint(core_web.blueprint(runtime))
    app.register_blueprint(organization_web.blueprint(organization))
    app.register_blueprint(source_web.blueprint(source))
    app.register_blueprint(product_web.blueprint(products))
    app.register_blueprint(controls_web.blueprint(controls, temporary_date))
    app.register_blueprint(tv_web.blueprint(tv))
    app.register_blueprint(theme_web.blueprint(theme))
    app.register_blueprint(system_web.blueprint(platform))

    platform.register(app, public_endpoints)
    auth_web.install_gate(app, auth, public_endpoints)

    if start_background:
        scheduler.start()
        platform.start_remote_qr_refresh()
    return app
