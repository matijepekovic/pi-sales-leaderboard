"""Digital MOD resulting workflow. Vendor operations stay behind source/writer contracts."""
from __future__ import annotations

from datetime import datetime, time as wall_time
import time
from pathlib import Path
import os
from zoneinfo import ZoneInfo

from .contract import clean_draft, outcome_fields


class ResultingService:
    def __init__(self, repository, source, writer, settings_repository, timezone,\n                 pdf_exporter=None, output_directory=None):
        self.repository = repository
        self.source = source
        self.writer = writer
        self.settings_repository = settings_repository
        self.zone = ZoneInfo(timezone)
        self.pdf_exporter = pdf_exporter
        self.output_directory = Path(output_directory) if output_directory else None

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
            product_category=config.product_category if config else 'All',
            source_type=config.source_type if config else '',
            remove_canceled=False, remove_unconfirmed=False, limit=None,
        )
        records = tuple(self.source.records(**kwargs))
        if config and config.assigned_service_resource:
            wanted = config.assigned_service_resource.casefold()
            records = tuple(r for r in records
                            if any(n.casefold() == wanted for n in r.assigned_service_resources))
        self.repository.refresh(day, records)
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

    def users(self):
        return self.writer.mod_users()

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
        if data['primary_product'] and data['primary_product'] not in available:
            raise ValueError('Choose a product listed on the MOD sheet.')
        if data['additional_products'] and not set(data['product_results']).issubset(available):
            raise ValueError('Results must belong to a product on the MOD sheet.')
        return self.repository.save_draft(day, work_order_id, data, revision)

    @staticmethod
    def submission_payload(sheet, mod_id):
        draft = clean_draft(sheet['draft'])
        fields = outcome_fields(draft)
        if fields is None:
            raise ValueError('A disposition is required.')
        if draft['dnr'] and not draft['dnr_reason']:
            raise ValueError('Choose a DNR Reason.')
        if draft['dispo'] == 'sale' and not fields['price']['lowest']:
            raise ValueError('Sale requires a numeric price in MOD Notes.')
        available_products = [part.strip() for part in
                    sheet['snapshot']['product_interest'].split(';') if part.strip()]
        if not available_products:
            raise ValueError('Product Interest is required for resulting.')
        primary = draft['primary_product'] or available_products[0]
        if primary not in available_products:
            raise ValueError('Choose a product listed on the MOD sheet.')
        products = available_products if draft['additional_products'] else [primary]
        per_product = draft['product_results'] if draft['additional_products'] else {}
        if draft['additional_products'] and set(per_product) != set(products):
            raise ValueError('Result each selected product or uncheck additional products.')
        results = [{
            'product': product,
            'result': (per_product[product]['result'] if per_product else draft['dispo']),
            'detail': (per_product[product]['detail'] if per_product
                       else draft['result_detail']),
        } for product in products]
        if draft['dispo'] == 'nra' and not fields['work_order_status']:
            raise ValueError('The Work Order status for NRA requires verification.')
        redlines = draft['redlines'].strip()
        if draft['dnr'] and draft['dnr_reason']:
            reason = 'DNR - ' + draft['dnr_reason'].strip()
            if reason.casefold() not in redlines.casefold():
                redlines = (redlines + '\n' + reason).strip()
        return dict(
            day=sheet['day'], work_order_id=sheet['work_order_id'],
            work_order_number=sheet['snapshot']['work_order_number'],
            lead_id=sheet['snapshot'].get('lead_source_id', ''),
            mod_id=mod_id, dispo=draft['dispo'], fields=fields,
            draft=draft, product_results=results, final_redlines=redlines,
        )

    def submit(self, day):
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
            # PDF generation must succeed before Salesforce is modified.
            pdf_payload = None
            if self.pdf_exporter:
                pdf_payload = self.pdf_exporter(rows)
            for row, plan in zip(rows, plans):
                try:
                    self.writer.apply(plan)
                except Exception as exc:
                    self.repository.error_item(day, row['work_order_id'], str(exc))
                    raise
                self.repository.finish_item(day, row['work_order_id'])
                sent += 1
            if pdf_payload is not None and self.output_directory:
                directory = self.output_directory
                directory.mkdir(parents=True,exist_ok=True,mode=0o700)
                target = directory / (day + '-completed.pdf')
                temp = directory / ('.' + day + '-completed.tmp')
                with temp.open('wb') as stream:
                    os.chmod(temp,0o600)
                    stream.write(pdf_payload)
                    stream.flush()
                    os.fsync(stream.fileno())
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
