from __future__ import annotations

from stats_core.storage import sqlite as database


class SettingsRepository:
    def get(self):
        return database.get_settings()

    def save(self, settings):
        return database.save_settings(settings)
