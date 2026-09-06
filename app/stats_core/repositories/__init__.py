from __future__ import annotations

from pathlib import Path

from stats_core.paths import persistent_data_dir
from stats_core.storage import sqlite as database

from .applied_assets import AppliedAssetRepository
from .asset_library import AssetLibraryRepository
from .data_catalog import DataCatalogRepository
from .display import DisplayRepository
from .filters import FilterRepository
from .fields import FieldRepository
from .groups import GroupRepository
from .meta import MetaRepository
from .report_data import ReportDataRepository
from .screens import ScreenRepository
from .settings import SettingsRepository
from .source_credentials import SourceCredentialRepository
from .table_presets import TablePresetRepository
from .themes import ThemeRepository
from .widgets import WidgetRepository


class Repositories:
    """Repository composition for current Stats product domains."""

    def __init__(self, static_root=None, data_root=None):
        data_root = Path(data_root or persistent_data_dir())
        static_root = Path(static_root or Path(__file__).resolve().parents[2] / "static")

        database.configure(data_root)
        database.init_db()

        self.meta = MetaRepository()
        self.settings = SettingsRepository()
        self.data_catalog = DataCatalogRepository()
        self.source_credentials = SourceCredentialRepository()
        self.report_data = ReportDataRepository(data_root)
        self.filters = FilterRepository()
        self.fields = FieldRepository()
        self.groups = GroupRepository()
        self.screens = ScreenRepository()
        self.table_presets = TablePresetRepository()
        self.widgets = WidgetRepository()
        self.display = DisplayRepository()
        self.themes = ThemeRepository(self.settings, self.meta)
        self.applied_assets = AppliedAssetRepository(data_root, static_root)
        self.asset_library = AssetLibraryRepository(data_root, static_root)

    @staticmethod
    def initialize(data_root=None):
        database.configure(data_root)
        database.init_db()
