"""Printer queue persistence: releases and schedule checkpoints are atomic."""
from __future__ import annotations

import json

from .db import Database

STATE_KEY = 'print_schedule_state'
# A completed/ambiguous job is never eligible for automatic reprinting.
UNFINISHED = "('PREPARING','READY','SUBMITTED','PRINTER ERROR')"
IMMEDIATE_JOB_PREFIX = 'print-job-now:'
IMMEDIATE_JOB_STATUSES = ('READY', 'SUBMITTED', 'PRINTER ERROR')
ACTIVITY_SELECT = '''SELECT j.*,a.filename,a.path AS source_path,m.subject,m.sender,
    (SELECT o.path FROM outputs o WHERE o.job_id=j.id AND o.role='Generated PDF'
     ORDER BY o.id LIMIT 1) AS generated_filename,
    p.request_id AS attempt_request_id,p.state AS attempt_state,
    (SELECT s.message FROM steps s WHERE s.job_id=j.id ORDER BY s.id DESC LIMIT 1) AS latest_step
    FROM jobs j LEFT JOIN attachments a ON a.id=j.attachment_id
    LEFT JOIN processed_messages m ON m.id=a.message_id
    LEFT JOIN print_attempts p ON p.id=(SELECT MAX(id) FROM print_attempts WHERE job_id=j.id)'''


class PrintQueueRepository:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _validate_generated_pdf(identity: str, pages: int) -> None:
        if not identity.startswith('pdf:'):
            raise ValueError('Generated PDF identity must use the pdf: namespace.')
        if type(pages) is not int or pages < 1:
            raise ValueError('Generated PDF must contain at least one page.')

    def _enqueue_generated_pdf(
        self,
        identity: str,
        path,
        pages: int,
        options: dict,
        now: float,
        *,
        immediate: bool,
    ) -> tuple[int, bool]:
        self._validate_generated_pdf(identity, pages)
        path = str(path)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute(
                'SELECT id FROM jobs WHERE attachment_id IS NULL AND group_key=? ORDER BY id LIMIT 1',
                (identity,),
            ).fetchone()
            if existing:
                job_id, created = int(existing['id']), False
            else:
                job_id = conn.execute(
                    """INSERT INTO jobs(
                        attachment_id,group_key,status,printable,page_count,tabloid,next_attempt,created,updated
                    ) VALUES (NULL,?,'READY',?,?,0,0,?,?)""",
                    (identity, path, pages, now, now),
                ).lastrowid
                conn.execute(
                    'INSERT INTO meta(key,value) VALUES (?,?)',
                    ('job_print_settings:' + str(job_id), json.dumps(options, sort_keys=True)),
                )
                conn.execute(
                    'INSERT INTO outputs(job_id,role,path) VALUES (?,?,?)',
                    (job_id, 'Generated PDF', path),
                )
                conn.execute(
                    'INSERT INTO steps(job_id,at,message) VALUES (?,?,?)',
                    (job_id, now, f'Generated PDF queued: {pages} page(s)'),
                )
                created = True

            if immediate:
                command = IMMEDIATE_JOB_PREFIX + str(job_id)
                if not conn.execute('SELECT 1 FROM commands WHERE name=?', (command,)).fetchone():
                    conn.execute('INSERT INTO commands(name,created) VALUES (?,?)', (command, now))
                conn.execute(
                    'INSERT INTO steps(job_id,at,message) VALUES (?,?,?)',
                    (job_id, now, 'Immediate print requested; this job goes before waiting software-queue jobs.'),
                )
            return int(job_id), created

    def enqueue_generated_pdf(self, identity: str, path, pages: int, options: dict, now: float) -> tuple[int, bool]:
        """Queue one already-rendered PDF exactly once for a durable identity."""
        return self._enqueue_generated_pdf(
            identity, path, pages, options, now, immediate=False
        )

    def enqueue_immediate_generated_pdf(
        self, identity: str, path, pages: int, options: dict, now: float
    ) -> tuple[int, bool]:
        """Queue a generated PDF and mark it for worker-first submission."""
        return self._enqueue_generated_pdf(
            identity, path, pages, options, now, immediate=True
        )

    def immediate_jobs(self, now: float) -> list[dict]:
        """Return due immediate jobs ahead of normal queue ordering.

        The durable command remains until the job reaches a terminal state, so
        CUPS reconciliation for this one-off print keeps its front-of-queue behavior.
        """
        jobs = []
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            commands = list(conn.execute(
                'SELECT id,name FROM commands WHERE name LIKE ? ORDER BY id',
                (IMMEDIATE_JOB_PREFIX + '%',),
            ))
            for command in commands:
                raw_id = command['name'][len(IMMEDIATE_JOB_PREFIX):]
                if not raw_id.isdecimal():
                    conn.execute('DELETE FROM commands WHERE id=?', (command['id'],))
                    continue
                job = conn.execute('SELECT * FROM jobs WHERE id=?', (int(raw_id),)).fetchone()
                if job is None or job['status'] not in IMMEDIATE_JOB_STATUSES:
                    conn.execute('DELETE FROM commands WHERE id=?', (command['id'],))
                    continue
                if float(job['next_attempt'] or 0) <= now:
                    jobs.append(dict(job))
            return jobs[:5]

    def job_status(self, job_id: int) -> dict | None:
        return self.db.one(
            'SELECT id,status,error,page_count,completed,updated FROM jobs WHERE id=?',
            (int(job_id),),
        )

    def recent_activity(self, limit: int = 200) -> list[dict]:
        """Recently changed jobs retain receipts after they leave the waiting queue."""
        return self.db.rows(ACTIVITY_SELECT + ' ORDER BY j.updated DESC,j.id DESC LIMIT ?',
                            (max(1, min(int(limit), 200)),))

    def activity_job(self, job_id: int) -> dict | None:
        return self.db.one(ACTIVITY_SELECT + ' WHERE j.id=?', (job_id,))

    def worker_heartbeat(self) -> float:
        return float(self.db.get('worker_heartbeat', 0) or 0)

    def last_report_printed(self):
        row = self.db.one("SELECT MAX(completed) AS at FROM jobs WHERE status='PRINTED'")
        return row['at']

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
