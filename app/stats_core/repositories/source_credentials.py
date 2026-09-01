"""Secret persistence for external source adapters.

Secrets are stored separately from public source definitions. The first Tableau
source remains compatible with the existing `tableau_pat_secret` setting while
additional sources get isolated secret records.
"""
from __future__ import annotations

from stats_core.repositories.data_catalog import PRIMARY_SOURCE_ID
from stats_core.storage import sqlite

_PREFIX = "source_secret:"


class SourceCredentialRepository:
    def __init__(self, settings_repo):
        self.settings_repo = settings_repo

    @staticmethod
    def _key(source_id):
        source_id = str(source_id or "").strip()
        if not source_id:
            raise ValueError("Source id is required.")
        return _PREFIX + source_id

    def get(self, source_id):
        source_id = str(source_id or "").strip()
        if source_id == PRIMARY_SOURCE_ID:
            return str(self.settings_repo.get().get("tableau_pat_secret") or "")
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (self._key(source_id),)
            ).fetchone()
        return str(row["value"] if row else "")

    def set(self, source_id, secret):
        source_id = str(source_id or "").strip()
        secret = str(secret or "")
        if source_id == PRIMARY_SOURCE_ID:
            settings = self.settings_repo.get()
            settings["tableau_pat_secret"] = secret
            self.settings_repo.save(settings)
            return
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self._key(source_id), secret),
            )

    def delete(self, source_id):
        source_id = str(source_id or "").strip()
        if source_id == PRIMARY_SOURCE_ID:
            self.set(source_id, "")
            return
        with sqlite.connect() as con:
            con.execute("DELETE FROM settings WHERE key=?", (self._key(source_id),))
