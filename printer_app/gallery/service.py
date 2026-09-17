"""Gallery workflows through explicit file/repository boundaries; no print actions."""
import hashlib
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .policy import checked_date, search_expression


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

    def search(self, query, offset):
        self.initialize()
        return self.repository.list_items(search_expression(query), max(0, min(offset, 1000000)))

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
                document_date=entry['document_date'], date_status=entry['date_status'], created=time.time()))
        warnings = manifest.get('warnings', [])
        if manifest.get('skipped'):
            warnings.append('No recognized form boxes on pages: ' + ', '.join(map(str, manifest['skipped'])))
        self.repository.finish(job['id'], items, '; '.join(warnings))
        self.files.remove('spool', job['id'])
        self.files.remove('work', job['id'])
