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
                submitted_at,override_active,submit_error FROM mod_result_sheets
                WHERE day=? ORDER BY display_order,work_order_id''', (day,))
        for row in rows:
            row['snapshot'] = json.loads(row['snapshot'])
            row['draft'] = json.loads(row['draft'])
        return rows

    def print_sheets(self, day):
        """All current imported cards; no disposition or submission filter."""
        rows = self.db.rows('''SELECT work_order_id,snapshot,draft
            FROM mod_result_sheets WHERE day=? AND current=1
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

    def refresh(self, day, records, external_drafts=None, market_segment=None,
                *, clear_local=False):
        """Apply a verified Salesforce snapshot atomically.

        Salesforce owns every resulting field, even for completed sheets.
        Locally edited MOD Notes and redlines are the only normal Refresh
        exceptions. Refresh cancels any manual override. Successful End-of-Day
        receipt timestamps survive only while Salesforce still has a result.

        Clear also discards local Notes before importing the same verified
        Salesforce snapshot. Remote-note baselines distinguish local edits
        from older Salesforce notes even when other controls were edited.
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
            previous = {
                row['work_order_id']: row for row in conn.execute(
                    'SELECT work_order_id,draft,revision,submitted_at,override_active '
                    'FROM mod_result_sheets WHERE day=?', (day,)
                ).fetchall()
            }
            if clear_local:
                # Clear is a LOCAL reset. Inactive drafts are reset too; actual
                # End-of-Day receipts remain intact until Salesforce says the
                # corresponding Work Order is no longer resulted.
                conn.execute('''UPDATE mod_result_sheets
                    SET draft='{}',revision=revision+1,override_active=0,
                        submit_error=''
                    WHERE day=? AND (submitted_at IS NULL OR override_active=1)''',
                    (day,))
                conn.execute('DELETE FROM meta WHERE key LIKE ?',
                             ('mod_result_sf_notes:' + day + ':%',))
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
                if record.source_id not in external_drafts:
                    continue
                old = previous.get(record.source_id)
                remote = dict(external_drafts[record.source_id])
                imported_notes = remote['notes']
                key = 'mod_result_sf_notes:' + day + ':' + record.source_id
                marker = conn.execute('SELECT value FROM meta WHERE key=?',
                                      (key,)).fetchone()
                prior_notes = json.loads(marker['value']) if marker else None
                if old and not clear_local:
                    local = json.loads(old['draft'])
                    # On older installations there is no marker yet; preserve
                    # only explicitly edited legacy notes, not pristine imports.
                    local_edited_notes = (
                        local.get('notes', '') != (
                            prior_notes if prior_notes is not None else imported_notes
                        ) and (prior_notes is not None or old['revision'] > 0)
                    )
                    if local_edited_notes or (
                        old['revision'] > 0 and local.get('note_runs')
                    ):
                        remote['notes'] = local['notes']
                        remote['note_runs'] = local.get('note_runs', [])
                    if local.get('redlines'):
                        remote['redlines'] = local['redlines']
                source = external_drafts[record.source_id]
                # A Salesforce product result is already submitted even when
                # conflicting product outcomes cannot choose one main Dispo.
                resulted = source['dispo'] or any(
                    item.get('result')
                    for item in source.get('product_results', {}).values()
                )
                # Keep real submission timestamps while Salesforce confirms a
                # result. An empty Salesforce result is authoritative too.
                receipt = old['submitted_at'] if old else None
                completed = (receipt if receipt is not None and receipt > 0
                             else -1.0) if resulted else None
                if resulted:
                    conn.execute('''UPDATE mod_result_submission_items SET
                        state='submitted',error=''
                        WHERE work_order_id=? AND state='uncertain'
                        AND job_id IN (SELECT id FROM mod_result_submission_jobs WHERE day=?)''',
                        (record.source_id, day))
                revised = old['revision'] if old else 0
                if old and (clear_local or old['override_active']
                            or remote != json.loads(old['draft'])):
                    revised += 1
                conn.execute('''UPDATE mod_result_sheets
                    SET draft=?,revision=?,submitted_at=?,override_active=0,
                        submit_error=''
                    WHERE day=? AND work_order_id=?''',
                    (json.dumps(remote), revised, completed, day, record.source_id))
                conn.execute('''INSERT INTO meta(key,value) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                    (key, json.dumps(imported_notes)))
            conn.execute('UPDATE mod_result_days SET refreshed_at=? WHERE day=?', (now, day))

    def override(self, day, work_order_id, revision):
        """Explicitly unlock exactly one completed sheet for End of Day."""
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            state = conn.execute(
                'SELECT submitting FROM mod_result_days WHERE day=?', (day,)
            ).fetchone()
            if state is None:
                raise LookupError('No MOD sheets have been loaded for this day.')
            if state['submitting']:
                raise ValueError('Submission in progress; editing is locked.')
            updated = conn.execute('''UPDATE mod_result_sheets
                SET override_active=1,revision=revision+1,submit_error=''
                WHERE day=? AND work_order_id=?
                AND submitted_at IS NOT NULL AND override_active=0
                AND revision=?''', (day, work_order_id, int(revision)))
            if updated.rowcount != 1:
                raise ValueError('Sheet changed or is not completed. Refresh and try again.')
            return int(revision) + 1

    def save_draft(self, day, work_order_id, draft, revision):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            day_state = conn.execute('SELECT submitting FROM mod_result_days WHERE day=?', (day,)).fetchone()
            if day_state is None:
                raise LookupError('No MOD sheets have been loaded for this day.')
            if day_state['submitting']:
                raise ValueError('Submission in progress; editing is locked.')
            result = conn.execute('''UPDATE mod_result_sheets SET draft=?,revision=revision+1
                    WHERE day=? AND work_order_id=? AND revision=?
                    AND (submitted_at IS NULL OR override_active=1)''',
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

    @staticmethod
    def _selected_ids(work_order_ids):
        if work_order_ids is None:
            return None
        if (not isinstance(work_order_ids, list) or not work_order_ids
            or len(work_order_ids) > 2000
            or any(not isinstance(value, str) or not value
                   for value in work_order_ids)
            or len(set(work_order_ids)) != len(work_order_ids)):
            raise ValueError('Select valid, distinct Work Orders.')
        return set(work_order_ids)

    @staticmethod
    def _reserve_rows(conn, day, selected):
        result = conn.execute('''UPDATE mod_result_days SET submitting=1
                WHERE day=? AND submitting=0 AND mod_user_id!='' ''', (day,))
        if result.rowcount != 1:
            raise ValueError('Select a MOD, or a submission is already underway.')
        records = conn.execute('''SELECT work_order_id,snapshot,draft
                FROM mod_result_sheets WHERE day=?
                AND (submitted_at IS NULL OR override_active=1)
                ORDER BY display_order,work_order_id''', (day,)).fetchall()
        pending = []
        for row in records:
            draft = json.loads(row['draft'])
            if draft.get('dispo') and (selected is None or row['work_order_id'] in selected):
                pending.append({
                    'work_order_id': row['work_order_id'],
                    'snapshot': json.loads(row['snapshot']),
                    'draft': draft,
                })
        if selected is not None and {row['work_order_id'] for row in pending} != selected:
            raise ValueError('Selected Work Orders changed or were already submitted. Refresh and try again.')
        if not pending:
            raise ValueError('No unsubmitted sheets have a disposition.')
        # A timed-out CLI operation could have reached Salesforce. Never
        # silently retry a work order until Salesforce Refresh confirms it.
        for row in pending:
            uncertain = conn.execute('''SELECT 1 FROM mod_result_submission_items i
                JOIN mod_result_submission_jobs j ON j.id=i.job_id
                WHERE j.day=? AND i.work_order_id=? AND i.state='uncertain'
                LIMIT 1''', (day, row['work_order_id'])).fetchone()
            if uncertain:
                raise ValueError('Work Order ' + row['snapshot'].get('work_order_number', '')
                                 + ' requires Salesforce confirmation before resubmission.')
        return pending

    def begin_submit(self, day, work_order_ids=None):
        """Existing synchronous submission boundary, including override rules."""
        selected = self._selected_ids(work_order_ids)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            return self._reserve_rows(conn, day, selected)

    def enqueue_submit(self, day, work_order_ids=None):
        """Atomically lock an immutable batch and queue it for the worker."""
        selected = self._selected_ids(work_order_ids)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = self._reserve_rows(conn, day, selected)
            now = time.time()
            job_id = conn.execute('''INSERT INTO mod_result_submission_jobs
                (day,state,created_at) VALUES (?,'queued',?)''',
                (day, now)).lastrowid
            conn.executemany('''INSERT INTO mod_result_submission_items
                (job_id,work_order_id,work_order_number,position,state)
                VALUES (?,?,?,?,'pending')''', [
                    (job_id, item['work_order_id'],
                     str(item['snapshot'].get('work_order_number') or ''),
                     position)
                    for position, item in enumerate(rows)
                ])
        return {'job_id': job_id, 'day': day, 'total': len(rows)}

    def claim_submission(self):
        """Claim one queued batch; the worker is the only executor."""
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            job = conn.execute('''SELECT id,day FROM mod_result_submission_jobs
                WHERE state='queued' ORDER BY id LIMIT 1''').fetchone()
            if job is None:
                return None
            day = job['day']
            state = conn.execute('SELECT submitting,mod_user_id FROM mod_result_days WHERE day=?',
                                 (day,)).fetchone()
            if not state or not state['submitting'] or not state['mod_user_id']:
                raise ValueError('Queued MOD submission lost its reserved day.')
            conn.execute('''UPDATE mod_result_submission_jobs SET
                state='running', started_at=? WHERE id=? AND state='queued' ''',
                (time.time(), job['id']))
            records = conn.execute('''SELECT i.work_order_id,s.snapshot,s.draft
                FROM mod_result_submission_items i
                JOIN mod_result_sheets s ON s.day=? AND s.work_order_id=i.work_order_id
                WHERE i.job_id=? ORDER BY i.position''', (day, job['id'])).fetchall()
            rows = [dict(work_order_id=row['work_order_id'],
                         snapshot=json.loads(row['snapshot']),
                         draft=json.loads(row['draft'])) for row in records]
            expected = conn.execute(
                'SELECT COUNT(*) FROM mod_result_submission_items WHERE job_id=?',
                (job['id'],)).fetchone()[0]
            if len(rows) != expected:
                raise ValueError('Queued MOD sheet records changed. Submission was not started.')
            return {'job_id': job['id'], 'day': day, 'mod_id': state['mod_user_id'],
                    'rows': rows}

    def submission_item(self, job_id, work_order_id, state, error=''):
        if state not in ('pending','processing','submitted','uncertain'):
            raise ValueError('Unknown submission state.')
        with self.db.connect() as conn:
            updated = conn.execute('''UPDATE mod_result_submission_items SET state=?,error=?
                WHERE job_id=? AND work_order_id=?''',
                (state, str(error)[:500], job_id, work_order_id))
            if updated.rowcount != 1:
                raise LookupError('Submission progress item missing.')

    def finish_submission_job(self, job_id, error=''):
        with self.db.connect() as conn:
            conn.execute('''UPDATE mod_result_submission_jobs SET
                state=?,finished_at=?,error=? WHERE id=? AND state='running' ''',
                ('failed' if error else 'completed', time.time(), str(error)[:500], job_id))

    def latest_submission(self, day):
        job = self.db.one('''SELECT id,day,state,created_at,started_at,finished_at,error
            FROM mod_result_submission_jobs WHERE day=? ORDER BY id DESC LIMIT 1''', (day,))
        if not job:
            return None
        items = self.db.rows('''SELECT work_order_number,state,error
            FROM mod_result_submission_items WHERE job_id=? ORDER BY position''',
            (job['id'],))
        return {**job, 'items': items,
                'total': len(items),
                'submitted': sum(item['state']=='submitted' for item in items),
                'pending': sum(item['state']=='pending' for item in items),
                'processing': sum(item['state']=='processing' for item in items),
                'failed': sum(item['state']=='uncertain' for item in items)}

    def interrupt_abandoned_submissions(self):
        """Worker-start reconciliation; never replay an in-flight Salesforce write."""
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            jobs = list(conn.execute(
                "SELECT id,day FROM mod_result_submission_jobs WHERE state='running'"))
            for job in jobs:
                # Local receipts conclusively identify successful operations.
                conn.execute('''UPDATE mod_result_submission_items SET
                    state='submitted',error='' WHERE job_id=? AND state='processing'
                    AND EXISTS (SELECT 1 FROM mod_result_sheets s
                        WHERE s.day=? AND s.work_order_id=mod_result_submission_items.work_order_id
                        AND s.submitted_at>0 AND s.override_active=0)''',
                    (job['id'], job['day']))
                conn.execute('''UPDATE mod_result_submission_items
                    SET state='uncertain',error='Worker stopped during Salesforce submission.'
                    WHERE job_id=? AND state='processing' ''', (job['id'],))
                conn.execute('''UPDATE mod_result_submission_jobs
                    SET state='interrupted',finished_at=?,
                        error='Worker stopped before submission completed.'
                    WHERE id=?''', (time.time(), job['id']))
                conn.execute('UPDATE mod_result_days SET submitting=0 WHERE day=?',
                             (job['day'],))

    def finish_item(self, day, work_order_id):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            now = time.time()
            updated = conn.execute('''UPDATE mod_result_sheets
                    SET submitted_at=?,override_active=0,submit_error=''
                    WHERE day=? AND work_order_id=?
                    AND (submitted_at IS NULL OR override_active=1)''',
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
                    WHERE day=? AND work_order_id=?
                    AND (submitted_at IS NULL OR override_active=1)''',
                         (str(message)[:500], day, work_order_id))

    def finish_submit(self, day):
        with self.db.connect() as conn:
            conn.execute('UPDATE mod_result_days SET submitting=0 WHERE day=?', (day,))
