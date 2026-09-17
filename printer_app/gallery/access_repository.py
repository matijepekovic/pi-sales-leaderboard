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
 used REAL,
 share_id TEXT,
 issuer_subject TEXT NOT NULL DEFAULT '',
 label TEXT NOT NULL DEFAULT '',
 revoked REAL
);
CREATE INDEX IF NOT EXISTS gallery_access_invites_expiry ON access_invites(expires);
CREATE TABLE IF NOT EXISTS access_credentials (
 token_hash TEXT PRIMARY KEY,
 subject TEXT NOT NULL,
 role TEXT NOT NULL,
 created REAL NOT NULL,
 expires REAL,
 revoked REAL,
 last_seen REAL NOT NULL,
 invite_hash TEXT
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
            invite_columns = {row['name'] for row in conn.execute('PRAGMA table_info(access_invites)')}
            for name, definition in (
                ('share_id', 'TEXT'),
                ('issuer_subject', "TEXT NOT NULL DEFAULT ''"),
                ('label', "TEXT NOT NULL DEFAULT ''"),
                ('revoked', 'REAL'),
            ):
                if name not in invite_columns:
                    conn.execute(f'ALTER TABLE access_invites ADD COLUMN {name} {definition}')
            credential_columns = {row['name'] for row in conn.execute('PRAGMA table_info(access_credentials)')}
            if 'invite_hash' not in credential_columns:
                conn.execute('ALTER TABLE access_credentials ADD COLUMN invite_hash TEXT')
            conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS gallery_access_share_id
                ON access_invites(share_id) WHERE share_id IS NOT NULL""")

    def create_invite(self, token_hash, role, expires, one_time, *,
                      share_id=None, issuer_subject='', label=''):
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO access_invites
                   (token_hash,role,created,expires,one_time,share_id,issuer_subject,label)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (token_hash, role, now, expires, 1 if one_time else 0,
                 share_id, issuer_subject, label),
            )
            self._prune(conn, now)

    def redeem_invite(self, token_hash, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                """SELECT token_hash,role,expires,one_time,used,share_id,issuer_subject,label,revoked
                   FROM access_invites WHERE token_hash=?""",
                (token_hash,),
            ).fetchone()
            if (not row or row['expires'] <= now or row['revoked'] is not None
                    or (row['one_time'] and row['used'] is not None)):
                return None
            if row['one_time']:
                conn.execute("UPDATE access_invites SET used=? WHERE token_hash=?", (now, token_hash))
            self._prune(conn, now)
            return dict(row)

    def create_credential(self, token_hash, subject, role, expires=None, *,
                          invite_hash=None, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO access_credentials
                   (token_hash,subject,role,created,expires,revoked,last_seen,invite_hash)
                   VALUES(?,?,?,?,?,NULL,?,?)""",
                (token_hash, subject, role, now, expires, now, invite_hash),
            )
            self._prune(conn, now)

    def credential(self, token_hash, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            row = conn.execute(
                """SELECT c.subject,c.role,c.expires,c.last_seen
                   FROM access_credentials c
                   LEFT JOIN access_invites i ON i.token_hash=c.invite_hash
                   WHERE c.token_hash=? AND c.revoked IS NULL
                     AND (c.expires IS NULL OR c.expires>?)
                     AND (c.invite_hash IS NULL OR
                          (i.token_hash IS NOT NULL AND i.revoked IS NULL AND i.expires>?))""",
                (token_hash, now, now),
            ).fetchone()
            if not row:
                self._prune(conn, now)
                return None
            if now - row['last_seen'] >= 60:
                conn.execute("UPDATE access_credentials SET last_seen=? WHERE token_hash=?", (now, token_hash))
            return dict(row)

    def active_shares(self, issuer_subject, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(
                """SELECT share_id,label,created,expires,used
                   FROM access_invites
                   WHERE role='guest' AND issuer_subject=? AND share_id IS NOT NULL
                     AND revoked IS NULL AND expires>?
                   ORDER BY created DESC,share_id""",
                (issuer_subject, now),
            )]
            self._prune(conn, now)
            return rows

    def revoke_share(self, issuer_subject, share_id, now=None):
        now = time.time() if now is None else now
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                """SELECT token_hash FROM access_invites
                   WHERE share_id=? AND issuer_subject=? AND role='guest'
                     AND revoked IS NULL AND expires>?""",
                (share_id, issuer_subject, now),
            ).fetchone()
            if not row:
                raise LookupError('This access session is no longer active.')
            conn.execute(
                "UPDATE access_invites SET revoked=? WHERE token_hash=?",
                (now, row['token_hash']),
            )
            conn.execute(
                """UPDATE access_credentials SET revoked=?
                   WHERE invite_hash=? AND revoked IS NULL""",
                (now, row['token_hash']),
            )

    def _prune(self, conn, now):
        # Keep recent used/revoked guest grants so an already-redeemed credential
        # remains tied to its grant until both are safely beyond their lifetime.
        conn.execute("DELETE FROM access_invites WHERE expires<?", (now - 7 * 86400,))
        conn.execute(
            "DELETE FROM access_credentials WHERE expires IS NOT NULL AND expires<?",
            (now - 7 * 86400,),
        )
