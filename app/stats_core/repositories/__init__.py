from __future__ import annotations

from pathlib import Path

from stats_core.paths import persistent_data_dir
from stats_core.storage import sqlite as database

from .applied_assets import AppliedAssetRepository
from .asset_library import AssetLibraryRepository
from .data_catalog import DataCatalogRepository
from .display import DisplayRepository
from .meta import MetaRepository
from .organization import OrganizationRepository
from .products import ProductRepository
from .report_data import ReportDataRepository
from .reps import RepRepository
from .screens import ScreenRepository
from .settings import SettingsRepository
from .source_credentials import SourceCredentialRepository
from .themes import ThemeRepository


class Repositories:
    def __init__(self, static_root=None, data_root=None):
        data_root = Path(data_root or persistent_data_dir())
        static_root = Path(static_root or Path(__file__).resolve().parents[2] / "static")

        self.meta = MetaRepository()
        self.settings = SettingsRepository()
        self.data_catalog = DataCatalogRepository()
        self.source_credentials = SourceCredentialRepository(self.settings)
        self.report_data = ReportDataRepository(data_root)
        self.screens = ScreenRepository()
        self.display = DisplayRepository()
        self.organization = OrganizationRepository(self.meta)
        self.reps = RepRepository(self.meta, self.organization)
        self.products = ProductRepository()
        self.themes = ThemeRepository(self.settings, self.meta)
        self.applied_assets = AppliedAssetRepository(data_root, static_root)
        self.asset_library = AssetLibraryRepository(data_root, static_root)

    @staticmethod
    def initialize():
        database.init_db()
