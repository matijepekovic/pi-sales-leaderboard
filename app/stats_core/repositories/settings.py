from __future__ import annotations

import database


class SettingsRepository:
    def get(self):
        return database.get_settings()

    def save(self, settings):
        return database.save_settings(settings)
