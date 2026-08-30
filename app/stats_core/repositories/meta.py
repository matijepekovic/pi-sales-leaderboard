from __future__ import annotations

from stats_core.storage import sqlite


class MetaRepository:
    def get(self, key, default=""):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM meta WHERE key=?",
                (key,),
            ).fetchone()
        return row["value"] if row else default

    def set(self, key, value):
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def bump(self, key):
        try:
            value = int(self.get(key, "0") or 0) + 1
        except Exception:
            value = 1
        self.set(key, value)
        return value
