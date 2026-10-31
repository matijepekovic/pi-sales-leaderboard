"""Digital MOD resulting workflow. Vendor operations stay behind source/writer contracts."""
from __future__ import annotations

from datetime import datetime, time as wall_time
import logging
import time
from zoneinfo import ZoneInfo

from ..mod_sheet_contract import ModSheetRecord
from .contract import (
    clean_draft, final_redline_text, outcome_fields, sold_products,
    individual_product_sales, deposit_payment_text, product_result_context,
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
        date = datetime.strptime(day, '%Y-%m-%d').strftime('%-m/%-d/%Y')
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
        normalized = {key: clean_draft(value) for key, value in external.items()}
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
            data = clean_draft(sheet['draft'])
            sheet['draft'] = data
            sheet['result'] = outcome_fields(data)
            sheets.append(sheet)
        return {'day': day, 'state': state, 'sheets': sheets}

    def checkbox_fields(self):
        """Presentation-only normalized capabilities from the source adapter."""
        reader = getattr(self.writer, 'checkbox_fields', None)
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
        data = clean_draft(data)
        row = next((s for s in self.repository.sheets(day)
                    if s['work_order_id'] == work_order_id), None)
        if row is None:
            raise LookupError('This MOD sheet is not part of the selected day.')
        available = {name.strip() for name in
                     row['snapshot']['product_interest'].split(';') if name.strip()}
        if data['additional_products'] and not set(data['product_results']).issubset(available):
            raise ValueError('Separate results must belong to a product on the MOD sheet.')
        # Sale products deliberately are not limited to the original lead:
        # pivot products are validated against Salesforce's live product list
        # by the writer during End of Day preflight.
        return self.repository.save_draft(day, work_order_id, data, revision)

    @staticmethod
    def submission_payload(sheet, mod_id, *, resulted_on=None,
                           lead_appointment_date=''):
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

        context = product_result_context(
            draft, results,
            lead_appointment_date=lead_appointment_date,
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

    def _apply_batch(self, day, mod_id, rows, *, job_id=None, resulted_on=None):
        """Single Salesforce write path for direct and background submissions."""
        resulting_date = resulted_on or self.day()
        if job_id is not None:
            self.repository.submission_stage(job_id, 'Reading Lead appointment dates')
        date_reader = getattr(self.writer, 'lead_appointment_dates', None)
        leads = sorted({row['snapshot'].get('lead_source_id', '')
                        for row in rows if row['snapshot'].get('lead_source_id')})
        dates = date_reader(leads) if callable(date_reader) else {}
        if not isinstance(dates, dict):
            raise ValueError('Lead appointment date lookup returned invalid data.')
        batch = [self.submission_payload(
            dict(row, day=day), mod_id, resulted_on=resulting_date,
            lead_appointment_date=dates.get(row['snapshot'].get('lead_source_id', ''), ''),
        ) for row in rows]
        # The dashboard must explain preflight before the first Work Order.
        if job_id is not None:
            self.repository.submission_stage(
                job_id, 'Checking Salesforce records and validating the batch')
        plans = self.writer.prepare(batch)
        if len(plans) != len(rows):
            raise ValueError('Salesforce preflight produced an incomplete submission plan.')
        if job_id is not None:
            self.repository.submission_stage(job_id, 'Writing Salesforce results')
        sent = 0
        for row, plan in zip(rows, plans):
            ident = row['work_order_id']
            if job_id is not None:
                self.repository.submission_item(job_id, ident, 'processing')
            try:
                self.writer.apply(plan)
                # A local receipt is recorded only after every planned write
                # for this Work Order returns successfully.
                self.repository.finish_item(day, ident)
            except Exception as exc:
                self.repository.error_item(day, ident, str(exc))
                if job_id is not None:
                    # CLI timeout or crash can occur after a remote write.
                    # Do not report a safe failure or blindly resend.
                    self.repository.submission_item(job_id, ident, 'uncertain', str(exc))
                raise
            if job_id is not None:
                self.repository.submission_item(job_id, ident, 'submitted')
            sent += 1
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
                    job['queued_at'], self.zone).date().isoformat())
            self.repository.finish_submission_job(job['job_id'])
            return {'ok': True, **result}
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
