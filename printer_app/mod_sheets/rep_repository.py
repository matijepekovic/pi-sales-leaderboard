"""Persist the last successfully refreshed MOD rep list, independently of reports."""
from __future__ import annotations


REP_NAMES_KEY = 'mod_sheet_rep_names'


class ModSheetRepRepository:
    def __init__(self, db):
        self.db = db

    def names(self) -> tuple[str, ...] | None:
        value = self.db.get(REP_NAMES_KEY)
        # None means never loaded. An empty list is a successful saved result.
        if not isinstance(value, list) or any(not isinstance(name, str) for name in value):
            return None
        return tuple(value)

    def replace(self, names: tuple[str, ...]) -> None:
        # One atomic replacement, never an append or a per-filter cache.
        self.db.set(REP_NAMES_KEY, list(names))
