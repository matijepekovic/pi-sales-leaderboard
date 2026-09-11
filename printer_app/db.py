"""Private, durable SQLite inbox, job queue and print outbox (schema version 1)."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS processed_messages (
 id INTEGER PRIMARY KEY, identity TEXT NOT NULL UNIQUE, account TEXT NOT NULL,
 mailbox TEXT NOT NULL, uidvalidity TEXT NOT NULL, uid TEXT NOT NULL,
 message_id TEXT NOT NULL, subject TEXT NOT NULL, sender TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'FETCHING', created REAL NOT NULL,
 UNIQUE(account,mailbox,uidvalidity,uid));
CREATE TABLE IF NOT EXISTS retained_message_receipts (
 identity TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS mail_cleanup_outbox (
 account TEXT NOT NULL, mailbox TEXT NOT NULL, message_key TEXT NOT NULL,
 received_at REAL NOT NULL, local_identity TEXT NOT NULL,
 PRIMARY KEY(account,mailbox,message_key)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS attachments (
 id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES processed_messages(id),
 part TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL DEFAULT '',
 path TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'PENDING', created REAL NOT NULL,
 UNIQUE(message_id,part));
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, attachment_id INTEGER REFERENCES attachments(id),
 group_key TEXT NOT NULL, substatus TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'READY', failure_kind TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '', page_count INTEGER,
 printable TEXT NOT NULL DEFAULT '', is_error INTEGER NOT NULL DEFAULT 0,
 tabloid INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
 created REAL NOT NULL, updated REAL NOT NULL, completed REAL,
 UNIQUE(attachment_id,group_key));
CREATE TABLE IF NOT EXISTS print_queue_releases (
 attachment_id INTEGER PRIMARY KEY REFERENCES attachments(id),
 released_at REAL NOT NULL, reason TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS attachments_received ON attachments(created);
CREATE TABLE IF NOT EXISTS outputs (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
 role TEXT NOT NULL, path TEXT NOT NULL, UNIQUE(job_id,path));
CREATE TABLE IF NOT EXISTS print_attempts (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
 token TEXT NOT NULL UNIQUE, state TEXT NOT NULL DEFAULT 'HOLDING',
 request_id TEXT NOT NULL DEFAULT '', cups_id INTEGER,
 command TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '',
 created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS steps (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
 at REAL NOT NULL, message TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_limits (
 address TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS jobs_due ON jobs(status,next_attempt);
CREATE INDEX IF NOT EXISTS attempts_job ON print_attempts(job_id,id);
'''


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            version = conn.execute('PRAGMA user_version').fetchone()[0]
            if version > 1:
                raise RuntimeError('Database is newer than this printer-app release')
            conn.executescript(SCHEMA)
            conn.execute('PRAGMA user_version=1')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA synchronous=FULL')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def execute(self, sql: str, args=()) -> int:
        with self.connect() as conn:
            return conn.execute(sql, args).lastrowid

    def rows(self, sql: str, args=()) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, args)]

    def one(self, sql: str, args=()):
        rows = self.rows(sql, args)
        return rows[0] if rows else None

    def get(self, key: str, default=None):
        row = self.one('SELECT value FROM meta WHERE key=?', (key,))
        return json.loads(row['value']) if row else default

    def set(self, key: str, value) -> None:
        self.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (key, json.dumps(value)))

    def step(self, job_id: int, message: str) -> None:
        self.execute('INSERT INTO steps(job_id,at,message) VALUES (?,?,?)', (job_id, time.time(), message))

    def output(self, job_id: int, role: str, path: Path) -> None:
        self.execute('INSERT OR IGNORE INTO outputs(job_id,role,path) VALUES (?,?,?)',
                     (job_id, role, str(path)))

    def job(self, job_id: int):
        return self.one('''SELECT j.*,a.filename,a.path AS source_path,m.subject,m.sender
          FROM jobs j LEFT JOIN attachments a ON a.id=j.attachment_id
          LEFT JOIN processed_messages m ON m.id=a.message_id WHERE j.id=?''', (job_id,))

    def create_job(self, attachment_id: int | None, key: str, options: dict) -> int:
        now = time.time()
        with self.connect() as conn:
            existing = conn.execute('SELECT id FROM jobs WHERE attachment_id=? AND group_key=?',
                                    (attachment_id, key)).fetchone()
            if existing:
                return existing['id']
            job_id = conn.execute("""INSERT INTO jobs(attachment_id,group_key,status,created,updated)
                VALUES (?,?,'PREPARING',?,?)""", (attachment_id, key, now, now)).lastrowid
            conn.execute('INSERT INTO meta(key,value) VALUES (?,?)',
                         ('job_print_settings:' + str(job_id), json.dumps(options)))
            return job_id

    def job_print_settings(self, job_id: int) -> dict | None:
        return self.get('job_print_settings:' + str(job_id))

    def recent(self):
        return self.rows('''SELECT j.*,a.filename,m.subject,m.sender FROM jobs j
          LEFT JOIN attachments a ON a.id=j.attachment_id
          LEFT JOIN processed_messages m ON m.id=a.message_id ORDER BY j.id DESC LIMIT 200''')
