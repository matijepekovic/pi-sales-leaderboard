"""Connection, schema, migration and backup only. Queries belong to repository.py."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_messages (
 id INTEGER PRIMARY KEY, source_key TEXT NOT NULL UNIQUE, scope TEXT NOT NULL,
 uid TEXT NOT NULL, uid_validity TEXT NOT NULL, message_id TEXT NOT NULL,
 subject TEXT NOT NULL, sender TEXT NOT NULL, created REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS message_identity
 ON processed_messages(scope, message_id) WHERE message_id != '';
CREATE TABLE IF NOT EXISTS attachments (
 id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES processed_messages(id),
 ordinal INTEGER NOT NULL, filename TEXT NOT NULL, path TEXT NOT NULL,
 sha256 TEXT NOT NULL, size INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING',
 UNIQUE(message_id, ordinal)
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, attachment_id INTEGER REFERENCES attachments(id),
 group_key TEXT NOT NULL, substatus TEXT NOT NULL DEFAULT '',
 filename TEXT NOT NULL, subject TEXT NOT NULL, sender TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'PROCESSING', failure_kind TEXT NOT NULL DEFAULT '',
 error TEXT NOT NULL DEFAULT '', page_count INTEGER, created REAL NOT NULL, updated REAL NOT NULL,
 UNIQUE(attachment_id, group_key)
);
CREATE TABLE IF NOT EXISTS outputs (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), kind TEXT NOT NULL,
 path TEXT NOT NULL, page_count INTEGER, state TEXT NOT NULL,
 tabloid INTEGER NOT NULL DEFAULT 0, request_id TEXT NOT NULL DEFAULT '',
 retry_at REAL NOT NULL DEFAULT 0, UNIQUE(job_id, kind)
);
CREATE TABLE IF NOT EXISTS print_attempts (
 id TEXT PRIMARY KEY, output_id TEXT NOT NULL REFERENCES outputs(id),
 token TEXT NOT NULL UNIQUE, started REAL NOT NULL, finished REAL,
 state TEXT NOT NULL, request_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS steps (
 id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), at REAL NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commands (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, created REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0
);
PRAGMA user_version=1;
"""


@contextmanager
def connect(path: Path):
    con = sqlite3.connect(path, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    try:
        with con:
            yield con
    finally:
        con.close()


def migrate(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with connect(path) as con:
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("Printer database is newer than this application; refusing downgrade")
        con.execute("PRAGMA journal_mode=WAL")
        if version == 0:
            con.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nCOMMIT;")
    path.chmod(0o600)


def backup(path: Path, destination: Path):
    with connect(path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
    destination.chmod(0o600)
