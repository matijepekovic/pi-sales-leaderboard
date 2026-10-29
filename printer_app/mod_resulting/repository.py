"""Only SQLite access for the isolated MOD resulting sandbox."""
from __future__ import annotations

from dataclasses import asdict
import json
import time


class ResultingRepository:
    def __init__(self, db):
        self.db = db

    def auto_attempt(self, day):
        value = self.db.get('mod_result_auto_pull:' + day, {})
        return value if isinstance(value, dict) else {}

    def record_auto_attempt(self, day, at, error=''):
        # One durable retry cursor, owned by this repository.
        self.db.set('mod_result_auto_pull:' + day,
                    {'at': float(at), 'error': str(error)[:250]})

    def day(self, day):
        return self.db.one('SELECT * FROM mod_result_days WHERE day=?', (day,))

    def imported_market(self, day):
        """Market used for this day's imported sheets, not current Settings."""
        value = self.db.get('mod_result_market:' + day, '')
        return value if isinstance(value, str) else ''

    def sheets(self, day):
        rows = self.db.rows('''SELECT work_order_id,snapshot,draft,revision,current,
                submitted_at,submit_error FROM mod_result_sheets
                WHERE day=? ORDER BY display_order,work_order_id''', (day,))
        for row in rows:
            row['snapshot'] = json.loads(row['snapshot'])
            row['draft'] = json.loads(row['draft'])
        return rows

    def submitted_sheets(self, day):
        """Only locally confirmed Salesforce writes belong in the completed PDF."""
        rows = self.db.rows('''SELECT work_order_id,snapshot,draft
            FROM mod_result_sheets WHERE day=? AND submitted_at>0
            ORDER BY display_order,work_order_id''', (day,))
        return [dict(work_order_id=row['work_order_id'],
                     snapshot=json.loads(row['snapshot']),
                     draft=json.loads(row['draft'])) for row in rows]

    def sheet_snapshot(self, day, work_order_id):
        row = self.db.one(
            'SELECT snapshot FROM mod_result_sheets WHERE day=? AND work_order_id=?',
            (day, work_order_id))
        if row is None:
            raise LookupError('This MOD sheet is not part of the selected day.')
        return json.loads(row['snapshot'])

    def refresh(self, day, records, external_drafts=None, market_segment=None):
        """Refresh source and verified Salesforce result data without erasing edits.

        Only untouched revision-zero drafts receive server values. A disposition
        already present in Salesforce is an existing completed result, not a new
        item for the End of Day writer to submit again. The -1 submitted marker
        denotes a read-only remote result, distinct from an actual local write
        receipt (positive Unix timestamp), so later Refresh updates still work.
        """
        external_drafts = external_drafts or {}
        if market_segment is not None and (
            not isinstance(market_segment, str) or len(market_segment) > 128
            or any(not char.isprintable() for char in market_segment)
        ):
            raise ValueError('Invalid imported MOD market.')
        now = time.time()
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT OR IGNORE INTO mod_result_days(day) VALUES(?)', (day,))
            state = conn.execute('SELECT submitting FROM mod_result_days WHERE day=?', (day,)).fetchone()
            if state['submitting']:
                raise ValueError('Cannot refresh while end-of-day submission is running.')
            # Persist the actual import scope transactionally with the sheets.
            # Changing Settings later must not silently change Select MOD.
            if market_segment is not None:
                market_key = 'mod_result_market:' + day
                previous = conn.execute(
                    'SELECT value FROM meta WHERE key=?', (market_key,)).fetchone()
                old_market = json.loads(previous['value']) if previous else ''
                if old_market and old_market != market_segment:
                    conn.execute(
                        "UPDATE mod_result_days SET mod_user_id='',mod_user_name='' WHERE day=? "
                        "AND submitted_at IS NULL", (day,))
                conn.execute(
                    'INSERT INTO meta(key,value) VALUES(?,?) '
                    'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    (market_key, json.dumps(market_segment)))
            conn.execute('UPDATE mod_result_sheets SET current=0 WHERE day=?', (day,))
            for position, record in enumerate(records):
                snapshot = asdict(record)
                conn.execute('''INSERT INTO mod_result_sheets
                            (day,work_order_id,snapshot,current,display_order)
                        VALUES(?,?,?,1,?)
                        ON CONFLICT(day,work_order_id) DO UPDATE SET
                        snapshot=excluded.snapshot,current=1,
                        display_order=excluded.display_order''',
                             (day, record.source_id, json.dumps(snapshot), position))
                if record.source_id in external_drafts:
                    draft = external_drafts[record.source_id]
                    # A locally edited sheet always wins over a remote refresh.
                    # Imported, already-resulted work is excluded from
                    # submission to prevent rewriting existing Salesforce data.
                    completed = -1.0 if draft.get('dispo') else None
                    conn.execute('''UPDATE mod_result_sheets
                        SET draft=?,submitted_at=?
                        WHERE day=? AND work_order_id=? AND revision=0
                        AND (submitted_at IS NULL OR submitted_at=-1.0)''',
                        (json.dumps(draft), completed, day, record.source_id))
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

    def begin_submit(self, day, work_order_ids=None):
        """Lock and resolve one exact batch without sealing the entire day."""
        selected = None
        if work_order_ids is not None:
            if (not isinstance(work_order_ids, list) or not work_order_ids
                    or len(work_order_ids) > 2000
                    or any(not isinstance(value, str) or not value
                           for value in work_order_ids)
                    or len(set(work_order_ids)) != len(work_order_ids)):
                raise ValueError('Select valid, distinct Work Orders.')
            selected = set(work_order_ids)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            result = conn.execute('''UPDATE mod_result_days SET submitting=1
                    WHERE day=? AND submitting=0 AND mod_user_id!='' ''', (day,))
            if result.rowcount != 1:
                raise ValueError('Select a MOD, or a submission is already underway.')
            records = conn.execute('''SELECT work_order_id,snapshot,draft
                    FROM mod_result_sheets WHERE day=? AND submitted_at IS NULL
                    ORDER BY display_order,work_order_id''', (day,)).fetchall()
            pending = []
            for row in records:
                draft = json.loads(row['draft'])
                if draft.get('dispo') and (selected is None or
                                          row['work_order_id'] in selected):
                    pending.append({
                        'work_order_id': row['work_order_id'],
                        'snapshot': json.loads(row['snapshot']),
                        'draft': draft,
                    })
            if selected is not None and {row['work_order_id'] for row in pending} != selected:
                raise ValueError('Selected Work Orders changed or were already submitted. Refresh and try again.')
            return pending

    def finish_item(self, day, work_order_id):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = time.time()
            updated = conn.execute('''UPDATE mod_result_sheets
                    SET submitted_at=?,submit_error=''
                    WHERE day=? AND work_order_id=? AND submitted_at IS NULL''',
                    (now, day, work_order_id))
            if updated.rowcount != 1:
                raise ValueError('Work Order submission receipt is already recorded.')
            # First successful write fixes the day's MOD, but later batches
            # remain possible. The day timestamp no longer means "sealed".
            conn.execute('''UPDATE mod_result_days
                    SET submitted_at=COALESCE(submitted_at,?) WHERE day=?''',
                    (now, day))

    def error_item(self, day, work_order_id, message):
        with self.db.connect() as conn:
            conn.execute('''UPDATE mod_result_sheets SET submit_error=?
                    WHERE day=? AND work_order_id=? AND submitted_at IS NULL''',
                         (str(message)[:500], day, work_order_id))

    def finish_submit(self, day):
        with self.db.connect() as conn:
            conn.execute('UPDATE mod_result_days SET submitting=0 WHERE day=?', (day,))
