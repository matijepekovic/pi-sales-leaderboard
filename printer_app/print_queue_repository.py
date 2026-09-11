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
        return self.db.one("SELECT * FROM attachments WHERE state IN ('PENDING','PROCESSING') ORDER BY id LIMIT 1")

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
        if job['attachment_id'] is None or immediate:
            return True
        return bool(self.db.one('''SELECT 1 FROM print_queue_releases WHERE attachment_id=?
            UNION ALL SELECT 1 FROM print_attempts WHERE job_id=? LIMIT 1''',
            (job['attachment_id'], job['id'])))

    def due_jobs(self, now: float, immediate: bool) -> list[dict]:
        # Filter before LIMIT: waiting jobs cannot starve a released batch or
        # prevent reconciliation of a job already submitted to CUPS.
        return self.db.rows('''SELECT j.* FROM jobs j
            WHERE j.status IN ('READY','SUBMITTED','PRINTER ERROR') AND j.next_attempt<=?
            AND (? OR j.attachment_id IS NULL
                OR EXISTS (SELECT 1 FROM print_queue_releases r WHERE r.attachment_id=j.attachment_id)
                OR EXISTS (SELECT 1 FROM print_attempts p WHERE p.job_id=j.id))
            ORDER BY j.id LIMIT 20''', (now, int(immediate)))

    def waiting(self) -> dict:
        condition = f'''FROM attachments a
            WHERE NOT EXISTS (SELECT 1 FROM print_queue_releases r WHERE r.attachment_id=a.id)
            AND NOT EXISTS (SELECT 1 FROM jobs j JOIN print_attempts p ON p.job_id=j.id WHERE j.attachment_id=a.id)
            AND (a.state!='DONE' OR EXISTS (
                SELECT 1 FROM jobs j WHERE j.attachment_id=a.id AND j.status IN {UNFINISHED}))'''
        count = self.db.one('SELECT COUNT(*) AS n ' + condition)['n']
        rows = self.db.rows('''SELECT a.*,m.subject,
            (SELECT MIN(j.id) FROM jobs j WHERE j.attachment_id=a.id) AS job_id
            FROM attachments a JOIN processed_messages m ON m.id=a.message_id
            WHERE a.id IN (SELECT a.id ''' + condition + ') ORDER BY a.id LIMIT 200')
        return dict(count=count, attachments=rows)
