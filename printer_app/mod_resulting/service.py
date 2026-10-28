"""Digital MOD resulting workflow. Vendor operations stay behind source/writer contracts."""
from __future__ import annotations

from datetime import datetime, time as wall_time
from decimal import Decimal
import time
from pathlib import Path
import os
from zoneinfo import ZoneInfo

from ..mod_sheet_contract import ModSheetRecord
from .contract import (
    clean_draft, final_redline_text, outcome_fields, sold_products,
    individual_product_sales,
)


class ResultingService:
    def __init__(self, repository, source, writer, settings_repository, timezone,
                 pdf_exporter=None, output_directory=None,
                 allow_salesforce_writes=False):
        self.repository = repository
        self.source = source
        self.writer = writer
        self.settings_repository = settings_repository
        self.zone = ZoneInfo(timezone)
        self.pdf_exporter = pdf_exporter
        self.output_directory = Path(output_directory) if output_directory else None
        # Safe-by-default: the sandbox can read, edit, and review drafts on main
        # without permitting unverified writes to the live Salesforce org.
        self.allow_salesforce_writes = bool(allow_salesforce_writes)

    def day(self):
        return datetime.now(self.zone).date().isoformat()

    def refresh(self, day):
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
        normalized = {}
        for record in records:
            if record.source_id in external:
                normalized[record.source_id] = clean_draft(external[record.source_id])
        self.repository.refresh(day, records, external_drafts=normalized)
        return len(records)

    def snapshot(self, day):
        state = self.repository.day(day)
        if not state:
            self.refresh(day)
            state = self.repository.day(day)
        sheets = self.repository.sheets(day)
        for sheet in sheets:
            data = clean_draft(sheet['draft'])
            sheet['draft'] = data
            sheet['result'] = outcome_fields(data)
        return {'day': day, 'state': state, 'sheets': sheets}

    def sheet_record(self, day, work_order_id):
        # Image requests read the saved day snapshot, never Salesforce again.
        datetime.strptime(day, '%Y-%m-%d')
        data = self.repository.sheet_snapshot(day, work_order_id)
        data['assigned_service_resources'] = tuple(data.get('assigned_service_resources', ()))
        return ModSheetRecord(**data)

    def users(self):
        return self.writer.mod_users()

    def dropdowns(self):
        return self.writer.dropdowns()

    def set_mod(self, day, user_id):
        users = self.users()
        matches = [(item['id'], item['name']) for item in users if item['id'] == user_id]
        if len(matches) != 1:
            raise ValueError('Select a MOD from the Salesforce list.')
        self.repository.select_mod(day, *matches[0])
        return matches[0][1]

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
    def submission_payload(sheet, mod_id):
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
            deposit_total = (
                str(sum((Decimal(item['deposit']) for item in sales), Decimal('0')))
                if sales else ''
            )
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
            deposit_total = (
                str(sum((Decimal(item['deposit']) for item in individual_sales),
                        Decimal('0'))) if individual_sales else ''
            )

        return dict(
            day=sheet['day'], work_order_id=sheet['work_order_id'],
            work_order_number=sheet['snapshot']['work_order_number'],
            lead_id=sheet['snapshot'].get('lead_source_id', ''),
            mod_id=mod_id, dispo=draft['dispo'], fields=fields,
            draft=draft, product_results=results,
            deposit_total=deposit_total,
            final_redlines=final_redline_text(draft),
        )

    def submit(self, day):
        if not self.allow_salesforce_writes:
            raise ValueError(
                'Live Salesforce submission is disabled in the MOD sandbox '
                'until field mappings and write behavior are verified.')
        day_state = self.repository.day(day)
        if not day_state or not day_state['mod_user_id']:
            raise ValueError('Select a MOD from Salesforce first.')
        # A frozen batch is held by the repository's cross-process write lock.
        rows = self.repository.begin_submit(day)
        complete = False
        sent = 0
        try:
            if not rows:
                raise ValueError('No unsubmitted sheets have a disposition.')
            batch = [self.submission_payload(dict(row, day=day),
                                              day_state['mod_user_id'])
                     for row in rows]
            # Preflight ALL Salesforce object/field mappings before a single write.
            plans = self.writer.prepare(batch)
            if len(plans) != len(rows):
                raise ValueError('Salesforce preflight produced an incomplete submission plan.')
            # Prepare and fsync the PDF before changing any Salesforce records.
            # If writing the PDF fails, Salesforce is never modified.
            pdf_payload = self.pdf_exporter(rows) if self.pdf_exporter else None
            target = temp = None
            if pdf_payload is not None and self.output_directory:
                directory = self.output_directory
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = directory / (day + '-completed.pdf')
                temp = directory / ('.' + day + '-completed.tmp')
                with temp.open('wb') as stream:
                    os.chmod(temp, 0o600)
                    stream.write(pdf_payload)
                    stream.flush()
                    os.fsync(stream.fileno())
            for row, plan in zip(rows, plans):
                try:
                    self.writer.apply(plan)
                except Exception as exc:
                    self.repository.error_item(day, row['work_order_id'], str(exc))
                    raise
                self.repository.finish_item(day, row['work_order_id'])
                sent += 1
            if target is not None:
                temp.replace(target)
            complete = True
            return {'submitted': sent, 'day': day, 'pdf': bool(pdf_payload)}
        finally:
            self.repository.finish_submit(day, complete)


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
        target = local.replace(hour=8, minute=0, second=0, microsecond=0).timestamp()
        if state and (state['submitting'] or state['submitted_at'] or
                      state['refreshed_at'] >= target):
            return False
        last = self.service.repository.auto_attempt(day)
        return float(last.get('at') or 0) + 600 <= stamp

    def run_due(self, stamp=None):
        stamp = time.time() if stamp is None else float(stamp)
        day = datetime.fromtimestamp(stamp,self.service.zone).date().isoformat()
        self.service.repository.record_auto_attempt(day,stamp)
        try:
            return {'ok':True,'count':self.service.refresh(day)}
        except Exception as exc:
            self.service.repository.record_auto_attempt(day,stamp,str(exc))
            return {'ok':False,'error':str(exc)[:250]}
