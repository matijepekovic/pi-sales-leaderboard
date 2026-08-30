from __future__ import annotations

from pathlib import Path

import database

from .applied_assets import AppliedAssetRepository
from .asset_library import AssetLibraryRepository
from .meta import MetaRepository
from .organization import OrganizationRepository
from .products import ProductRepository
from .reps import RepRepository
from .settings import SettingsRepository
from .themes import ThemeRepository


def persistent_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "pi-tableau-leaderboard"


class Repositories:
    def __init__(self, static_root=None, data_root=None):
        data_root = Path(data_root or persistent_data_dir())
        static_root = Path(static_root or Path(__file__).resolve().parents[2] / "static")
        self.meta = MetaRepository()
        self.settings = SettingsRepository()
        self.reps = RepRepository()
        self.organization = OrganizationRepository()
        self.products = ProductRepository()
        self.themes = ThemeRepository(self.settings, self.meta)
        self.applied_assets = AppliedAssetRepository(data_root, static_root)
        self.asset_library = AssetLibraryRepository(data_root, static_root)

    @staticmethod
    def initialize():
        database.init_db()
