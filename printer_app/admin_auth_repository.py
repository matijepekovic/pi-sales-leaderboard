"""Printer-admin authentication persistence.

SQL lives here; password verification/session rules live in admin_auth.py.
"""
import time


class AdminAuthRepository:
    def __init__(self, db):
        self.db = db

    def state(self):
        return self.db.one(
            "SELECT password_hash,must_change,revision,updated FROM admin_auth WHERE singleton=1"
        )

    def create(self, password_hash, *, must_change=True):
        now = time.time()
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT 1 FROM admin_auth WHERE singleton=1").fetchone()
            if row:
                return False
            conn.execute(
                """INSERT INTO admin_auth(singleton,password_hash,must_change,revision,updated)
                   VALUES(1,?,?,1,?)""",
                (password_hash, 1 if must_change else 0, now),
            )
            return True

    def replace_password(self, password_hash):
        now = time.time()
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                "SELECT revision FROM admin_auth WHERE singleton=1"
            ).fetchone()
            if not row:
                raise LookupError('Printer admin password is not initialized.')
            revision = int(row['revision']) + 1
            conn.execute(
                """UPDATE admin_auth
                   SET password_hash=?,must_change=0,revision=?,updated=?
                   WHERE singleton=1""",
                (password_hash, revision, now),
            )
            return revision

    def blocked_until(self, address, now=None):
        now = time.time() if now is None else now
        row = self.db.one(
            "SELECT attempts,reset_at FROM login_limits WHERE address=?", (address,)
        )
        if not row or row['reset_at'] <= now or row['attempts'] < 5:
            return None
        return float(row['reset_at'])

    def record_failure(self, address, now=None):
        now = time.time() if now is None else now
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                "SELECT attempts,reset_at FROM login_limits WHERE address=?", (address,)
            ).fetchone()
            if not row or row['reset_at'] <= now:
                attempts, reset_at = 1, now + 15 * 60
                conn.execute(
                    """INSERT INTO login_limits(address,attempts,reset_at)
                       VALUES(?,?,?)
                       ON CONFLICT(address) DO UPDATE
                       SET attempts=excluded.attempts,reset_at=excluded.reset_at""",
                    (address, attempts, reset_at),
                )
            else:
                attempts, reset_at = int(row['attempts']) + 1, float(row['reset_at'])
                conn.execute(
                    "UPDATE login_limits SET attempts=? WHERE address=?",
                    (attempts, address),
                )
            return attempts, reset_at

    def clear_failures(self, address):
        self.db.execute("DELETE FROM login_limits WHERE address=?", (address,))
