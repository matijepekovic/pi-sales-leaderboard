"""Printer queue persistence: releases and schedule checkpoints are atomic."""
from __future__ import annotations

import json

from .db import Database

STATE_KEY = 'print_schedule_state'
# A completed/ambiguous job is never eligible for automatic reprinting.
UNFINISHED = "('PREPARING','READY','SUBMITTED','PRINTER ERROR')"


class PrintQueueRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _state(conn):
        row = conn.execute('SELECT value FROM meta WHERE key=?', (STATE_KEY,)).fetchone()
        return json.loads(row['value']) if row else None

    @staticmethod
    def _save(conn, state):
        conn.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                     (STATE_KEY, json.dumps(state)))

    def next_attachment(self):
        return self.db.one('''SELECT a.* FROM attachments a
            WHERE a.state IN ('PENDING','PROCESSING') AND NOT EXISTS (
                SELECT 1 FROM print_queue_cancellations x WHERE x.attachment_id=a.id)
            ORDER BY a.id LIMIT 1''')

    def state(self):
        return self.db.get(STATE_KEY)

    def configure(self, signature: str, next_run: float | None, now: float) -> dict:
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            state = self._state(conn)
            if state and state['signature'] == signature:
                return state
            # A timing change governs work not yet submitted. Never revoke a
            # job with a CUPS attempt: its receipt/recovery must finish safely.
            conn.execute('''DELETE FROM print_queue_releases WHERE NOT EXISTS (
                SELECT 1 FROM jobs j JOIN print_attempts p ON p.job_id=j.id
                WHERE j.attachment_id=print_queue_releases.attachment_id)''')
            state = dict(signature=signature, next_run=next_run, configured_at=now,
                         last_run=state.get('last_run') if state else None)
            self._save(conn, state)
            return state

    @staticmethod
    def _release(conn, cutoff: float, now: float, reason: str) -> int:
        cursor = conn.execute(f'''INSERT OR IGNORE INTO print_queue_releases(attachment_id,released_at,reason)
            SELECT a.id,?,? FROM attachments a WHERE a.created<=? AND a.state!='DOWNLOADING'
            AND NOT EXISTS (SELECT 1 FROM print_queue_cancellations x WHERE x.attachment_id=a.id)
            AND (a.state!='DONE' OR EXISTS (
                SELECT 1 FROM jobs j WHERE j.attachment_id=a.id AND j.status IN {UNFINISHED}))''',
            (now, reason, cutoff))
        return cursor.rowcount

    def release_due(self, signature: str, expected: float, cutoff: float,
                    next_run: float, now: float) -> int:
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            state = self._state(conn)
            if not state or state['signature'] != signature or state['next_run'] != expected:
                return 0
            count = self._release(conn, cutoff, now, 'Weekly schedule')
            state.update(next_run=next_run,
                         last_run=dict(scheduled_for=cutoff, released_at=now, attachments=count))
            self._save(conn, state)
            return count

    def request_manual_release(self, now: float) -> None:
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute("SELECT 1 FROM commands WHERE name='print-queued-now'").fetchone():
                conn.execute("INSERT INTO commands(name,created) VALUES ('print-queued-now',?)", (now,))

    def release_requested(self, now: float) -> int:
        # Removing a command and recording its exact batch share a transaction:
        # a crash cannot lose the request or release tomorrow's new arrivals.
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            commands = list(conn.execute("SELECT * FROM commands WHERE name='print-queued-now' ORDER BY id"))
            count = 0
            for command in commands:
                count += self._release(conn, command['created'], now, 'Print queued now')
                conn.execute('DELETE FROM commands WHERE id=?', (command['id'],))
            return count

    def eligible(self, job: dict, immediate: bool) -> bool:
        if job['status'] == 'CANCELLED' or self.cancelled(job['attachment_id']):
            return False
        if job['attachment_id'] is None:
            return True
        # Preparation runs concurrently with dispatch. READY is intermediate
        # until process_attachment finishes recording every output/step and
        # marks the attachment DONE. Never spool a file still being finalized.
        # Existing CUPS attempts always remain eligible for reconciliation.
        return bool(self.db.one('''SELECT 1 FROM print_attempts WHERE job_id=?
            UNION ALL SELECT 1 FROM attachments a WHERE a.id=? AND a.state='DONE'
            AND (? OR EXISTS (SELECT 1 FROM print_queue_releases r WHERE r.attachment_id=a.id))
            LIMIT 1''', (job['id'], job['attachment_id'], int(immediate))))

    def due_jobs(self, now: float, immediate: bool) -> list[dict]:
        # Filter before LIMIT: waiting jobs cannot starve a released batch or
        # prevent reconciliation of a job already submitted to CUPS.
        return self.db.rows('''SELECT j.* FROM jobs j
            WHERE j.status IN ('READY','SUBMITTED','PRINTER ERROR') AND j.next_attempt<=?
            AND NOT EXISTS (SELECT 1 FROM print_queue_cancellations x WHERE x.attachment_id=j.attachment_id)
            AND (j.attachment_id IS NULL
                OR EXISTS (SELECT 1 FROM print_attempts p WHERE p.job_id=j.id)
                OR (EXISTS (SELECT 1 FROM attachments a WHERE a.id=j.attachment_id AND a.state='DONE')
                    AND (? OR EXISTS (SELECT 1 FROM print_queue_releases r WHERE r.attachment_id=j.attachment_id))))
            ORDER BY j.id LIMIT 20''', (now, int(immediate)))

    def waiting(self) -> dict:
        condition = f'''FROM attachments a
            WHERE NOT EXISTS (SELECT 1 FROM print_queue_cancellations x WHERE x.attachment_id=a.id)
            AND NOT EXISTS (SELECT 1 FROM print_queue_releases r WHERE r.attachment_id=a.id)
            AND NOT EXISTS (SELECT 1 FROM jobs j JOIN print_attempts p ON p.job_id=j.id WHERE j.attachment_id=a.id)
            AND (a.state!='DONE' OR EXISTS (
                SELECT 1 FROM jobs j WHERE j.attachment_id=a.id AND j.status IN {UNFINISHED}))'''
        count = self.db.one('SELECT COUNT(*) AS n ' + condition)['n']
        rows = self.db.rows('''SELECT a.*,m.subject,
            (SELECT MIN(j.id) FROM jobs j WHERE j.attachment_id=a.id) AS job_id
            FROM attachments a JOIN processed_messages m ON m.id=a.message_id
            WHERE a.id IN (SELECT a.id ''' + condition + ') ORDER BY a.id LIMIT 200')
        return dict(count=count, attachments=rows)

    def cancelled(self, attachment_id):
        return attachment_id is not None and bool(self.db.one(
            'SELECT 1 FROM print_queue_cancellations WHERE attachment_id=?', (attachment_id,)))

    @staticmethod
    def _removal_info(conn, attachment_id):
        row = conn.execute("""SELECT a.id,a.filename,a.state,a.created,m.subject,
            (SELECT cancelled_at FROM print_queue_cancellations x WHERE x.attachment_id=a.id) AS cancelled_at,
            EXISTS(SELECT 1 FROM jobs j JOIN print_attempts p ON p.job_id=j.id
                   WHERE j.attachment_id=a.id) AS has_attempts,
            EXISTS(SELECT 1 FROM jobs j WHERE j.attachment_id=a.id
                   AND j.status NOT IN ('PREPARING','READY','PRINTER ERROR','CANCELLED')) AS terminal_job,
            EXISTS(SELECT 1 FROM jobs j WHERE j.attachment_id=a.id
                   AND j.status IN ('PREPARING','READY','PRINTER ERROR')) AS unfinished
            FROM attachments a JOIN processed_messages m ON m.id=a.message_id WHERE a.id=?""",
            (attachment_id,)).fetchone()
        return dict(row) if row else None

    def removal_info(self, attachment_id):
        with self.db.connect() as conn:
            return self._removal_info(conn, attachment_id)

    @staticmethod
    def _finish_cancelled(conn, attachment_id, now):
        conn.execute("UPDATE attachments SET state='CANCELLED' WHERE id=?", (attachment_id,))
        conn.execute("""UPDATE jobs SET status='CANCELLED',completed=coalesce(completed,?),updated=?
            WHERE attachment_id=? AND status IN ('PREPARING','READY','PRINTER ERROR','CANCELLED')""",
            (now, now, attachment_id))

    def cancel_attachment(self, attachment_id, now):
        # This transaction races the reservation below, NOT a network CUPS call.
        # Whoever commits first wins; a successful removal can never be submitted.
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            item = self._removal_info(conn, attachment_id)
            if item is None:
                raise LookupError('This attachment is no longer available.')
            if item['cancelled_at'] is not None:
                return False
            if item['has_attempts'] or item['terminal_job']:
                raise ValueError('Submission has already started or finished. This cannot be removed as a waiting print.')
            if item['state'] == 'DOWNLOADING':
                raise ValueError('The attachment is still downloading. Refresh when the download finishes.')
            if item['state'] not in ('PENDING','PROCESSING') and not item['unfinished']:
                raise ValueError('This attachment has no waiting print to remove.')
            conn.execute('INSERT INTO print_queue_cancellations VALUES (?,?)', (attachment_id, now))
            conn.execute('DELETE FROM print_queue_releases WHERE attachment_id=?', (attachment_id,))
            conn.execute("""INSERT INTO steps(job_id,at,message)
                SELECT id,?,'Removed from print queue by user. No printer submission will be made.'
                FROM jobs WHERE attachment_id=?""", (now, attachment_id))
            conn.execute("""UPDATE jobs SET status='CANCELLED',completed=?,updated=?
                WHERE attachment_id=?""", (now, now, attachment_id))
            # A running conversion may still write temporary output. Keep the
            # attachment nonterminal for retention until preparation finishes.
            if item['state'] != 'PROCESSING':
                self._finish_cancelled(conn, attachment_id, now)
            return True

    def recover_cancellations(self, now):
        # Worker startup only, AFTER acquiring its process lock. No conversion
        # from a previous process can still be using these directories.
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for row in list(conn.execute('SELECT attachment_id FROM print_queue_cancellations')):
                self._finish_cancelled(conn, row['attachment_id'], now)

    def start_preparation(self, attachment_id):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            return bool(conn.execute("""UPDATE attachments SET state='PROCESSING'
                WHERE id=? AND state IN ('PENDING','PROCESSING') AND NOT EXISTS (
                    SELECT 1 FROM print_queue_cancellations x WHERE x.attachment_id=attachments.id)""",
                (attachment_id,)).rowcount)

    def finish_preparation(self, attachment_id, now):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM print_queue_cancellations WHERE attachment_id=?', (attachment_id,)).fetchone():
                self._finish_cancelled(conn, attachment_id, now)
            else:
                conn.execute("UPDATE attachments SET state='DONE' WHERE id=?", (attachment_id,))

    def prepared(self, job_id, path, pages, tabloid, now, *, failure_kind='', error=''):
        guard = """ WHERE id=? AND status!='CANCELLED' AND NOT EXISTS (
            SELECT 1 FROM print_queue_cancellations x WHERE x.attachment_id=jobs.attachment_id)"""
        with self.db.connect() as conn:
            if failure_kind:
                conn.execute("""UPDATE jobs SET printable=?,is_error=1,tabloid=0,failure_kind=?,error=?,
                    status='READY',next_attempt=0,updated=?""" + guard,
                    (str(path), failure_kind, error, now, job_id))
            else:
                conn.execute("""UPDATE jobs SET printable=?,page_count=?,tabloid=?,status='READY',updated=?""" + guard,
                    (str(path), pages, int(tabloid), now, job_id))

    def reserve_attempt(self, job_id, token, now):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            job = conn.execute("""SELECT id FROM jobs WHERE id=?
                AND status IN ('READY','SUBMITTED','PRINTER ERROR') AND NOT EXISTS (
                    SELECT 1 FROM print_queue_cancellations x WHERE x.attachment_id=jobs.attachment_id)""",
                (job_id,)).fetchone()
            if not job:
                return None
            attempt = conn.execute('SELECT * FROM print_attempts WHERE job_id=? ORDER BY id DESC LIMIT 1', (job_id,)).fetchone()
            if not attempt or attempt['state'] in ('FAILED','UNKNOWN'):
                aid = conn.execute('INSERT INTO print_attempts(job_id,token,created,updated) VALUES (?,?,?,?)',
                                   (job_id, token, now, now)).lastrowid
                attempt = conn.execute('SELECT * FROM print_attempts WHERE id=?', (aid,)).fetchone()
            return dict(attempt)
