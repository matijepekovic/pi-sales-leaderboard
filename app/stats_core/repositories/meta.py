from __future__ import annotations

from stats_core.storage import sqlite as database


class MetaRepository:
    def get(self, key, default=""):
        return database.get_meta(key, default)

    def set(self, key, value):
        return database.set_meta(key, value)

    def bump(self, key):
        try:
            value = int(self.get(key, "0") or 0) + 1
        except Exception:
            value = 1
        self.set(key, value)
        return value
