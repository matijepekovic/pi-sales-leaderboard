"""Digital MOD resulting workflow. Vendor operations stay behind source/writer contracts."""
from __future__ import annotations

from datetime import datetime, time as wall_time
import logging
import time
from zoneinfo import ZoneInfo

from ..mod_sheet_contract import ModSheetRecord
from .contract import (
    ResultingWriteRejected,
    source_draft,
    clean_draft, final_redline_text, outcome_fields, sold_products,
    individual_product_sales, deposit_payment_text, product_result_context,
    user_redline_text,
)


class ResultingService:
    def __init__(self, repository, source, writer, settings_repository, timezone,
                 pdf_exporter=None, allow_salesforce_writes=False):
        self.repository = repository
        self.source = source
        self.writer = writer
        self.settings_repository = settings_repository
        self.zone = ZoneInfo(timezone)
        self.pdf_exporter = pdf_exporter
        # Safe-by-default: the sandbox can read, edit, and review drafts on main
        # without permitting unverified writes to the live Salesforce org.
        self.allow_salesforce_writes = bool(allow_salesforce_writes)

    def day(self):
        return datetime.now(self.zone).date().isoformat()

    def refresh(self, day, *, clear_local=False, initial_only=False):
        # The same normalized records and market settings used by Printer;
        # canceled/unconfirmed results are included for live routing changes.
        config = self.settings_repository.settings()
        selected = datetime.strptime(day, '%Y-%m-%d')
        date = f'{selected.month}/{selected.day}/{selected.year}'
        kwargs = dict(
            start_date=date, end_date=date,
            market_segment=config.market_segment if config else '',
            # The sandbox lists every lead in the selected MOD market, not
            # a subset filtered to one product, source, or assigned rep.
            product_category='All', source_type='',
            remove_canceled=False, remove_unconfirmed=False, limit=None,
        )
        records = tuple(self.source.records(**kwargs))
        # Salesforce's read-only resulting projection is a separate adapter
        # operation. Fetch it completely before modifying local SQLite;
        # failures never replace existing snapshots or pending work.
        reader = getattr(self.writer, 'read_results', None)
        external = reader(records) if callable(reader) else {}
        if not isinstance(external, dict):
            raise ValueError('Salesforce resulting refresh returned invalid records.')
        # A partial remote response must never become blank local data.
        if callable(reader) and set(external) != {record.source_id for record in records}:
            raise ValueError('Salesforce resulting refresh returned incomplete records.')
        normalized = {key: source_draft(value) for key, value in external.items()}
        if clear_local and not callable(reader):
            normalized = {record.source_id: clean_draft({}) for record in records}
        applied = self.repository.refresh(
            day, records, external_drafts=normalized,
            market_segment=kwargs['market_segment'],
            clear_local=clear_local, initial_only=initial_only,
        )
        return len(records) if applied is not False else 0

    def clear_local(self, day):
        """Discard local drafts and restore verified Salesforce values.

        This performs read-only Salesforce queries; it never calls the writer
        or touches real End-of-Day submission receipts.
        """
        return self.refresh(day, clear_local=True)

    def snapshot(self, day):
        state = self.repository.day(day)
        if not state:
            self.refresh(day)
            state = self.repository.day(day)
        sheets = []
        for sheet in self.repository.sheets(day):
            data = source_draft(sheet['draft'])
            sheet['draft'] = data
            sheet['result'] = outcome_fields(data)
            sheets.append(sheet)
        return {'day': day, 'state': state, 'sheets': sheets}

    def checkbox_fields(self):
        """Presentation-only normalized capabilities from the source adapter."""
        reader = getattr(self.writer, 'checkbox_fields', None)
        return reader() if callable(reader) else {}

    def note_field(self):
        """Normalized source capabilities for the existing Notes editor."""
        reader = getattr(self.writer, 'note_field', None)
        return reader() if callable(reader) else {}

    def sheet_record(self, day, work_order_id):
        # Image requests read the saved day snapshot, never Salesforce again.
        datetime.strptime(day, '%Y-%m-%d')
        data = self.repository.sheet_snapshot(day, work_order_id)
        data['assigned_service_resources'] = tuple(data.get('assigned_service_resources', ()))
        return ModSheetRecord(**data)

    def users(self, day=None):
        day = day or self.day()
        market = self.repository.imported_market(day)
        if not market:
            # Never refresh existing work implicitly just to populate Select
            # MOD: only the explicit Refresh button may reconcile remote data.
            raise ValueError(
                'Imported MOD sheets have no market. Press Refresh to load the '
                'Salesforce market before selecting a MOD.')
        return self.writer.mod_users(market)

    def dropdowns(self):
        return self.writer.dropdowns()

    def set_mod(self, day, user_id):
        users = self.users(day)
        matches = [(item['id'], item['name']) for item in users if item['id'] == user_id]
        if len(matches) != 1:
            raise ValueError('Select a MOD from the Salesforce list.')
        self.repository.select_mod(day, *matches[0])
        return matches[0][1]

    def override(self, day, work_order_id, revision):
        """Unlock an explicitly selected completed sheet; never write yet."""
        return self.repository.override(day, work_order_id, revision)

    def save(self, day, work_order_id, data, revision):
        # Saving an editable sheet cannot revalidate untouched Salesforce
        # values or discard source records absent from the visible controls.
        data = source_draft(data)
        row = next((s for s in self.repository.sheets(day)
                    if s['work_order_id'] == work_order_id), None)
        if row is None:
            raise LookupError('This MOD sheet is not part of the selected day.')
        # Only actual Stats editor fields may be changed by a browser post.
        # Preserve every source-owned field from the stored Salesforce read,
        # including identities that the current editor cannot represent.
        editor_fields = set(clean_draft({}))
        data = {key: value for key, value in data.items() if key in editor_fields}
        data.update({
            key: value for key, value in row['draft'].items()
            if key not in editor_fields
        })
        # A Sale does not expose individual Product Results for editing.
        # Neither does a sheet with one product or individual mode disabled.
        # Preserve the stored Salesforce outcomes in those modes, regardless
        # of whether an older browser sent an empty product_results object.
        # Only the individual-result editor may replace its visible entries.
        visible_products = {
            part.strip() for part in
            row['snapshot'].get('product_interest', '').split(';')
            if part.strip()
        }
        source_results = row['draft'].get('product_results') or {}
        if (data['dispo'] == 'sale' or not data['additional_products']
                or len(visible_products) < 2):
            data['product_results'] = dict(source_results)
        else:
            # Product Interest is the sheet's starting selection, not a limit
            # on Salesforce results. Entries absent from the editor are always
            # preserved; explicitly changed visible entries still take effect.
            edited_results = dict(data.get('product_results') or {})
            for product, info in source_results.items():
                if product not in visible_products and product not in edited_results:
                    edited_results[product] = info
            data['product_results'] = edited_results
        # The Salesforce writer owns validation of deliberately submitted
        # selections against actual org metadata, not the imported snapshot.
        return self.repository.save_draft(day, work_order_id, data, revision)

    @staticmethod
    def _saved_appointment_date(snapshot):
        """Read the selected Service Appointment date when available.

        Saved dates supply the fallback for Product Interest Results. Missing
        legacy snapshot dates must not block valid Salesforce Lead date paths.
        """
        sources = (
            (snapshot.get('scheduled_start'),
             ('%Y.%m.%d ; %I:%M:%S %p',)),
            (snapshot.get('local_scheduled_start_time'),
             ('%b %d %Y %I:%M %p', '%b %d, %Y %I:%M %p',
              '%m/%d/%Y %I:%M %p', '%Y-%m-%d %I:%M %p')),
        )
        for raw, formats in sources:
            if not isinstance(raw, str) or not raw.strip():
                continue
            for fmt in formats:
                try:
                    return datetime.strptime(raw.strip(), fmt).date().isoformat()
                except ValueError:
                    continue
        return ''

    @staticmethod
    def submission_payload(sheet, mod_id, *, resulted_on=None,
                           lead_appointment_date='', work_order_appointment_date=''):
        draft = clean_draft(sheet['draft'])
        fields = outcome_fields(draft)
        if fields is None:
            raise ValueError('A disposition is required.')
        if draft['dnr'] and not draft['dnr_reason']:
            raise ValueError('Choose at least one DNR Reason.')

        original_products = [
            part.strip() for part in
            sheet['snapshot'].get('product_interest', '').split(';')
            if part.strip()
        ]
        if draft['dispo'] == 'sale':
            sales = sold_products(draft)
            # Price zero is not a sale. Never invent a required minimum count
            # of sold products or create product records from zero-price rows.
            results = [{
                'product': item['product'],
                'result': 'sale',
                'detail': draft['result_detail'],
                'price': item['price'],
                'deposit': item['deposit'],
            } for item in sales]
        else:
            if not original_products:
                raise ValueError('Product Interest is required for resulting.')
            overrides = draft['product_results'] if draft['additional_products'] else {}
            # An individual result overrides only that product. All others
            # retain the default main Dispo/result.
            results = []
            for product in original_products:
                chosen = overrides.get(product)
                if chosen and chosen['result'] == 'sale':
                    # Price 0 means not sold; keep the product result blank.
                    priced_sale = next(
                        (item for item in individual_product_sales(draft)
                         if item['product'] == product), None
                    )
                    if priced_sale is None:
                        continue
                    results.append({
                        'product': product, 'result': 'sale',
                        'detail': chosen['detail'],
                        'price': priced_sale['price'],
                        'deposit': priced_sale['deposit'],
                    })
                else:
                    results.append({
                        'product': product,
                        'result': chosen['result'] if chosen else draft['dispo'],
                        'detail': chosen['detail'] if chosen else draft['result_detail'],
                        'price': '',
                        'deposit': '',
                    })
            individual_sales = individual_product_sales(draft)

        manual_redline = user_redline_text(draft)
        if manual_redline and not results:
            raise ValueError(
                'The manual redline needs a resulted product for its comment. '
                'Your draft is saved; choose a product result before submitting.')
        if manual_redline:
            # The red-pen editor belongs to the whole card, like its default
            # result detail. Only products actually being resulted receive it.
            for result in results:
                result['comment'] = manual_redline

        context = product_result_context(
            draft, results,
            lead_appointment_date=lead_appointment_date,
            work_order_appointment_date=work_order_appointment_date,
            resulted_on=resulted_on or sheet['day'],
            work_type=sheet['snapshot'].get('work_type', ''),
        )

        return dict(
            day=sheet['day'], work_order_id=sheet['work_order_id'],
            work_order_number=sheet['snapshot']['work_order_number'],
            lead_id=sheet['snapshot'].get('lead_source_id', ''),
            mod_id=mod_id, dispo=draft['dispo'], fields=fields,
            draft=draft, product_results=results,
            product_result_context=context,
            deposit_payment=deposit_payment_text(draft),
            final_redlines=final_redline_text(draft),
        )

    def export_all_pdf(self, day):
        """On-demand print of every currently imported card, regardless of outcome."""
        if self.pdf_exporter is None:
            raise ValueError('MOD PDF renderer is not configured.')
        sheets = self.repository.print_sheets(day)
        if not sheets:
            raise LookupError('There are no MOD sheets to print for this day.')
        return self.pdf_exporter(sheets)

    def _apply_batch(self, day, mod_id, rows, *, job_id=None, resulted_on=None,
                     raise_on_error=True):
        """Single Salesforce write path for direct and background submissions."""
        resulting_date = resulted_on or self.day()
        if job_id is not None:
            self.repository.submission_stage(job_id, 'Checking saved MOD appointment dates')
        # Prefer Salesforce's Lead dates for the Flow date branches. An
        # unavailable lookup is not a new submission gate: the normalized
        # contract can fall back to the saved Service Appointment date.
        lead_ids = [row['snapshot']['lead_source_id'] for row in rows]
        reader = getattr(self.writer, 'lead_appointment_dates', None)
        lead_dates = {}
        if callable(reader):
            try:
                lead_dates = reader(lead_ids)
            except RuntimeError:
                logging.getLogger(__name__).warning(
                    'MOD Lead appointment date lookup failed; using saved dates.')
        if not isinstance(lead_dates, dict):
            lead_dates = {}
        # Plans sharing a Lead depend on one another's history and product
        # interests. Keep that dependency inside one preflight group while
        # allowing unrelated Leads to complete after a confirmed rejection.
        groups, row_groups, plans, payloads, failures = {}, {}, {}, {}, []
        confirmed = set()
        sent = 0
        counts = {'rejected': 0, 'uncertain': 0, 'not_submitted': 0}

        def record_failure(row, state, message):
            ident = row['work_order_id']
            self.repository.error_item(day, ident, message)
            if job_id is not None:
                self.repository.submission_item(job_id, ident, state, message)
            counts[state] += 1

        group_key = getattr(self.writer, 'submission_group_key', None)
        for row in rows:
            ident = row['work_order_id']
            identity = {'work_order_id': ident,
                        'lead_id': row['snapshot'].get('lead_source_id', '')}
            try:
                key = group_key(identity) if callable(group_key) else identity['lead_id']
                key = ('lead', key) if key else ('work_order', ident)
                hash(key)
            except Exception as exc:
                failures.append(exc)
                record_failure(row, 'rejected', str(exc))
                continue
            row_groups[ident] = key
            group = groups.setdefault(key, {'rows': [], 'error': None, 'verifying': None})
            group['rows'].append(row)
            try:
                payload = self.submission_payload(
                    dict(row, day=day), mod_id, resulted_on=resulting_date,
                    lead_appointment_date=lead_dates.get(identity['lead_id'], '') or '',
                    work_order_appointment_date=self._saved_appointment_date(row['snapshot']),
                )
                payloads[ident] = payload
            except Exception as exc:
                group['error'] = group['error'] or exc

        # Finish every group's read-only validation before the first write.
        if job_id is not None:
            self.repository.submission_stage(
                job_id, 'Checking Salesforce records and validating the batch')
        # Selecting a different Work Order must not bypass an unknown write
        # against the same Lead, including attempts from an earlier day.
        for group in groups.values():
            group['attempts'] = []
        for attempt in self.repository.unresolved_submission_attempts():
            identity = {'work_order_id': attempt['work_order_id'], 'lead_id': attempt['lead_id']}
            source_key = group_key(identity) if callable(group_key) else identity['lead_id']
            source_key = ('lead', source_key) if source_key else ('work_order', identity['work_order_id'])
            targets = {source_key, row_groups.get(attempt['work_order_id'])}
            for key in targets:
                if key in groups:
                    groups[key]['attempts'].append(attempt)
        bulk_prepared = False
        if len(payloads) == len(rows) and all(
                group['error'] is None and not group['attempts'] for group in groups.values()):
            try:
                prepared = self.writer.prepare([payloads[row['work_order_id']] for row in rows])
                if len(prepared) != len(rows):
                    raise ValueError('Salesforce preflight produced an incomplete submission plan.')
                plans.update((row['work_order_id'], plan) for row, plan in zip(rows, prepared))
                bulk_prepared = True
            except Exception:
                # No writes occur during preflight. Isolate a rejected group
                # below without making every normal batch fetch one Lead at a time.
                plans.clear()
        verified_attempts = set()
        for group in groups.values():
            if bulk_prepared:
                continue
            if group['error'] is None:
                try:
                    for attempt in group['attempts']:
                        ident = attempt['work_order_id']
                        token = (attempt['day'], ident)
                        if token in verified_attempts:
                            continue
                        group['verifying'] = ident
                        prior = attempt['payload'] or self.submission_payload(
                            attempt, attempt['mod_user_id'], resulted_on=attempt['day'],
                            work_order_appointment_date=self._saved_appointment_date(attempt['snapshot']))
                        verifier = getattr(self.writer, 'reconcile_submission', None)
                        if not callable(verifier):
                            raise ValueError('Verify the previous Work Order submission before retrying.')
                        verified = verifier(prior, verification=attempt['plan'])
                        if verified not in ('submitted', 'ready'):
                            raise ValueError('The previous Work Order submission could not be verified.')
                        if verified == 'submitted':
                            if not attempt['plan']:
                                raise ValueError('The original submission plan is required to recover a receipt.')
                            selected_here = attempt['day'] == day and ident in payloads
                            same_desired = selected_here and prior == payloads[ident]
                            preserve = (not same_desired and (
                                selected_here or bool(attempt['override_active'])
                                or prior.get('draft') != attempt['draft']))
                            self.repository.recover_submission_attempt(
                                attempt['day'], ident, preserve_edits=preserve,
                                expected_revision=attempt['revision'])
                            if same_desired:
                                if job_id is not None:
                                    self.repository.submission_item(job_id, ident, 'submitted')
                                confirmed.add(ident)
                                sent += 1
                        verified_attempts.add(token)
                        group['verifying'] = None
                    remaining = [row for row in group['rows']
                                 if row['work_order_id'] not in confirmed]
                    group['rows'] = remaining
                    prepared = self.writer.prepare([payloads[row['work_order_id']]
                                                    for row in remaining]) if remaining else []
                    if len(prepared) != len(group['rows']):
                        raise ValueError('Salesforce preflight produced an incomplete submission plan.')
                    group_plans = {row['work_order_id']: plan
                                   for row, plan in zip(group['rows'], prepared)}
                    plans.update(group_plans)
                except Exception as exc:
                    group['error'] = exc
            if group['error'] is not None:
                failures.append(group['error'])
                message = 'Group preflight rejected; no writes performed: ' + str(group['error'])
                for row in group['rows']:
                    ident = row['work_order_id']
                    if ident in confirmed:
                        continue
                    if group['verifying']:
                        state = 'uncertain' if ident == group['verifying'] else 'not_submitted'
                        detail = ('Previous submission still needs verification: '
                                  if state == 'uncertain' else
                                  'Not submitted because this Lead has an unverified earlier submission: ')
                        record_failure(row, state, detail + str(group['error']))
                    else:
                        record_failure(row, 'rejected', message)
        if job_id is not None:
            self.repository.submission_stage(job_id, 'Writing Salesforce results')
        blocked_groups, stopped = set(), False
        for row in rows:
            ident = row['work_order_id']
            if ident not in plans:
                continue
            key = row_groups[ident]
            if stopped or key in blocked_groups:
                message = ('Not submitted because an earlier write needs verification.'
                           if stopped else
                           'Not submitted because an earlier Work Order for this Lead was rejected.')
                record_failure(row, 'not_submitted', message)
                continue
            if job_id is not None:
                self.repository.submission_item(job_id, ident, 'processing')
            try:
                plan = plans[ident]
                self.repository.record_submission_attempt(day, ident, payloads[ident], plan,
                                                          job_id=job_id)
                self.writer.apply(plan)
                # A local receipt is recorded only after every planned write
                # for this Work Order returns successfully.
                self.repository.finish_item(day, ident)
            except Exception as exc:
                failures.append(exc)
                if isinstance(exc, ResultingWriteRejected):
                    self.repository.reject_submission_attempt(day, ident)
                    record_failure(row, 'rejected', str(exc))
                    blocked_groups.add(key)
                else:
                    # A transport failure or lost local receipt can follow a
                    # committed remote write. Stop without replaying anything.
                    record_failure(row, 'uncertain', str(exc))
                    stopped = True
                continue
            if job_id is not None:
                self.repository.submission_item(job_id, ident, 'submitted')
            sent += 1
        if failures:
            if raise_on_error:
                raise failures[0]
            return {'submitted': sent, 'day': day, **counts,
                    'error': str(failures[0])[:500]}
        return {'submitted': sent, 'day': day}

    def submit(self, day, work_order_ids=None):
        """Synchronous workflow contract retained for callers and tests."""
        if not self.allow_salesforce_writes:
            raise ValueError(
                'Live Salesforce submission is disabled in the MOD sandbox '
                'until field mappings and write behavior are verified.')
        day_state = self.repository.day(day)
        if not day_state or not day_state['mod_user_id']:
            raise ValueError('Select a MOD from Salesforce first.')
        rows = self.repository.begin_submit(day, work_order_ids)
        try:
            return self._apply_batch(day, day_state['mod_user_id'], rows)
        finally:
            self.repository.finish_submit(day)

    def enqueue(self, day, work_order_ids=None):
        """Browser request only reserves the batch; never calls Salesforce."""
        if not self.allow_salesforce_writes:
            raise ValueError(
                'Live Salesforce submission is disabled in the MOD sandbox '
                'until field mappings and write behavior are verified.')
        return self.repository.enqueue_submit(day, work_order_ids)

    def process_next_submission(self):
        """Worker executes one queued job, independently of browser connections."""
        if not self.allow_salesforce_writes:
            return None
        job = self.repository.claim_submission()
        if job is None:
            return None
        try:
            result = self._apply_batch(
                job['day'], job['mod_id'], job['rows'], job_id=job['job_id'],
                resulted_on=datetime.fromtimestamp(
                    job['queued_at'], self.zone).date().isoformat(),
                raise_on_error=False)
            self.repository.finish_submission_job(job['job_id'], result.get('error', ''))
            return {'ok': not bool(result.get('error')), **result}
        except Exception as exc:
            self.repository.finish_submission_job(job['job_id'], str(exc))
            return {'ok': False, 'day': job['day'], 'error': str(exc)[:500]}
        finally:
            self.repository.finish_submit(job['day'])



