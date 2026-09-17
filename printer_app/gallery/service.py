"""Gallery workflows through explicit file/repository boundaries; no print actions."""
import hashlib
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .policy import (address_key, checked_date, checked_date_filter, checked_lead_name,
                     search_expression, printed_address, printed_lead, lead_key, related_identity)


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

    def search(self, query, offset, document_date=''):
        self.initialize()
        return self.repository.list_items(search_expression(query), max(0, min(offset, 1000000)),
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
            'lead_name','lead_status','address','notes_count'
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

    def lead(self, ident, value):
        self.initialize()
        name = checked_lead_name(value)
        if not name or not any(c.isalpha() for c in name):
            raise ValueError('Enter the lead name printed on this card.')
        item = self.repository.item(ident)
        if not item:
            raise LookupError('This image has expired or is unavailable.')
        matches = self._identity_matches(item)
        return self.repository.rename_leads(
            [row['id'] for row in matches], name, lead_key(name)
        )

    def item(self, ident):
        self.initialize()
        return self.repository.item(ident)

    def note(self, ident, note_id, author, body):
        self.initialize()
        if not body.strip() or len(body) > 2000 or len(author) > 80 or len(note_id) != 32:
            raise ValueError('Enter a note up to 2,000 characters and a name up to 80 characters.')
        int(note_id, 16)
        self.repository.add_note(ident, note_id, author.strip() or 'Anonymous', body.strip())

    def date(self, ident, value):
        self.initialize()
        self.repository.correct_date(ident, checked_date(value))

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
        items = []
        for entry in manifest['items']:
            ident = hashlib.sha256(f"{job['id']}:{entry['page']}:{entry['part']}".encode()).hexdigest()
            self.files.publish(directory / entry['file'], ident)
            items.append(dict(id=ident, import_id=job['id'], filename=job['filename'],
                page=entry['page'], part=entry['part'], bytes=entry['bytes'], text=entry['text'],
                document_date=entry['document_date'], date_status=entry['date_status'], created=time.time(),
                lead_text=entry.get('lead_text', ''), recognition_revision=1 if 'lead_text' in entry and entry['text'].strip() else 0))
        warnings = manifest.get('warnings', [])
        if manifest.get('skipped'):
            warnings.append('No recognized form boxes on pages: ' + ', '.join(map(str, manifest['skipped'])))
        self.repository.finish(job['id'], items, '; '.join(warnings))
        self.files.remove('spool', job['id'])
        self.files.remove('work', job['id'])

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
            name = printed_lead(header) or printed_lead(text)
            address = printed_address(text)
            self.repository.repair_recognition(
                item['id'], text, name, lead_key(name), address, address_key(address)
            )
        except (OSError, ValueError):
            self.repository.defer_recognition(item['id'], time.time())
        return True
