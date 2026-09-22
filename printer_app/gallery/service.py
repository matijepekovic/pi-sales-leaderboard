"""Gallery workflows through explicit file/repository boundaries; no print actions."""
from dataclasses import asdict, is_dataclass
import hashlib
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .policy import (
    address_key, authoritative_reference_text, checked_date, checked_date_filter,
    checked_lead_name, checked_work_order_number, lead_key, printed_address, printed_lead, printed_work_order_number,
    printed_phone, related_identity, search_expression, usable_phone, work_order_key,
)

log = logging.getLogger(__name__)


class GalleryService:
    def __init__(self, repository, files):
        self.repository, self.files = repository, files
        self.initialized = False

    def initialize(self):
        if not self.initialized:
            self.files.initialize()
            self.repository.initialize()
            self.initialized = True

    def offer(self, filename, payload, options):
        self.initialize()
        ident = hashlib.sha256(payload).hexdigest()
        with self.files.lock():
            if not self.repository.imported(ident):
                self.files.stage(ident, payload, options.max_mb)
                self.repository.enqueue(ident, filename)
        return ident

    def offer_morning(self, day, filename, payload, options):
        """Stage the already-rendered morning PDF through the existing card worker."""
        self.initialize()
        day = checked_date(day)
        ident = hashlib.sha256(b'morning:' + day.encode() + b':' + payload).hexdigest()
        with self.files.lock():
            if not self.repository.imported(ident):
                self.files.stage(ident, payload, options.max_mb)
                self.repository.enqueue(ident, filename, origin='morning', reference_day=day)
        return ident

    def search(self, query, offset, document_date='', *, field=None):
        self.initialize()
        return self.repository.list_items(search_expression(query, field), max(0, min(offset, 1000000)),
                                          document_date=checked_date_filter(document_date))

    def offline_index(self):
        """Normalized active-card index; image bytes remain behind the image endpoint."""
        self.initialize()
        return dict(items=self.repository.offline_items(), generated=time.time())

    def _identity_matches(self, item):
        if not item.get('lead_name') and not item.get('address'):
            raise ValueError('Neither the lead name nor address could be read on this card.')
        return [
            row for row in self.repository.related_candidates()
            if related_identity(
                item.get('lead_name', ''), item.get('address', ''),
                row.get('lead_name', ''), row.get('address', ''),
            )
        ]

    @staticmethod
    def _public_related_row(row):
        return {key: row[key] for key in (
            'id','filename','page','part','document_date','date_status','bytes',
            'lead_name','lead_status','address','work_order_number',
            'assigned_service_resource','sales_lead_status','notes_count','origin','image_revision','search_revision'
        )}

    def related(self, ident, offset=0, document_date=''):
        self.initialize()
        item = self.repository.item(ident)
        if not item:
            raise LookupError('This image has expired or is unavailable.')
        rows = self._identity_matches(item)
        buckets = {}
        for row in rows:
            key = row['document_date']
            buckets[key] = buckets.get(key, 0) + 1
        dates = [dict(date=value, count=buckets[value])
                 for value in sorted((key for key in buckets if key), reverse=True)]
        if None in buckets:
            dates.append(dict(date=None, count=buckets[None]))

        date_filter = checked_date_filter(document_date)
        if date_filter == 'undated':
            rows = [row for row in rows if not row['document_date']]
        elif date_filter:
            rows = [row for row in rows if row['document_date'] == date_filter]

        start = max(0, min(offset, 1000000))
        page = rows[start:start + 24]
        return dict(
            total=len(rows),
            items=[self._public_related_row(row) for row in page],
            dates=dates,
            lead_name=item.get('lead_name', ''),
            address=item.get('address', ''),
            selected_id=ident,
        )

    @staticmethod
    def _checked_lead(value):
        name = checked_lead_name(value)
        if not name or not any(c.isalpha() for c in name):
            raise ValueError('Enter the lead name printed on this card.')
        return name

    def lead(self, ident, value):
        self.initialize()
        name = self._checked_lead(value)
        item = self.repository.item(ident)
        if not item:
            raise LookupError('This image has expired or is unavailable.')
        # An unnamed active card has no confirmed name identity yet. Its first
        # correction is intentionally local; later edits can use related identity.
        if not item.get('lead_name'):
            return dict(updated=self.repository.rename_one_active_lead(
                ident, name, lead_key(name)
            ), scope='single')
        matches = self._identity_matches(item)
        return dict(
            updated=self.repository.rename_leads(
                [row['id'] for row in matches], name, lead_key(name)
            ),
            scope='related',
        )

    def import_item_lead(self, import_id, item_id, value):
        """Admin correction for one retained generated card, including REVIEW."""
        self.initialize()
        name = self._checked_lead(value)
        result = self.repository.correct_import_item_lead(
            import_id, item_id, name, lead_key(name)
        )
        return dict(result, lead_name=name)

    @staticmethod
    def _checked_work_order(value):
        return checked_work_order_number(value)

    def work_order(self, ident, value):
        self.initialize()
        number = self._checked_work_order(value)
        self.repository.correct_work_order(ident, number)
        self._enrich_reference_item(ident)
        return dict(work_order_number=number)

    def import_item_work_order(self, import_id, item_id, value):
        """Admin correction for one retained generated card, including REVIEW."""
        self.initialize()
        number = self._checked_work_order(value)
        result = self.repository.correct_import_item_work_order(import_id, item_id, number)
        self._enrich_reference_item(item_id)
        return dict(result, work_order_number=number)

    def item(self, ident):
        self.initialize()
        item = self.repository.item(ident)
        if item:
            kind, reference = self._reference_for(item.get('document_date'), item.get('work_order_number'))
            if reference is not None and str(reference.get('phone') or '').strip():
                phone, dial = usable_phone(reference['phone'])
            elif kind and reference is None:
                phone, dial = '', ''  # Ambiguous references must not select a contact.
            else:
                phone, dial = printed_phone(item.get('text'))
            item.update(phone=phone, phone_dial=dial)
        return item

    def note(self, ident, note_id, author, body):
        self.initialize()
        if not body.strip() or len(body) > 2000 or len(author) > 80 or len(note_id) != 32:
            raise ValueError('Enter a note up to 2,000 characters and a name up to 80 characters.')
        int(note_id, 16)
        self.repository.add_note(ident, note_id, author.strip() or 'Anonymous', body.strip())

    def date(self, ident, value):
        self.initialize()
        self.repository.correct_date(ident, checked_date(value))
        self._enrich_reference_item(ident)

    def summary(self, options):
        self.initialize()
        result = self.repository.overview()
        usage = self.files.usage()
        first = result.get('first_import') or time.time()
        observed_days = min(7, max(1, (time.time() - first) / 86400))
        daily = options.crops_per_day or result['recent_crops'] / observed_days
        result.update(storage=usage, keep_days=options.days, limit_bytes=options.max_mb * 1048576,
            estimated_daily=round(daily, 1), estimate_source='entered daily count' if options.crops_per_day else 'observed imports (up to 7 days)',
            projected_image_bytes=int(result['average_bytes'] * daily * options.days))
        return result

    def expire(self, days, timezone):
        self.initialize()
        today = datetime.now(ZoneInfo(timezone)).date()
        self._remove_morning_cards()  # Finish any interrupted scan reconciliation.
        cutoff = (today - timedelta(days=days)).isoformat()
        for ident in self.repository.expiring(cutoff):
            self.files.remove('crops', ident)
            self.repository.forget(ident)
        self.repository.housekeeping(time.time() - days * 86400)

    def clear_temporary(self):
        self.initialize()
        with self.files.lock():
            self.files.prune_partials(time.time() - 3600)
            for category, ident, modified in self.files.temporary_entries():
                state = self.repository.import_state(ident)
                if state in ('COMPLETE', 'ERROR') or (state is None and modified < time.time() - 3600):
                    self.files.remove(category, ident)

    def publish(self, job, manifest, directory):
        items = {}
        identities = {}
        origin = job.get('origin', 'scan')
        for entry in manifest['items']:
            revision = hashlib.sha256(f"{job['id']}:{entry['page']}:{entry['part']}".encode()).hexdigest()
            day = job.get('reference_day') if origin == 'morning' else entry['document_date']
            number = printed_work_order_number(entry['text'])
            _, reference = self._reference_for(day, number)
            if reference and not day:
                day = reference.get('day') or day
            if origin == 'morning' and day and self.repository.scans_received(day):
                continue
            key = (day, work_order_key(number))
            existing = self.repository.card_for_work_order(day, number)
            if origin == 'morning' and existing:
                continue
            ident = existing['id'] if existing else identities.get(key, revision) if all(key) else revision
            if all(key):
                identities[key] = ident
            text = entry['text']
            lead_text = entry.get('lead_text', '')
            previous = self.repository.reference_item(ident) if existing else None
            if previous and previous.get('reference_kind'):
                text = authoritative_reference_text(text, previous['lead_name'], previous['address'],
                                                    previous['assigned_service_resource'])
                if previous['lead_name']:
                    lead_text = 'Lead Name: ' + previous['lead_name']
            if reference:
                # Typed identity comes from the normalized source; the image is the scan.
                text = self._reference_text(text, reference, day, include_resources=False)
                if reference.get('lead_name'):
                    lead_text = 'Lead Name: ' + reference['lead_name']
            self.files.publish(directory / entry['file'], ident)
            items[ident] = dict(id=ident, import_id=job['id'], filename=job['filename'],
                page=entry['page'], part=entry['part'], bytes=entry['bytes'], text=text,
                document_date=day, date_status='reference' if origin == 'morning' else entry['date_status'], created=time.time(),
                lead_text=lead_text,
                work_order_candidates=tuple(entry.get('work_order_candidates') or ()),
                recognition_revision=1 if (entry.get('work_order_candidates') or
                    ('lead_text' in entry and entry['text'].strip())) else 0,
                origin=origin, image_revision=revision, replace_existing=bool(existing), require_identity=True)
        warnings = manifest.get('warnings', [])
        if manifest.get('skipped'):
            warnings.append('No recognized form boxes on pages: ' + ', '.join(map(str, manifest['skipped'])))
        self.repository.finish(job['id'], list(items.values()), '; '.join(warnings))
        self._remove_morning_cards()
        # Reference enrichment is optional. With no matching reference snapshot,
        # these calls are no-ops and Gallery behaves exactly as before.
        lookup_numbers = []
        for item in items.values():
            self._enrich_reference_item(item['id'])
            lookup_numbers.extend(item.get('work_order_candidates') or ())
            number = printed_work_order_number(item.get('text', ''))
            if number:
                lookup_numbers.append(number)
        self.files.remove('spool', job['id'])
        self.files.remove('work', job['id'])
        return tuple(dict.fromkeys(lookup_numbers))

    @staticmethod
    def _reference_record(record):
        if is_dataclass(record):
            return asdict(record)
        if isinstance(record, dict):
            return dict(record)
        raise ValueError('Reference records must use the normalized MOD contract.')

    @staticmethod
    def _match_reference(item, references):
        """Only one exact work-order match in the card's day can enrich it."""
        work = work_order_key(item.get('work_order_number', ''))
        if not work:
            return None
        matches = [row for row in references if row.get('work_order_key') == work]
        return matches[0] if len(matches) == 1 else None

    def _reference_for(self, day, number):
        if not work_order_key(number):
            return '', None
        for kind in ('final', 'morning'):
            references = self.repository.reference_matches(day, kind, number)
            match = self._match_reference({'work_order_number': number}, references)
            if match is not None:
                if kind == 'final':
                    match_day = match.get('day') or day
                    morning = self.repository.reference_matches(match_day, 'morning', number)
                    initial = self._match_reference({'work_order_number': number}, morning)
                    if initial:
                        match = dict(match)
                        for field in ('lead_name', 'address', 'phone', 'product_interest', 'work_type',
                                      'source', 'sub_source', 'set_by', 'canvass_set_by', 'lead_description',
                                      'local_scheduled_start_time', 'scheduled_start'):
                            if not str(match.get(field) or '').strip():
                                match[field] = initial.get(field, '')
                return kind, match
            if any(row.get('work_order_key') == work_order_key(number) for row in references):
                return kind, None  # Preserve ambiguity; never fall back to older data.
        return '', None

    @staticmethod
    def _resource_names(reference):
        names = {}
        for value in reference.get('assigned_service_resources') or ():
            clean = ' '.join(str(value or '').split())
            if clean:
                names.setdefault(clean.casefold(), clean)
        return ', '.join(names.values())

    @classmethod
    def _reference_text(cls, text, reference, day, *, include_resources=True):
        fields = {key: reference.get(key, '') for key in (
            'phone', 'product_interest', 'work_type', 'source', 'sub_source', 'set_by',
            'canvass_set_by', 'lead_description', 'local_scheduled_start_time', 'scheduled_start')}
        assigned = cls._resource_names(reference) if include_resources else ''
        return authoritative_reference_text(
            text, reference.get('lead_name', ''), reference.get('address', ''),
            assigned, appointment_date=day,
            clear_assigned_resource=include_resources and not assigned, **fields)

    def _remove_morning_cards(self):
        for ident in self.repository.retired_morning_cards():
            try:
                self.files.remove('crops', ident)
            except OSError:
                log.warning('Temporary card file cleanup will retry; the scanned cards are available.')
                continue
            self.repository.forget(ident)

    def _enrich_reference_item(self, ident):
        item = self.repository.reference_item(ident)
        if not item:
            return False
        status_changed = bool(self.repository.refresh_sales_lead_status(
            ident, expected_work_order_key=item['work_order_key']))
        identity = dict(expected_day=item['document_date'],
                        expected_work_order_key=item['work_order_key'])
        kind, match = self._reference_for(item.get('document_date'), item['work_order_number'])
        if match is None:
            return status_changed

        reference_day = match.get('day') or item.get('document_date') or ''
        assigned = self._resource_names(match) if kind == 'final' else ''
        name = ' '.join(str(match.get('lead_name') or '').split())
        address = ' '.join(str(match.get('address') or '').split())
        text = self._reference_text(item.get('text', ''), match, reference_day, include_resources=kind == 'final')
        return bool(self.repository.apply_reference(
            ident,
            match.get('source_id', ''),
            kind,
            assigned if kind == 'final' else item.get('assigned_service_resource', ''),
            text,
            name,
            address,
            reference_day=reference_day,
            **identity,
        )) or status_changed

    def repair_missing_work_orders(self):
        """Recover clear saved OCR numbers only on cards still missing Lead status."""
        self.initialize()
        repaired = review = 0
        for item in self.repository.missing_work_order_items():
            number = printed_work_order_number(item['text'])
            changed = self.repository.repair_missing_work_order(item, number)
            repaired += changed if number else 0
            review += changed if not number else 0
        return dict(repaired=repaired, review=review)

    def work_order_numbers(self, *, missing_only=False):
        self.initialize()
        return self.repository.work_order_numbers(missing_only=missing_only)

    def work_order_lookup_numbers(self):
        """Accepted work orders plus OCR candidates awaiting source validation."""
        self.initialize()
        return self.repository.work_order_lookup_numbers()

    def publish_lead_statuses(self, work_order_numbers, records, captured, *, missing_only=False):
        """Apply a completed normalized work-order lookup independently of appointments."""
        self.initialize()
        normalized = []
        for record in records:
            value = self._reference_record(record)
            normalized.append({key: ' '.join(str(value.get(key) or '').split()) for key in (
                'work_order_number', 'lead_source_id', 'sales_lead_status')})
        changed = self.repository.replace_work_order_lead_statuses(
            work_order_numbers, normalized, captured, missing_only=missing_only)
        return dict(count=len(normalized), enriched=changed)

    def publish_work_order_records(self, work_order_numbers, records, captured):
        """Validate OCR candidates and enrich accepted work orders from normalized source data."""
        self.initialize()
        requested = {work_order_key(number) for number in work_order_numbers if work_order_key(number)}
        normalized = {}
        for record in records:
            value = self._reference_record(record)
            key = work_order_key(value.get('work_order_number', ''))
            if key in requested and key not in normalized:
                normalized[key] = value

        def fields(record):
            day = str(record.get('appointment_date') or '').strip()
            if day:
                day = checked_date(day)
            return (
                day,
                self._resource_names(record),
                ' '.join(str(record.get('lead_name') or '').split()),
                ' '.join(str(record.get('address') or '').split()),
                ' '.join(str(record.get('lead_source_id') or '').split()),
                ' '.join(str(record.get('sales_lead_status') or '').split()),
            )

        changed = 0
        # Existing confirmed work orders keep their direct enrichment path.
        for key, record in normalized.items():
            number = record.get('work_order_number', '')
            day, assigned, name, address, lead_source_id, sales_status = fields(record)
            for item in self.repository.work_order_items(number):
                text = self._reference_text(item.get('text', ''), record, day, include_resources=True)
                changed += self.repository.apply_work_order_reference(
                    item['id'], item['work_order_key'], str(record.get('source_id') or ''),
                    text, name, address, assigned, day, lead_source_id, sales_status,
                )

        # A scanned card accepts an OCR number only when exactly one of its
        # independent candidates resolves through the normalized source.
        validated = 0
        for item in self.repository.work_order_candidate_items():
            matches = [
                (candidate, normalized[work_order_key(candidate)])
                for candidate in item['candidates']
                if work_order_key(candidate) in normalized
            ]
            if len(matches) != 1:
                continue
            number, record = matches[0]
            day, assigned, name, address, lead_source_id, sales_status = fields(record)
            text = self._reference_text(
                'Work Order Number: ' + number, record, day, include_resources=True
            )
            applied = self.repository.apply_validated_work_order_reference(
                item['id'], item['candidates'], number, str(record.get('source_id') or ''),
                text, name, address, assigned, day, lead_source_id, sales_status,
            )
            changed += applied
            validated += applied
        return dict(count=len(normalized), enriched=changed, validated=validated)

    def reference_dates(self):
        """Distinct usable dates of retained cards, for normalized source backfill."""
        self.initialize()
        days = set()
        for value in self.repository.reference_dates():
            try:
                days.add(checked_date_filter(value))
            except (TypeError, ValueError):
                continue
        return sorted(day for day in days if day and day != 'undated')

    def enrich_reference_day(self, day):
        self.initialize()
        changed = 0
        for item in self.repository.reference_items(checked_date(day)):
            changed += int(self._enrich_reference_item(item['id']))
        return changed

    def publish_reference_snapshot(self, day, kind, records, captured):
        """Store normalized reference data; it never creates Gallery cards."""
        self.initialize()
        day = checked_date(day)
        if kind not in ('morning', 'final'):
            raise ValueError('Unknown Gallery reference snapshot kind.')
        normalized = [self._reference_record(record) for record in records]
        self.repository.replace_reference_snapshot(day, kind, normalized, captured)
        changed = self.enrich_reference_day(day)
        return dict(day=day, kind=kind, count=len(normalized), enriched=changed)

    def queue(self, state='', offset=0, limit=25):
        self.initialize()
        if state not in ('','pending','WAITING','PROCESSING','COMPLETE','ERROR'):
            raise ValueError('Choose a valid gallery job state.')
        return self.repository.import_queue(state, max(0,min(offset,1000000)), max(1,min(limit,25)))

    def import_job(self, ident, offset=0):
        self.initialize()
        result = self.repository.import_job(ident, max(0,min(offset,1000000)))
        if result:
            result['source_available'] = self.files.path('spool',ident).is_file()
        return result

    def import_item(self, import_id, item_id):
        """Administrative view of one retained card, including review-only cards."""
        self.initialize()
        return self.repository.import_item(import_id, item_id)

    def approve_import_item(self, import_id, item_id):
        """Publish one review-only generated card to the normal Gallery."""
        self.initialize()
        return self.repository.approve_import_item(import_id, item_id)

    def delete_import_item(self, import_id, item_id):
        """Delete exactly one generated card from this gallery job."""
        self.initialize()
        claimed = self.repository.claim_import_item_delete(import_id, item_id)
        try:
            with self.files.lock():
                self.files.remove('crops', item_id)
        except (OSError, ValueError):
            self.repository.restore_import_item(import_id, item_id, claimed['state'])
            raise
        self.repository.finish_import_item_delete(
            import_id, item_id, claimed['page'], claimed['part'])
        return claimed

    def reprocess(self, ident):
        """Discard generated gallery data so the same original PDF can be offered again."""
        self.initialize()
        reset = self.repository.reset_for_reprocess(ident)
        with self.files.lock():
            for item_id in reset['item_ids']:
                self.files.remove('crops', item_id)
            self.files.remove('spool', ident)
            self.files.remove('work', ident)
        return reset

    def report_progress(self, ident):
        value = self.files.read_progress(ident)
        stages = {'inspect':'Inspecting PDF','render':'Rendering page','crop':'Detecting form borders',
                  'search':'Reading text for search','page-complete':'Page processed','publish':'Saving gallery images'}
        if not isinstance(value,dict) or value.get('stage') not in stages:
            return
        if any(type(value.get(k)) is not int or not 0<=value[k]<=100000 for k in ('page','pages','crops')):
            return
        clean = {k:value[k] for k in ('stage','page','pages','crops')}
        clean['message'] = stages[value['stage']]
        if value['pages']:
            clean['message'] += f" — page {value['page']} of {value['pages']}, {value['crops']} image(s) prepared"
        self.repository.progress(ident, clean)


    def repair_one(self, reader):
        """Low-priority worker operation; reader returns normalized OCR values.

        Re-read existing PNGs so lost word geometry and TSV contamination can be
        corrected without PDFs or any destructive document reimport.
        """
        self.initialize()
        item = self.repository.recognition_candidate(time.time())
        if not item:
            return False
        try:
            result = reader(self.files.path('crops', item['id']))
            if not isinstance(result, dict) or not isinstance(result.get('text'), str):
                raise ValueError('Invalid recognition result')
            text = result['text'][:100000]
            if not text.strip():
                raise ValueError('No readable text; preserve the existing search index')
            header = result.get('lead_text', '')
            if not isinstance(header, str):
                raise ValueError('Invalid header text')
            candidates = tuple(result.get('work_order_candidates') or ())
            if item.get('state') == 'REVIEW' and not item.get('work_order_key'):
                if not candidates:
                    raise ValueError('No readable work order; retry later')
                if not self.repository.save_work_order_candidates(item['id'], candidates):
                    raise ValueError('Work-order candidate changed during recognition')
                return True
            name = printed_lead(header) or printed_lead(text)
            address = printed_address(text)
            work_order = printed_work_order_number(text)
            self.repository.repair_recognition(
                item['id'], text, name, lead_key(name), address, address_key(address),
                work_order, work_order_key(work_order),
            )
            self._enrich_reference_item(item['id'])
        except (OSError, ValueError):
            self.repository.defer_recognition(item['id'], time.time())
        return True
