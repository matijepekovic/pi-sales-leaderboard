"""Secret persistence for normalized external source records."""
from __future__ import annotations

from stats_core.storage import sqlite

_PREFIX = "source_secret:"


class SourceCredentialRepository:
    @staticmethod
    def _key(source_id):
        source_id = str(source_id or "").strip()
        if not source_id:
            raise ValueError("Source id is required.")
        return _PREFIX + source_id

    def get(self, source_id):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key=?", (self._key(source_id),)
            ).fetchone()
        return str(row["value"] if row else "")

    def set(self, source_id, secret):
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (self._key(source_id), str(secret or "")),
            )

    def delete(self, source_id):
        with sqlite.connect() as con:
            con.execute("DELETE FROM settings WHERE key=?", (self._key(source_id),))
