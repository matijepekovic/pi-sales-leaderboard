"""Only SQLite access for the isolated MOD resulting sandbox."""
from __future__ import annotations

from dataclasses import asdict
import json
import time


# A Salesforce cancellation changes the work left on this card to local
# documentation. Its completion must never stand in for a Salesforce receipt.
def _completed_at(prefix=''):
    return (f"CASE WHEN json_extract({prefix}snapshot,'$.appointment_canceled') "
            f'THEN {prefix}pdf_completed_at ELSE {prefix}submitted_at END')


_COMPLETED_AT = _completed_at()
_PDF_DOCUMENTATION_FIELDS = ('notes', 'redlines', 'note_runs', 'numbers')


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
        rows = self.db.rows(f'''SELECT work_order_id,snapshot,draft,revision,current,
                submitted_at,override_active,submit_error,pdf_documentation,
                {_COMPLETED_AT} AS completed_at
                FROM mod_result_sheets
                WHERE day=? ORDER BY display_order,work_order_id''', (day,))
        for row in rows:
            row['snapshot'] = json.loads(row['snapshot'])
            row['draft'] = json.loads(row['draft'])
            pdf_documentation = json.loads(row.pop('pdf_documentation'))
            row['pdf_notes'] = pdf_documentation.pop('supplement', {})
            if row['snapshot'].get('appointment_canceled'):
                row['draft'].update(pdf_documentation)
        return rows

    def print_sheets(self, day):
        """Every card displayed for the day, including previously imported rows."""
        rows = self.db.rows('''SELECT work_order_id,snapshot,draft,pdf_documentation
            FROM mod_result_sheets WHERE day=?
            ORDER BY display_order,work_order_id''', (day,))
        return [dict(work_order_id=row['work_order_id'],
                     snapshot=json.loads(row['snapshot']),
                     draft=json.loads(row['draft']),
                     pdf_documentation=json.loads(row['pdf_documentation'])) for row in rows]

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
                    'SELECT work_order_id,snapshot,draft,revision,submitted_at,'
                    'pdf_completed_at,pdf_documentation,override_active '
                    'FROM mod_result_sheets WHERE day=?', (day,)
                ).fetchall()
            }
            conn.execute('UPDATE mod_result_sheets SET current=0 WHERE day=?', (day,))
            for position, record in enumerate(records):
                ident = record.source_id
                old = prior_rows.get(ident)
                was_canceled = bool(old and json.loads(old['snapshot']).get('appointment_canceled'))
                cancellation_changed = was_canceled != record.appointment_canceled
                conn.execute('''INSERT INTO mod_result_sheets
                    (day,work_order_id,snapshot,current,display_order)
                    VALUES(?,?,?,1,?)
                    ON CONFLICT(day,work_order_id) DO UPDATE SET
                    snapshot=excluded.snapshot,current=1,
                    display_order=excluded.display_order''',
                    (day, ident, json.dumps(asdict(record)), position))
                if ident not in external_drafts and not cancellation_changed:
                    continue
                previous_local = json.loads(old['draft']) if old else {}
                baseline_key = 'mod_result_sf_baseline:' + day + ':' + ident
                baseline_row = conn.execute(
                    'SELECT value FROM meta WHERE key=?', (baseline_key,)).fetchone()
                baseline = json.loads(baseline_row['value']) if baseline_row else None
                incoming = dict(external_drafts.get(ident, baseline or {}))
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

                # Repair a legacy Sale-card save that erased imported Product
                # Results while leaving the Salesforce baseline unchanged.
                # Do not overwrite nonempty local individual-result edits:
                # that is a separate, intentional Refresh reconciliation rule.
                if (not merged.get('product_results')
                        and not previous_local.get('product_results')
                        and baseline is not None
                        and baseline.get('product_results')
                        and incoming.get('product_results') == baseline['product_results']):
                    merged['product_results'] = incoming['product_results']

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
                        # Source serialization provenance belongs to its Notes
                        # text. A different incoming prefix cannot describe the
                        # protected local text or reconstruct its old numbers.
                        if 'note_origin' in previous_local:
                            merged['note_origin'] = dict(previous_local['note_origin'])
                        else:
                            merged.pop('note_origin', None)
                    # Redlines are user-owned, not a field in Salesforce's
                    # projected draft. Never discard them on Refresh.
                    merged['redlines'] = previous_local.get('redlines', '')

                # Salesforce's recorded disposition is authoritative. Only an
                # unresulted canceled Service Appointment/Lead infers CXL;
                # Refresh does not send any Salesforce writes.
                source_resulted = bool(incoming.get('dispo') or any(
                    item.get('result') for item in
                    incoming.get('product_results', {}).values()))
                lead_canceled = (
                    str(record.sales_lead_status or '').strip().casefold() == 'canceled'
                    or str(incoming.get('lead_status') or '').strip().casefold() == 'canceled'
                )
                # Only a transition in the actual resulting read may
                # invalidate a local receipt; a source-only Lead status must
                # not repeatedly look like a new remote cancellation.
                new_cancellation = (
                    str(incoming.get('lead_status') or '').strip().casefold() == 'canceled'
                    and (baseline is None or
                         str(baseline.get('lead_status') or '').strip().casefold() != 'canceled')
                )
                auto_key = 'mod_result_inferred_cxl:' + day + ':' + ident
                prior_auto = conn.execute(
                    'SELECT value FROM meta WHERE key=?', (auto_key,)
                ).fetchone()
                if clear_local:
                    # Clear must discard any pre-cancellation draft backup;
                    # an active card must not resurrect explicitly cleared data.
                    conn.execute('DELETE FROM meta WHERE key=?', (auto_key,))
                    prior_auto = None
                if (record.appointment_canceled or lead_canceled) and not source_resulted:
                    # Keep the prior local Dispo for a later reactivation.
                    if prior_auto is None:
                        conn.execute('INSERT INTO meta(key,value) VALUES (?,?)',
                                     (auto_key, json.dumps(merged.get('dispo') or '')))
                    merged['dispo'] = 'cxl'
                    if lead_canceled:
                        merged['lead_status'] = (incoming.get('lead_status')
                                                 or record.sales_lead_status)
                elif prior_auto is not None:
                    # Reactivation restores only an inferred, unsent CXL.
                    # A Salesforce result or completed local write remains intact.
                    if (not source_resulted and not clear_local
                            and merged.get('dispo') == 'cxl'
                            and (old is None or old['submitted_at'] is None)):
                        merged['dispo'] = json.loads(prior_auto['value'])
                    conn.execute('DELETE FROM meta WHERE key=?', (auto_key,))

                # Clear must be explicit, and any note replacement is backed up.
                if old and any(
                    previous_local.get(key) != merged.get(key)
                    for key in ('notes', 'redlines', 'note_runs')
                ):
                    self._archive_notes(
                        conn, day, ident, previous_local,
                        'clear' if clear_local else 'salesforce_refresh')
                if old and clear_local and old['pdf_documentation'] != '{}':
                    documentation = json.loads(old['pdf_documentation'])
                    self._archive_notes(conn, day, ident, documentation, 'clear')
                    self._archive_notes(conn, day, ident,
                                        documentation.get('supplement', {}), 'clear')

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
                elif old and not remote_result_changed and not clear_local:
                    # An unchanged blank remote result is not evidence that
                    # an earlier successful local write should be replayed.
                    completed = receipt
                else:
                    completed = None

                pdf_completed_at = (old['pdf_completed_at'] if old and not clear_local
                                    and not cancellation_changed else None)
                if cancellation_changed and record.appointment_canceled and receipt and receipt > 0:
                    attempt_row = conn.execute('SELECT value FROM meta WHERE key=?',
                                               (self._attempt_key(day, ident),)).fetchone()
                    attempt = json.loads(attempt_row['value']) if attempt_row else {}
                    if (attempt.get('state') == 'submitted'
                            and attempt.get('payload', {}).get('dispo') in ('cxl', 'oos')):
                        # Our own completed CXL/OOS is still complete when its
                        # resulting Salesforce cancellation comes back on Refresh.
                        pdf_completed_at = receipt
                override_active = (0 if (clear_local or cancellation_changed or
                    (remote_result_changed and remote_resulted)) else
                    int(old['override_active']) if old else 0)
                revision = old['revision'] if old else 0
                if old and (cancellation_changed or merged != previous_local or
                            override_active != old['override_active']):
                    revision += 1
                conn.execute('''UPDATE mod_result_sheets SET
                    draft=?,revision=?,submitted_at=?,pdf_completed_at=?,override_active=0,
                    pdf_documentation=CASE WHEN ? THEN '{}' ELSE pdf_documentation END,
                    submit_error='' WHERE day=? AND work_order_id=?''',
                    (json.dumps(merged), revision, completed, pdf_completed_at,
                     clear_local, day, ident))
                if override_active:
                    conn.execute('''UPDATE mod_result_sheets SET override_active=1
                        WHERE day=? AND work_order_id=?''', (day, ident))
            conn.execute('UPDATE mod_result_days SET refreshed_at=? WHERE day=?', (now, day))
            return True

    @staticmethod
    def _work_order_submission_locked(conn, day, work_order_id):
        """Lock only reserved cards during a background batch.

        The synchronous writer has no queued job, so its legacy whole-day
        lock remains in force. All database decisions use this transaction.
        """
        active = conn.execute('''SELECT j.id FROM mod_result_submission_jobs j
            WHERE j.day=? AND j.state IN ('queued','running') LIMIT 1''',
            (day,)).fetchone()
        if active is None:
            return True
        return conn.execute('''SELECT 1 FROM mod_result_submission_items i
            JOIN mod_result_submission_jobs j ON j.id=i.job_id
            WHERE j.day=? AND i.work_order_id=?
              AND j.state IN ('queued','running') LIMIT 1''',
            (day, work_order_id)).fetchone() is not None

    def override(self, day, work_order_id, revision):
        """Explicitly unlock exactly one completed sheet for End of Day."""
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            state = conn.execute(
                'SELECT submitting FROM mod_result_days WHERE day=?', (day,)
            ).fetchone()
            if state is None:
                raise LookupError('No MOD sheets have been loaded for this day.')
            if state['submitting'] and self._work_order_submission_locked(
                    conn, day, work_order_id):
                raise ValueError('This Work Order is being submitted.')
            updated = conn.execute(f'''UPDATE mod_result_sheets
                SET override_active=1,revision=revision+1,submit_error=''
                WHERE day=? AND work_order_id=?
                AND ({_COMPLETED_AT}) IS NOT NULL AND override_active=0
                AND revision=?''', (day, work_order_id, int(revision)))
            if updated.rowcount != 1:
                raise ValueError('Sheet changed or is not completed. Refresh and try again.')
            return int(revision) + 1

    def save_pdf_notes(self, day, work_order_id, revision, notes):
        """Store supplemental print text on a locked sheet without unlocking it."""
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(f'''SELECT pdf_documentation FROM mod_result_sheets
                WHERE day=? AND work_order_id=? AND revision=? AND override_active=0
                AND ({_COMPLETED_AT}) IS NOT NULL''', (day, work_order_id, revision)).fetchone()
            if row is None:
                raise ValueError('This completed MOD sheet changed. Reload it before saving PDF notes.')
            documentation = json.loads(row['pdf_documentation'])
            previous = documentation.get('supplement', {})
            if previous == notes:
                return revision
            self._archive_notes(conn, day, work_order_id, previous, 'pdf_notes_edit')
            documentation['supplement'] = notes
            conn.execute('''UPDATE mod_result_sheets SET pdf_documentation=?,revision=revision+1
                WHERE day=? AND work_order_id=?''', (json.dumps(documentation), day, work_order_id))
            return revision + 1

    def save_draft(self, day, work_order_id, draft, revision):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            day_state = conn.execute('SELECT submitting FROM mod_result_days WHERE day=?', (day,)).fetchone()
            if day_state is None:
                raise LookupError('No MOD sheets have been loaded for this day.')
            if day_state['submitting'] and self._work_order_submission_locked(
                    conn, day, work_order_id):
                raise ValueError('This Work Order is being submitted.')
            before = conn.execute(f'''SELECT draft,pdf_documentation,
                    json_extract(snapshot,'$.appointment_canceled') AS pdf_only
                    FROM mod_result_sheets
                    WHERE day=? AND work_order_id=? AND revision=?
                    AND (({_COMPLETED_AT}) IS NULL OR override_active=1)''',
                    (day, work_order_id, int(revision))).fetchone()
            if before is None:
                raise ValueError('Sheet changed or already submitted. Reload before editing.')
            prior = json.loads(before['draft'])
            pdf_documentation = json.loads(before['pdf_documentation'])
            previous = dict(prior, **pdf_documentation) if before['pdf_only'] else prior
            if any(previous.get(key) != draft.get(key)
                   for key in ('notes', 'redlines', 'note_runs')):
                self._archive_notes(conn, day, work_order_id, previous, 'local_edit')
            if before['pdf_only']:
                for key in _PDF_DOCUMENTATION_FIELDS:
                    if draft.get(key) != previous.get(key):
                        pdf_documentation[key] = draft.get(key, [] if key == 'note_runs' else '')
                draft = {key: value for key, value in draft.items()
                         if key not in _PDF_DOCUMENTATION_FIELDS}
                draft.update({key: prior[key] for key in _PDF_DOCUMENTATION_FIELDS if key in prior})
            result = conn.execute(f'''UPDATE mod_result_sheets
                    SET draft=?,pdf_documentation=?,revision=revision+1
                    WHERE day=? AND work_order_id=? AND revision=?
                    AND (({_COMPLETED_AT}) IS NULL OR override_active=1)''',
                    (json.dumps(draft), json.dumps(pdf_documentation),
                     day, work_order_id, int(revision)))
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
        records = conn.execute(f'''SELECT work_order_id,snapshot,draft
                FROM mod_result_sheets WHERE day=?
                AND (({_COMPLETED_AT}) IS NULL OR override_active=1)
                ORDER BY display_order,work_order_id''', (day,)).fetchall()
        pending = []
        for row in records:
            draft = json.loads(row['draft'])
            snapshot = json.loads(row['snapshot'])
            if ((draft.get('dispo') or snapshot.get('appointment_canceled'))
                    and (selected is None or row['work_order_id'] in selected)):
                pending.append({
                    'work_order_id': row['work_order_id'],
                    'snapshot': snapshot,
                    'draft': draft,
                })
        if selected is not None and {row['work_order_id'] for row in pending} != selected:
            raise ValueError('Selected Work Orders changed or were already submitted. Refresh and try again.')
        if not pending:
            raise ValueError('No unsubmitted sheets have a disposition.')
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

    @staticmethod
    def _attempt_key(day, work_order_id):
        return 'mod_result_submission_attempt:' + day + ':' + work_order_id

    def unresolved_submission_attempts(self):
        """Outstanding dependency checks across days, including legacy history.

        Read only unknown attempts rather than loading the full daily archive.
        Source identity normalization remains the writer's responsibility.
        """
        prefix = 'mod_result_submission_attempt:'
        frozen = self.db.rows('''SELECT s.day,s.work_order_id,s.snapshot,s.draft,s.revision,
                s.override_active,d.mod_user_id,m.value
            FROM meta m
            JOIN mod_result_sheets s ON m.key=? || s.day || ':' || s.work_order_id
            JOIN mod_result_days d ON d.day=s.day
            WHERE m.key GLOB ? AND json_extract(m.value,'$.state')='uncertain' ''',
            (prefix, prefix + '*'))
        legacy = self.db.rows('''SELECT DISTINCT s.day,s.work_order_id,s.snapshot,s.draft,s.revision,
                s.override_active,d.mod_user_id
            FROM mod_result_submission_items i
            JOIN mod_result_submission_jobs j ON j.id=i.job_id
            JOIN mod_result_sheets s ON s.day=j.day AND s.work_order_id=i.work_order_id
            JOIN mod_result_days d ON d.day=s.day
            LEFT JOIN meta m ON m.key=? || s.day || ':' || s.work_order_id
            WHERE i.state='uncertain' AND m.key IS NULL
              AND NOT EXISTS (SELECT 1 FROM mod_result_submission_items newer
                JOIN mod_result_submission_jobs newer_job ON newer_job.id=newer.job_id
                WHERE newer_job.day=j.day AND newer.work_order_id=i.work_order_id
                  AND newer_job.id>j.id AND newer.state IN ('submitted','rejected'))''',
            (prefix,))
        output = []
        for row in [*frozen, *legacy]:
            attempt = json.loads(row.pop('value')) if 'value' in row else {}
            row['snapshot'] = json.loads(row['snapshot'])
            row['draft'] = json.loads(row['draft'])
            row['payload'] = attempt.get('payload')
            row['plan'] = attempt.get('plan')
            row['lead_id'] = (row['payload'] or {}).get(
                'lead_id', row['snapshot'].get('lead_source_id', ''))
            output.append(row)
        return output

    def record_submission_attempt(self, day, work_order_id, payload, plan, *, job_id=None):
        # Save before transport so a crash cannot erase what may have committed.
        self.db.set(self._attempt_key(day, work_order_id),
                    {'state': 'uncertain', 'payload': payload, 'plan': plan, 'job_id': job_id})

    def recover_submission_attempt(self, day, work_order_id, *, preserve_edits=False,
                                   expected_revision=None):
        """Record an exact remote match without discarding newer local edits."""
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            key = self._attempt_key(day, work_order_id)
            saved = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            if saved is None:
                raise ValueError('The original submission plan is unavailable.')
            attempt = json.loads(saved['value'])
            if not attempt.get('plan'):
                raise ValueError('The original submission plan is unavailable.')
            current = conn.execute('''SELECT revision FROM mod_result_sheets
                WHERE day=? AND work_order_id=?''', (day, work_order_id)).fetchone()
            if current is None:
                raise ValueError('The original MOD sheet is unavailable.')
            if expected_revision is not None and current['revision'] != expected_revision:
                # Unselected cards remain editable while another card runs.
                # Do not mistake an edit made during verification for a write.
                preserve_edits = True
            conn.execute('UPDATE meta SET value=? WHERE key=?',
                         (json.dumps(dict(attempt, state='submitted')), key))
            now = time.time()
            conn.execute('''UPDATE mod_result_sheets SET
                submitted_at=CASE WHEN submitted_at>0 THEN submitted_at ELSE ? END,
                override_active=?,submit_error='' WHERE day=? AND work_order_id=?''',
                (now, int(preserve_edits), day, work_order_id))
            conn.execute('''UPDATE mod_result_days SET submitted_at=COALESCE(submitted_at,?)
                WHERE day=?''', (now, day))
            if attempt.get('job_id') is not None:
                conn.execute('''UPDATE mod_result_submission_items SET state='submitted',error=''
                    WHERE job_id=? AND work_order_id=? AND state='uncertain' ''',
                    (attempt['job_id'], work_order_id))

    def reject_submission_attempt(self, day, work_order_id):
        key = self._attempt_key(day, work_order_id)
        attempt = self.db.get(key, None)
        if isinstance(attempt, dict):
            self.db.set(key, dict(attempt, state='rejected'))

    def submission_item(self, job_id, work_order_id, state, error=''):
        if state not in ('pending','processing','submitted','rejected',
                          'uncertain','not_submitted'):
            raise ValueError('Unknown submission state.')
        with self.db.connect() as conn:
            updated = conn.execute('''UPDATE mod_result_submission_items SET state=?,error=?
                WHERE job_id=? AND work_order_id=?''',
                (state, str(error)[:500], job_id, work_order_id))
            if updated.rowcount != 1:
                raise LookupError('Submission progress item missing.')

    def finish_submission_job(self, job_id, error=''):
        with self.db.connect() as conn:
            # A terminal batch has no work left waiting for this worker.
            # Preserve a conclusive rejection separately from an unknown write.
            conn.execute('''UPDATE mod_result_submission_items
                SET state='not_submitted',error=CASE WHEN error='' THEN ? ELSE error END
                WHERE job_id=? AND state='pending' ''',
                (str(error or 'Submission ended before this Work Order was attempted.')[:500], job_id))
            conn.execute('''UPDATE mod_result_submission_items
                SET state='uncertain',error=CASE WHEN error='' THEN ? ELSE error END
                WHERE job_id=? AND state='processing' ''',
                (str(error or 'Submission ended before its outcome was recorded.')[:500], job_id))
            incomplete = conn.execute('''SELECT 1 FROM mod_result_submission_items
                WHERE job_id=? AND state NOT IN ('submitted','pdf_only') LIMIT 1''',
                (job_id,)).fetchone()
            message = str(error or ('Some Work Orders were not submitted.' if incomplete else ''))[:500]
            conn.execute('''UPDATE mod_result_submission_jobs SET
                state=?,finished_at=?,error=? WHERE id=? AND state='running' ''',
                ('failed' if message else 'completed', time.time(), message, job_id))

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
        if job['state'] not in ('queued', 'running'):
            # Older failed batches left untouched rows marked as pending.
            # Project their terminal outcome without rewriting their history.
            for item in items:
                if item['state'] == 'pending':
                    item.update(state='not_submitted', error=item['error'] or job['error'])
        elapsed = max(0, int(time.time() - job['stage_started'])) if (
            job['state'] == 'running' and job['stage_started']) else 0
        return {**job, 'items': items, 'stage_elapsed_seconds': elapsed,
                'total': len(items),
                'submitted': sum(item['state']=='submitted' for item in items),
                'pdf_only': sum(item['state']=='pdf_only' for item in items),
                'pending': sum(item['state']=='pending' for item in items),
                'processing': sum(item['state']=='processing' for item in items),
                'rejected': sum(item['state']=='rejected' for item in items),
                'uncertain': sum(item['state']=='uncertain' for item in items),
                'not_submitted': sum(item['state']=='not_submitted' for item in items),
                'failed': sum(item['state'] in ('rejected','uncertain','not_submitted') for item in items)}

    def recent_submission_items(self, day):
        """Recent per-Work-Order statuses for the MOD notification bell.

        Submission history is already durable; no second notification store
        and no Salesforce calls are necessary. Include cross-midnight results.
        """
        return self.db.rows(f'''SELECT j.id AS job_id, j.day, j.state AS job_state,
                j.created_at, j.finished_at, j.error AS job_error,
                i.work_order_id, i.work_order_number, i.state, i.error,
                s.override_active, ({_completed_at('s.')}) IS NOT NULL AS completed
            FROM mod_result_submission_items i
            JOIN mod_result_submission_jobs j ON j.id=i.job_id
            LEFT JOIN mod_result_sheets s ON s.day=j.day AND s.work_order_id=i.work_order_id
            WHERE j.day=? OR j.created_at >= ?
            ORDER BY j.id DESC, i.position DESC LIMIT 60''',
            (day, time.time() - 2 * 86400))

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
                conn.execute('''UPDATE mod_result_submission_items
                    SET state='not_submitted',error='Worker stopped before this Work Order was submitted.'
                    WHERE job_id=? AND state='pending' ''', (job['id'],))
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
            key = self._attempt_key(day, work_order_id)
            attempt = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            if attempt:
                payload = json.loads(attempt['value'])
                conn.execute('UPDATE meta SET value=? WHERE key=?',
                             (json.dumps(dict(payload, state='submitted')), key))

    def finish_pdf_only(self, day, work_order_id, job_id):
        """Finish local documentation without writing a Salesforce receipt."""
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            updated = conn.execute('''UPDATE mod_result_sheets SET
                pdf_completed_at=?,override_active=0,submit_error=''
                WHERE day=? AND work_order_id=?
                AND json_extract(snapshot,'$.appointment_canceled')=1
                AND (pdf_completed_at IS NULL OR override_active=1)''',
                (time.time(), day, work_order_id))
            if updated.rowcount != 1:
                raise ValueError('This canceled appointment changed or is already finished for PDF.')
            if job_id is not None:
                item = conn.execute('''UPDATE mod_result_submission_items SET state='pdf_only'
                    WHERE job_id=? AND work_order_id=? AND state='pending' ''',
                    (job_id, work_order_id))
                if item.rowcount != 1:
                    raise ValueError('This canceled appointment is no longer queued.')

    def error_item(self, day, work_order_id, message):
        with self.db.connect() as conn:
            conn.execute(f'''UPDATE mod_result_sheets SET submit_error=?
                    WHERE day=? AND work_order_id=?
                    AND (({_COMPLETED_AT}) IS NULL OR override_active=1)''',
                         (str(message)[:500], day, work_order_id))

    def finish_submit(self, day):
        with self.db.connect() as conn:
            conn.execute('UPDATE mod_result_days SET submitting=0 WHERE day=?', (day,))
