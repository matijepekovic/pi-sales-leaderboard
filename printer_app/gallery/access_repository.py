"""SQLite persistence for gallery access grants and temporary invitations."""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager


SCHEMA = """
CREATE TABLE IF NOT EXISTS access_invites (
 token_hash TEXT PRIMARY KEY,
 role TEXT NOT NULL,
 created REAL NOT NULL,
 expires REAL NOT NULL,
 one_time INTEGER NOT NULL,
 used REAL
);
CREATE INDEX IF NOT EXISTS gallery_access_invites_expiry ON access_invites(expires);
CREATE TABLE IF NOT EXISTS access_credentials (
 token_hash TEXT PRIMARY KEY,
 subject TEXT NOT NULL,
 role TEXT NOT NULL,
 created REAL NOT NULL,
 expires REAL,
 revoked REAL,
 last_seen REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS gallery_access_subject ON access_credentials(subject);
CREATE INDEX IF NOT EXISTS gallery_access_expiry ON access_credentials(expires);
"""


class GalleryAccessRepository:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript(SCHEMA)

    def create_invite(self, token_hash, role, expires, one_time):
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO access_invites(token_hash,role,created,expires,one_time) VALUES(?,?,?,?,?)",
                (token_hash, role, now, expires, 1 if one_time else 0),
            )
            self._prune(conn, now)

    def redeem_invite(self, token_hash, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                "SELECT token_hash,role,expires,one_time,used FROM access_invites WHERE token_hash=?",
                (token_hash,),
            ).fetchone()
            if not row or row['expires'] <= now or (row['one_time'] and row['used'] is not None):
                return None
            if row['one_time']:
                conn.execute("UPDATE access_invites SET used=? WHERE token_hash=?", (now, token_hash))
            self._prune(conn, now)
            return dict(row)

    def create_credential(self, token_hash, subject, role, expires=None, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO access_credentials
                   (token_hash,subject,role,created,expires,revoked,last_seen)
                   VALUES(?,?,?,?,?,NULL,?)""",
                (token_hash, subject, role, now, expires, now),
            )
            self._prune(conn, now)

    def credential(self, token_hash, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            row = conn.execute(
                """SELECT subject,role,expires,last_seen FROM access_credentials
                   WHERE token_hash=? AND revoked IS NULL
                     AND (expires IS NULL OR expires>?)""",
                (token_hash, now),
            ).fetchone()
            if not row:
                self._prune(conn, now)
                return None
            if now - row['last_seen'] >= 60:
                conn.execute("UPDATE access_credentials SET last_seen=? WHERE token_hash=?", (now, token_hash))
            return dict(row)

    def _prune(self, conn, now):
        conn.execute("DELETE FROM access_invites WHERE expires<? OR (one_time=1 AND used IS NOT NULL)", (now,))
        conn.execute(
            "DELETE FROM access_credentials WHERE expires IS NOT NULL AND expires<?",
            (now - 7 * 86400,),
        )
