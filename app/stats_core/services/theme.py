"""Theme domain adapter.

The existing theme engine remains intact for this restructure, but all theme
registration/extensions now have one explicit owner instead of being installed
through scheduler/QR startup.
"""
from __future__ import annotations

from themes import themes_blueprint, display_theme_state
import applied_theme_assets_v116
import starter_theme_v119
import starter_theme_assets_v119
import theme_asset_apply_v127


class ThemeService:
    def display_state(self, settings=None):
        return display_theme_state(settings)

    def register(self, app):
        app.register_blueprint(themes_blueprint)
        applied_theme_assets_v116.install(app)
        starter_theme_v119.install(app)
        starter_theme_assets_v119.install(app)
        theme_asset_apply_v127.install(app)
