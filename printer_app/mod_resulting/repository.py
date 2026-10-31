"""Only SQLite access for the isolated MOD resulting sandbox."""
from __future__ import annotations

from dataclasses import asdict
import json
import time

from .contract import canceled_without_notes, has_mod_notes


def _apply_remote_changes(local, previous, incoming):
    """Three-way update: only fields changed remotely can replace local values."""
    if not (isinstance(local, dict) and isinstance(previous, dict)
            and isinstance(incoming, dict)):
        return incoming if previous != incoming else local
    merged = dict(local)
    for key in set(previous) | set(incoming):
        if key not in incoming:
            merged.pop(key, None)
        elif key not in previous:
            merged[key] = incoming[key]
        elif previous[key] != incoming[key]:
            if (key == 'checkbox_values' and isinstance(previous[key], dict)
                    and isinstance(incoming[key], dict)):
                # A changed Salesforce checkbox scalar is one atomic source
                # observation: its local edited marker must not survive while
                # replacing just the value. Unchanged remote fields preserve
                # the entire locally edited checkbox entry.
                values = dict(local.get(key) or {})
                for field in set(previous[key]) | set(incoming[key]):
                    if previous[key].get(field) != incoming[key].get(field):
                        if field in incoming[key]:
                            values[field] = incoming[key][field]
                        else:
                            values.pop(field, None)
                merged[key] = values
            else:
                merged[key] = _apply_remote_changes(
                    local.get(key), previous[key], incoming[key])
    return merged


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
        """Every card displayed for the day, including previously imported rows."""
        rows = self.db.rows('''SELECT work_order_id,snapshot,draft
            FROM mod_result_sheets WHERE day=?
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

    @staticmethod
    def _archive_notes(conn, day, work_order_id, draft, reason):
        """Save a recoverable local checkpoint before any note replacement."""
        notes = str(draft.get('notes') or '')
        redlines = str(draft.get('redlines') or '')
        runs = draft.get('note_runs') or []
        if not (notes or redlines or runs):
            return
        conn.execute('''INSERT INTO mod_result_note_backups
            (day,work_order_id,saved_at,reason,notes,redlines,note_runs)
            VALUES (?,?,?,?,?,?,?)''',
            (day, work_order_id, time.time(), reason, notes,
             redlines, json.dumps(runs)))
        # Bound autosave history on small Pi disks; Clear also creates a checkpoint.
        conn.execute('''DELETE FROM mod_result_note_backups
            WHERE day=? AND work_order_id=? AND id NOT IN
                (SELECT id FROM mod_result_note_backups
                 WHERE day=? AND work_order_id=?
                 ORDER BY id DESC LIMIT 30)''',
            (day, work_order_id, day, work_order_id))

    def refresh(self, day, records, external_drafts=None, market_segment=None,
                *, clear_local=False, initial_only=False):
        """Reconcile explicit Salesforce Refresh against its last remote baseline.

        Unchanged remote fields never overwrite local edits. Salesforce changes
        win only their affected fields, including cancellations. Locally edited
        MOD Notes and red ink are protected even when other remote fields move.
        Existing drafts without a remote baseline are treated conservatively.
        Clear is the explicit local reset and archives notes before replacing.
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
            state = conn.execute('SELECT submitting,refreshed_at FROM mod_result_days WHERE day=?',
                                 (day,)).fetchone()
            if state['submitting']:
                raise ValueError('Cannot refresh while end-of-day submission is running.')
            if initial_only and (state['refreshed_at'] > 0 or conn.execute(
                    'SELECT 1 FROM mod_result_sheets WHERE day=? LIMIT 1',
                    (day,)).fetchone()):
                # Atomic guard against a background import queued just before
                # the user began editing. Only explicit Refresh can reconcile.
                return False
            if market_segment is not None:
                market_key = 'mod_result_market:' + day
                previous = conn.execute('SELECT value FROM meta WHERE key=?',
                                        (market_key,)).fetchone()
                old_market = json.loads(previous['value']) if previous else ''
                if old_market and old_market != market_segment:
                    conn.execute(
                        "UPDATE mod_result_days SET mod_user_id='',mod_user_name='' WHERE day=? "
                        "AND submitted_at IS NULL", (day,))
                conn.execute(
                    'INSERT INTO meta(key,value) VALUES(?,?) '
                    'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    (market_key, json.dumps(market_segment)))
            prior_rows = {
                row['work_order_id']: row for row in conn.execute(
                    'SELECT work_order_id,draft,revision,submitted_at,override_active '
                    'FROM mod_result_sheets WHERE day=?', (day,)
                ).fetchall()
            }
            conn.execute('UPDATE mod_result_sheets SET current=0 WHERE day=?', (day,))
            for position, record in enumerate(records):
                ident = record.source_id
                old = prior_rows.get(ident)
                conn.execute('''INSERT INTO mod_result_sheets
                    (day,work_order_id,snapshot,current,display_order)
                    VALUES(?,?,?,1,?)
                    ON CONFLICT(day,work_order_id) DO UPDATE SET
                    snapshot=excluded.snapshot,current=1,
                    display_order=excluded.display_order''',
                    (day, ident, json.dumps(asdict(record)), position))
                if ident not in external_drafts:
                    continue
                incoming = dict(external_drafts[ident])
                previous_local = json.loads(old['draft']) if old else {}
                baseline_key = 'mod_result_sf_baseline:' + day + ':' + ident
                baseline_row = conn.execute(
                    'SELECT value FROM meta WHERE key=?', (baseline_key,)).fetchone()
                baseline = json.loads(baseline_row['value']) if baseline_row else None
                notes_key = 'mod_result_sf_notes:' + day + ':' + ident
                prior_note = conn.execute(
                    'SELECT value FROM meta WHERE key=?', (notes_key,)).fetchone()
                prior_note_text = json.loads(prior_note['value']) if prior_note else None

                if clear_local or old is None:
                    merged = dict(incoming)
                elif baseline is not None:
                    merged = _apply_remote_changes(previous_local, baseline, incoming)
                elif old['revision'] == 0:
                    # Legacy pristine rows can accept the first full remote read.
                    merged = dict(incoming)
                else:
                    # No trusted comparison baseline exists for old local edits.
                    # Establish one without mistaking those edits for Salesforce.
                    merged = dict(previous_local)

                if old and not clear_local:
                    prior_remote_note = (baseline.get('notes', '')
                                         if baseline is not None else prior_note_text)
                    locally_edited_notes = (
                        previous_local.get('notes', '') != prior_remote_note
                        if prior_remote_note is not None else old['revision'] > 0
                    )
                    locally_edited_notes = locally_edited_notes or bool(
                        previous_local.get('note_runs'))
                    if locally_edited_notes:
                        merged['notes'] = previous_local.get('notes', '')
                        merged['note_runs'] = previous_local.get('note_runs', [])
                    # Redlines are user-owned, not a field in Salesforce's
                    # projected draft. Never discard them on Refresh.
                    merged['redlines'] = previous_local.get('redlines', '')

                # A canceled Lead always takes precedence, including over a
                # locally drafted Dispo or an old unmatched product result.
                canceled = str(incoming.get('lead_status') or '').strip().casefold() == 'canceled'
                new_cancellation = canceled and (
                    baseline is None or str(baseline.get('lead_status') or '').strip().casefold() != 'canceled'
                )
                if new_cancellation:
                    merged['dispo'] = 'cxl'
                    merged['lead_status'] = incoming['lead_status']

                # Service Appointment cancellations are separate from Lead
                # cancellations. Do not turn a blank, canceled-only card into
                # an eligible End-of-Day result. If the MOD has written notes,
                # keep the card visible and make its disposition clearly CXL.
                # An explicit Salesforce result remains authoritative. An
                # appointment canceled after a completed Sale/PNS/etc. is not
                # permission to rewrite that actual Work Order result.
                source_resulted = bool(incoming.get('dispo') or any(
                    item.get('result') for item in
                    incoming.get('product_results', {}).values()))
                if (record.appointment_canceled and has_mod_notes(merged)
                        and not source_resulted):
                    merged['dispo'] = 'cxl'

                # Clear must be explicit, and any note replacement is backed up.
                if old and any(
                    previous_local.get(key) != merged.get(key)
                    for key in ('notes', 'redlines', 'note_runs')
                ):
                    self._archive_notes(
                        conn, day, ident, previous_local,
                        'clear' if clear_local else 'salesforce_refresh')

                # The remote baseline is updated separately, never from local
                # drafts. Failed reads never reach this SQLite transaction.
                conn.execute('''INSERT INTO meta(key,value) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                    (baseline_key, json.dumps(incoming)))
                conn.execute('''INSERT INTO meta(key,value) VALUES(?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                    (notes_key, json.dumps(incoming.get('notes', ''))))

                remote_resulted = source_resulted
                remote_result_changed = (baseline is not None and any(
                    baseline.get(key) != incoming.get(key)
                    for key in ('dispo', 'product_results', 'lead_status')))
                if new_cancellation:
                    remote_result_changed = True
                receipt = old['submitted_at'] if old else None
                if remote_resulted:
                    completed = receipt if receipt is not None and receipt > 0 else -1.0
                    conn.execute('''UPDATE mod_result_submission_items SET
                        state='submitted',error=''
                        WHERE work_order_id=? AND state='uncertain'
                        AND job_id IN (SELECT id FROM mod_result_submission_jobs WHERE day=?)''',
                        (ident, day))
                elif old and not remote_result_changed and not clear_local:
                    # An unchanged blank remote result is not evidence that
                    # an earlier successful local write should be replayed.
                    completed = receipt
                else:
                    completed = None

                override_active = (0 if (clear_local or
                    (remote_result_changed and remote_resulted)) else
                    int(old['override_active']) if old else 0)
                revision = old['revision'] if old else 0
                if old and (merged != previous_local or
                            override_active != old['override_active']):
                    revision += 1
                conn.execute('''UPDATE mod_result_sheets SET
                    draft=?,revision=?,submitted_at=?,override_active=0,
                    submit_error='' WHERE day=? AND work_order_id=?''',
                    (json.dumps(merged), revision, completed, day, ident))
                if override_active:
                    conn.execute('''UPDATE mod_result_sheets SET override_active=1
                        WHERE day=? AND work_order_id=?''', (day, ident))
            conn.execute('UPDATE mod_result_days SET refreshed_at=? WHERE day=?', (now, day))
            return True

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
            before = conn.execute('''SELECT draft FROM mod_result_sheets
                    WHERE day=? AND work_order_id=? AND revision=?
                    AND (submitted_at IS NULL OR override_active=1)''',
                    (day, work_order_id, int(revision))).fetchone()
            if before is None:
                raise ValueError('Sheet changed or already submitted. Reload before editing.')
            prior = json.loads(before['draft'])
            if any(prior.get(key) != draft.get(key)
                   for key in ('notes', 'redlines', 'note_runs')):
                self._archive_notes(conn, day, work_order_id, prior, 'local_edit')
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
            snapshot = json.loads(row['snapshot'])
            # A canceled card hidden for having no notes is never silently
            # submitted by Submit All, even if an old local Dispo remains.
            if canceled_without_notes(snapshot, draft):
                continue
            if draft.get('dispo') and (selected is None or row['work_order_id'] in selected):
                pending.append({
                    'work_order_id': row['work_order_id'],
                    'snapshot': snapshot,
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
            job = conn.execute('''SELECT id,day,created_at FROM mod_result_submission_jobs
                WHERE state='queued' ORDER BY id LIMIT 1''').fetchone()
            if job is None:
                return None
            day = job['day']
            state = conn.execute('SELECT submitting,mod_user_id FROM mod_result_days WHERE day=?',
                                 (day,)).fetchone()
            if not state or not state['submitting'] or not state['mod_user_id']:
                raise ValueError('Queued MOD submission lost its reserved day.')
            now = time.time()
            conn.execute('''UPDATE mod_result_submission_jobs SET
                state='running', started_at=?, stage='Preparing submission',
                stage_started=? WHERE id=? AND state='queued' ''',
                (now, now, job['id']))
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
                    'queued_at': job['created_at'], 'rows': rows}

    def submission_stage(self, job_id, stage):
        """Persist the active preflight stage for the progress dashboard."""
        if not isinstance(stage, str) or not 0 < len(stage) <= 120:
            raise ValueError('Invalid submission stage.')
        with self.db.connect() as conn:
            updated = conn.execute('''UPDATE mod_result_submission_jobs
                SET stage=?,stage_started=? WHERE id=? AND state='running' ''',
                (stage, time.time(), job_id))
            if updated.rowcount != 1:
                raise LookupError('Active submission stage is unavailable.')

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

    def latest_submission(self, day, job_id=None):
        fields = 'id,day,state,created_at,started_at,finished_at,stage,stage_started,error'
        if job_id is not None:
            job = self.db.one('SELECT ' + fields +
                              ' FROM mod_result_submission_jobs WHERE id=?', (job_id,))
        else:
            # A long-running End of Day may cross local midnight. Show that
            # active batch before showing a completed batch for the new day.
            job = self.db.one('SELECT ' + fields + ''' FROM mod_result_submission_jobs
                WHERE state IN ('queued','running') ORDER BY id DESC LIMIT 1''')
            if job is None:
                job = self.db.one('SELECT ' + fields +
                                  ' FROM mod_result_submission_jobs WHERE day=? '
                                  'ORDER BY id DESC LIMIT 1', (day,))
        if not job:
            return None
        items = self.db.rows('''SELECT work_order_number,state,error
            FROM mod_result_submission_items WHERE job_id=? ORDER BY position''',
            (job['id'],))
        elapsed = max(0, int(time.time() - job['stage_started'])) if (
            job['state'] == 'running' and job['stage_started']) else 0
        return {**job, 'items': items, 'stage_elapsed_seconds': elapsed,
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