class ResultingDailyPull:
    """Single 8 AM snapshot with a 10-minute failure backoff; never touches printing."""

    def __init__(self, service):
        self.service = service

    def due(self, stamp):
        local = datetime.fromtimestamp(stamp, self.service.zone)
        if local.time() < wall_time(8, 0):
            return False
        day = local.date().isoformat()
        state = self.service.repository.day(day)
        # The 8 AM pull is initial-only; existing drafts cannot be replaced
        # by background work. Explicit Refresh is the only reconciliation.
        if state and (state['submitting'] or state['submitted_at'] or
                      state['refreshed_at'] > 0 or
                      self.service.repository.sheets(day)):
            return False
        last = self.service.repository.auto_attempt(day)
        return float(last.get('at') or 0) + 600 <= stamp

    def run_due(self, stamp=None):
        stamp = time.time() if stamp is None else float(stamp)
        day = datetime.fromtimestamp(stamp,self.service.zone).date().isoformat()
        self.service.repository.record_auto_attempt(day,stamp)
        try:
            count = self.service.refresh(day, initial_only=True)
            if count:
                prepare = getattr(self.service.writer, 'prepare_metadata', None)
                if callable(prepare):
                    try:
                        prepare()
                    except Exception:
                        # Warming a cache is optional, never reason to discard
                        # a verified morning MOD import. EOD revalidates.
                        logging.getLogger(__name__).warning(
                            'MOD write metadata prewarm unavailable; preflight will retry')
            return {'ok':True,'count':count}
        except Exception as exc:
            self.service.repository.record_auto_attempt(day,stamp,str(exc))
            return {'ok':False,'error':str(exc)[:250]}
