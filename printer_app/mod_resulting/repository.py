"""Only SQLite access for the isolated MOD resulting sandbox."""
from __future__ import annotations

from dataclasses import asdict
import json
import time


class ResultingRepository:
    def __init__(self, db):
        self.db = db

    def day(self, day):
        return self.db.one('SELECT * FROM mod_result_days WHERE day=?', (day,))

    def sheets(self, day):
        rows = self.db.rows('''SELECT work_order_id,snapshot,draft,revision,current,
                submitted_at,submit_error FROM mod_result_sheets
                WHERE day=? ORDER BY json_extract(snapshot,'$.scheduled_start'),
                  json_extract(snapshot,'$.lead_name')''', (day,))
        for row in rows:
            row['snapshot'] = json.loads(row['snapshot'])
            row['draft'] = json.loads(row['draft'])
        return rows

    def refresh(self, day, records):
        """Replace external snapshots, never an unsubmitted draft or receipt."""
        now = time.time()
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT OR IGNORE INTO mod_result_days(day) VALUES(?)', (day,))
            state = conn.execute('SELECT submitting FROM mod_result_days WHERE day=?', (day,)).fetchone()
            if state['submitting']:
                raise ValueError('Cannot refresh while end-of-day submission is running.')
            conn.execute('UPDATE mod_result_sheets SET current=0 WHERE day=?', (day,))
            for record in records:
                snapshot = asdict(record)
                conn.execute('''INSERT INTO mod_result_sheets(day,work_order_id,snapshot,current)
                        VALUES(?,?,?,1)
                        ON CONFLICT(day,work_order_id) DO UPDATE SET
                        snapshot=excluded.snapshot,current=1''',
                             (day, record.source_id, json.dumps(snapshot)))
            conn.execute('UPDATE mod_result_days SET refreshed_at=? WHERE day=?', (now, day))

    def save_draft(self, day, work_order_id, draft, revision):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            day_state = conn.execute('SELECT submitting FROM mod_result_days WHERE day=?', (day,)).fetchone()
            if day_state is None:
                raise LookupError('No MOD sheets have been loaded for this day.')
            if day_state['submitting']:
                raise ValueError('Submission in progress; editing is locked.')
            result = conn.execute('''UPDATE mod_result_sheets SET draft=?,revision=revision+1
                    WHERE day=? AND work_order_id=? AND revision=? AND submitted_at IS NULL''',
                (json.dumps(draft), day, work_order_id, int(revision)))
            if result.rowcount != 1:
                raise ValueError('Sheet changed or already submitted. Reload before editing.')
            row = conn.execute('''SELECT revision FROM mod_result_sheets
                    WHERE day=? AND work_order_id=?''', (day, work_order_id)).fetchone()
            return row['revision']

    def select_mod(self, day, user_id, user_name):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT OR IGNORE INTO mod_result_days(day) VALUES(?)', (day,))
            state = conn.execute('SELECT submitting,submitted_at FROM mod_result_days WHERE day=?',
                                 (day,)).fetchone()
            if state['submitting'] or state['submitted_at']:
                raise ValueError('The MOD cannot change during or after submission.')
            conn.execute('UPDATE mod_result_days SET mod_user_id=?,mod_user_name=? WHERE day=?',
                         (user_id, user_name, day))

    def begin_submit(self, day):
        """Atomic guard prevents two web workers submitting the same day."""
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            result = conn.execute('''UPDATE mod_result_days SET submitting=1
                    WHERE day=? AND submitting=0 AND mod_user_id!=''
                    AND submitted_at IS NULL''', (day,))
            if result.rowcount != 1:
                raise ValueError('Select a MOD, or a submission is already underway.')
            records = conn.execute('''SELECT work_order_id,snapshot,draft
                    FROM mod_result_sheets WHERE day=? AND submitted_at IS NULL''', (day,)).fetchall()
            pending = []
            for row in records:
                draft = json.loads(row['draft'])
                if draft.get('dispo'):
                    pending.append({
                        'work_order_id': row['work_order_id'],
                        'snapshot': json.loads(row['snapshot']),
                        'draft': draft,
                    })
            return pending

    def finish_item(self, day, work_order_id):
        with self.db.connect() as conn:
            conn.execute('''UPDATE mod_result_sheets SET submitted_at=?,submit_error=''
                    WHERE day=? AND work_order_id=? AND submitted_at IS NULL''',
                         (time.time(), day, work_order_id))

    def error_item(self, day, work_order_id, message):
        with self.db.connect() as conn:
            conn.execute('''UPDATE mod_result_sheets SET submit_error=?
                    WHERE day=? AND work_order_id=?''',
                         (str(message)[:500], day, work_order_id))

    def finish_submit(self, day, complete=False):
        with self.db.connect() as conn:
            conn.execute('UPDATE mod_result_days SET submitting=0,submitted_at=? WHERE day=?',
                         (time.time() if complete else None, day))
