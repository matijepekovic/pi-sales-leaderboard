"""Persistence for permanent daily MOD-sheet settings and run state."""
from __future__ import annotations

from .policy import ModSheetAutomationSettings


SETTINGS_KEY = 'daily_mod_sheet_settings'
STATE_KEY = 'daily_mod_sheet_state'
TEST_STATE_KEY = 'daily_mod_sheet_test_state'


class ModSheetAutomationRepository:
    def __init__(self, db):
        self.db = db

    def settings(self) -> ModSheetAutomationSettings | None:
        value = self.db.get(SETTINGS_KEY)
        if not isinstance(value, dict):
            return None
        try:
            return ModSheetAutomationSettings.from_dict(value)
        except (TypeError, ValueError):
            return None

    def save_settings(self, settings: ModSheetAutomationSettings) -> None:
        self.db.set(SETTINGS_KEY, settings.as_dict())

    def state(self) -> dict:
        value = self.db.get(STATE_KEY, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_state(self, state: dict) -> dict:
        value = dict(state)
        self.db.set(STATE_KEY, value)
        return value


    def test_state(self) -> dict:
        value = self.db.get(TEST_STATE_KEY, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_test_state(self, state: dict) -> dict:
        value = dict(state)
        self.db.set(TEST_STATE_KEY, value)
        return value
