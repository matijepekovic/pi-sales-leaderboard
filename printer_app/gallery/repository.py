"""The gallery's SQLite schema, search index, import receipts, and notes."""
import json
import re
import sqlite3
import time
from contextlib import contextmanager

from .policy import (
    address_key, clear_work_order_identity, lead_key, printed_address, printed_lead,
    normalize_work_order_evidence, printed_work_order_number, work_order_key,
)

_UNSET = object()


def _work_order_evidence(raw):
    """Decode persisted scan evidence without interpreting it as card identity."""
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        value = {}
    return normalize_work_order_evidence(value)


def _work_order_reads(raw):
    reads = []
    for entry in raw if isinstance(raw, (list, tuple)) else ():
        if isinstance(entry, dict):
            reads.append({
                'label': str(entry.get('label') or '')[:80],
                'psm': entry.get('psm') if type(entry.get('psm')) is int else None,
                'text': str(entry.get('text') or '')[:256],
                'candidate': str(entry.get('candidate') or '')[:8],
                'ok': bool(entry.get('ok')),
            })
    return reads


SCHEMA = '''
CREATE TABLE IF NOT EXISTS imports (
 id TEXT PRIMARY KEY, filename TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'WAITING',
 created REAL NOT NULL, updated REAL NOT NULL, error TEXT NOT NULL DEFAULT '', count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS import_steps (
 id INTEGER PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
 at REAL NOT NULL, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS gallery_import_steps ON import_steps(import_id,id);
CREATE TABLE IF NOT EXISTS import_review_pages (
 import_id TEXT NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
 page INTEGER NOT NULL, file_id TEXT NOT NULL, bytes INTEGER NOT NULL,
 reason TEXT NOT NULL DEFAULT 'no-recognized-forms',
 PRIMARY KEY(import_id,page));
CREATE TABLE IF NOT EXISTS items (
 id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id), page INTEGER NOT NULL,
 part INTEGER NOT NULL, filename TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
 notes_text TEXT NOT NULL DEFAULT '', document_date TEXT, date_status TEXT NOT NULL,
 bytes INTEGER NOT NULL, created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'ACTIVE');
CREATE INDEX IF NOT EXISTS gallery_items_date ON items(state,document_date);
CREATE TABLE IF NOT EXISTS notes (
 id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
 author TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS gallery_notes_item ON notes(item_id,created);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(text,notes_text,filename,
 content='items',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2',prefix='2 3 4');
CREATE TRIGGER IF NOT EXISTS gallery_insert AFTER INSERT ON items BEGIN
 INSERT INTO search(rowid,text,notes_text,filename) VALUES(new.rowid,new.text,new.notes_text,new.filename); END;
CREATE TRIGGER IF NOT EXISTS gallery_delete AFTER DELETE ON items BEGIN
 INSERT INTO search(search,rowid,text,notes_text,filename) VALUES('delete',old.rowid,old.text,old.notes_text,old.filename); END;
CREATE TRIGGER IF NOT EXISTS gallery_update AFTER UPDATE ON items BEGIN
 INSERT INTO search(search,rowid,text,notes_text,filename) VALUES('delete',old.rowid,old.text,old.notes_text,old.filename);
 INSERT INTO search(rowid,text,notes_text,filename) VALUES(new.rowid,new.text,new.notes_text,new.filename); END;
CREATE TABLE IF NOT EXISTS appointment_reference_snapshots (
 day TEXT NOT NULL, kind TEXT NOT NULL, captured REAL NOT NULL, count INTEGER NOT NULL,
 PRIMARY KEY(day,kind));
CREATE TABLE IF NOT EXISTS lead_status_snapshots (
 lead_source_id TEXT PRIMARY KEY, sales_lead_status TEXT NOT NULL DEFAULT '',
 captured REAL NOT NULL);
CREATE TABLE IF NOT EXISTS work_order_leads (
 work_order_key TEXT PRIMARY KEY, lead_source_id TEXT NOT NULL DEFAULT '',
 captured REAL NOT NULL);
CREATE INDEX IF NOT EXISTS gallery_work_order_lead ON work_order_leads(lead_source_id);
CREATE TABLE IF NOT EXISTS appointment_references (
 day TEXT NOT NULL, kind TEXT NOT NULL, source_id TEXT NOT NULL,
 work_order_number TEXT NOT NULL DEFAULT '', work_order_key TEXT NOT NULL DEFAULT '',
 lead_name TEXT NOT NULL DEFAULT '', lead_key TEXT NOT NULL DEFAULT '',
 address TEXT NOT NULL DEFAULT '', address_key TEXT NOT NULL DEFAULT '',
 phone TEXT NOT NULL DEFAULT '', scheduled_start TEXT NOT NULL DEFAULT '',
 assigned_service_resources TEXT NOT NULL DEFAULT '[]',
 product_interest TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
 sub_source TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(day,kind,source_id));
CREATE INDEX IF NOT EXISTS gallery_reference_work_order
 ON appointment_references(day,kind,work_order_key);
CREATE INDEX IF NOT EXISTS gallery_reference_address
 ON appointment_references(day,kind,address_key);
CREATE INDEX IF NOT EXISTS gallery_reference_lead
 ON appointment_references(day,kind,lead_key);
'''


class GalleryRepository:
    def __init__(self, path):
        self.path = path

    @staticmethod
    def _recognition_view(row):
        """Decode stored OCR diagnostics at the repository boundary for admin display."""
        if row is None:
            return None
        value = dict(row)
        raw = value.get('work_order_candidates', '[]')
        try:
            candidates = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError):
            candidates = []
        if not isinstance(candidates, (list, tuple)):
            candidates = []
        value['work_order_candidates'] = tuple(
            candidate for candidate in candidates if isinstance(candidate, str)
            and len(candidate) == 8 and candidate.isascii() and candidate.isdecimal()
        )

        raw_reads = value.get('work_order_reads', '[]')
        try:
            reads = json.loads(raw_reads) if isinstance(raw_reads, str) else raw_reads
        except (TypeError, ValueError, json.JSONDecodeError):
            reads = []
        clean_reads = []
        for entry in reads if isinstance(reads, list) else ():
            if not isinstance(entry, dict):
                continue
            label = str(entry.get('label') or '')[:80]
            text = str(entry.get('text') or '')[:256]
            candidate = str(entry.get('candidate') or '')
            psm = entry.get('psm')
            if candidate and not (len(candidate) == 8 and candidate.isascii() and candidate.isdecimal()):
                candidate = ''
            if type(psm) is not int or not 0 <= psm <= 99:
                psm = None
            clean_reads.append(dict(
                label=label, psm=psm, text=text, candidate=candidate,
                ok=bool(entry.get('ok')),
            ))
        value['work_order_reads'] = tuple(clean_reads)
        value['work_order_evidence'] = _work_order_evidence(value.get('work_order_evidence'))
        return value

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=2)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(SCHEMA)
            c.execute('BEGIN IMMEDIATE')
            import_columns = {row['name'] for row in c.execute('PRAGMA table_info(imports)')}
            for name, definition in (('progress', "TEXT NOT NULL DEFAULT '{}'"), ('started', 'REAL'), ('completed', 'REAL'),
                                     ('origin', "TEXT NOT NULL DEFAULT 'scan'"), ('reference_day', 'TEXT'),
                                     ('reprocess_pending', 'INTEGER NOT NULL DEFAULT 0')):
                if name not in import_columns:
                    c.execute(f'ALTER TABLE imports ADD COLUMN {name} {definition}')
            columns = {row['name'] for row in c.execute('PRAGMA table_info(items)')}
            for name, definition in (('recognition_revision', 'INTEGER NOT NULL DEFAULT 0'),
                                     ('recognition_attempts', 'INTEGER NOT NULL DEFAULT 0'),
                                     ('recognition_retry_at', 'REAL NOT NULL DEFAULT 0')):
                if name not in columns:
                    c.execute(f'ALTER TABLE items ADD COLUMN {name} {definition}')
            if 'lead_name' not in columns:
                c.execute("ALTER TABLE items ADD COLUMN lead_name TEXT NOT NULL DEFAULT ''")
                c.execute("ALTER TABLE items ADD COLUMN lead_key TEXT NOT NULL DEFAULT ''")
                c.execute("ALTER TABLE items ADD COLUMN lead_status TEXT NOT NULL DEFAULT 'needs-name'")
                # Backfill saved search text only; no PDF import, OCR or image changes.
                for row in c.execute('SELECT id,text FROM items'):
                    name = printed_lead(row['text'])
                    c.execute('UPDATE items SET lead_name=?,lead_key=?,lead_status=? WHERE id=?',
                              (name, lead_key(name), 'printed' if name else 'needs-name', row['id']))
            columns = {row['name'] for row in c.execute('PRAGMA table_info(items)')}
            address_added = False
            if 'address' not in columns:
                c.execute("ALTER TABLE items ADD COLUMN address TEXT NOT NULL DEFAULT ''")
                address_added = True
            if 'address_key' not in columns:
                c.execute("ALTER TABLE items ADD COLUMN address_key TEXT NOT NULL DEFAULT ''")
                address_added = True
            if address_added:
                for row in c.execute('SELECT id,text FROM items'):
                    address = printed_address(row['text'])
                    c.execute('UPDATE items SET address=?,address_key=? WHERE id=?',
                              (address, address_key(address), row['id']))
            columns = {row['name'] for row in c.execute('PRAGMA table_info(items)')}
            for name, definition in (
                ('work_order_number', "TEXT NOT NULL DEFAULT ''"),
                ('work_order_key', "TEXT NOT NULL DEFAULT ''"),
                ('work_order_candidates', "TEXT NOT NULL DEFAULT '[]'"),
                ('work_order_reads', "TEXT NOT NULL DEFAULT '[]'"),
                ('work_order_evidence', "TEXT NOT NULL DEFAULT '{}'"),
                ('assigned_service_resource', "TEXT NOT NULL DEFAULT ''"),
                ('sales_lead_status', "TEXT NOT NULL DEFAULT ''"),
                ('lead_source_id', "TEXT NOT NULL DEFAULT ''"),
                ('reference_kind', "TEXT NOT NULL DEFAULT ''"),
                ('reference_source_id', "TEXT NOT NULL DEFAULT ''"),
                ('origin', "TEXT NOT NULL DEFAULT 'scan'"),
                ('mod_notes_status', "TEXT NOT NULL DEFAULT 'legacy'"),
                ('image_revision', "TEXT NOT NULL DEFAULT ''"),
                ('search_revision', 'INTEGER NOT NULL DEFAULT 0'),
            ):
                if name not in columns:
                    c.execute(f'ALTER TABLE items ADD COLUMN {name} {definition}')
            reference_columns = {row['name'] for row in c.execute('PRAGMA table_info(appointment_references)')}
            for name in ('local_scheduled_start_time', 'canvass_set_by', 'set_by', 'work_type', 'lead_description',
                         'sales_lead_status', 'lead_source_id'):
                if name not in reference_columns:
                    c.execute(f"ALTER TABLE appointment_references ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            if not c.execute("SELECT 1 FROM meta WHERE key='work_order_backfill_v1'").fetchone():
                for row in list(c.execute("SELECT id,text FROM items WHERE work_order_key=''")):
                    number = printed_work_order_number(row['text'])
                    if number:
                        c.execute(
                            'UPDATE items SET work_order_number=?,work_order_key=? WHERE id=?',
                            (number, work_order_key(number), row['id']),
                        )
                c.execute("INSERT INTO meta(key,value) VALUES('work_order_backfill_v1','true')")

            c.execute('CREATE INDEX IF NOT EXISTS gallery_items_lead ON items(state,lead_key,document_date)')
            c.execute('CREATE INDEX IF NOT EXISTS gallery_items_address ON items(state,address_key,document_date)')
            c.execute('CREATE INDEX IF NOT EXISTS gallery_items_work_order ON items(state,work_order_key,document_date)')
            c.execute('CREATE INDEX IF NOT EXISTS gallery_items_source_lead ON items(lead_source_id,state)')
            c.execute('CREATE INDEX IF NOT EXISTS gallery_reference_source_lead ON appointment_references(lead_source_id)')
            search_columns = {row['name'] for row in c.execute('PRAGMA table_info(search)')}
            if not {'lead_name', 'address', 'assigned_service_resource'} <= search_columns:
                # Replace the one search index, not a parallel implementation.
                for event in ('insert', 'delete', 'update'):
                    c.execute('DROP TRIGGER IF EXISTS gallery_' + event)
                c.execute('DROP TABLE search')
                c.execute("""CREATE VIRTUAL TABLE search USING fts5(text,notes_text,filename,lead_name,address,assigned_service_resource,
                    content='items',content_rowid='rowid',
                    tokenize='unicode61 remove_diacritics 2',prefix='2 3 4')""")
                add = 'INSERT INTO search(rowid,text,notes_text,filename,lead_name,address,assigned_service_resource) VALUES(new.rowid,new.text,new.notes_text,new.filename,new.lead_name,new.address,new.assigned_service_resource);'
                remove = "INSERT INTO search(search,rowid,text,notes_text,filename,lead_name,address,assigned_service_resource) VALUES('delete',old.rowid,old.text,old.notes_text,old.filename,old.lead_name,old.address,old.assigned_service_resource);"
                for event, statement in (('insert', add), ('delete', remove), ('update', remove + add)):
                    c.execute(f'CREATE TRIGGER gallery_{event} AFTER {event} ON items BEGIN {statement} END')
                c.execute("INSERT INTO search(search) VALUES('rebuild')")

            if not c.execute("SELECT 1 FROM meta WHERE key='flattened_lead_backfill'").fetchone():
                for row in list(c.execute("SELECT id,text FROM items WHERE lead_key='' AND lead_status!='confirmed'")):
                    name = printed_lead(row['text'])
                    if name:
                        c.execute("UPDATE items SET lead_name=?,lead_key=?,lead_status='printed' WHERE id=?",
                                  (name, lead_key(name), row['id']))
                c.execute("INSERT INTO meta(key,value) VALUES('flattened_lead_backfill','true')")

            # From this release forward, OCR is never allowed to publish an
            # unnamed crop by itself. Move existing unnamed active cards behind
            # the same manual-review gate exactly once; later manual approvals
            # must remain ACTIVE even if the card still has no recognized name.
            if not c.execute("SELECT 1 FROM meta WHERE key='unnamed_review_gate_v1'").fetchone():
                c.execute("UPDATE items SET state='REVIEW' WHERE state='ACTIVE' AND lead_key=''")
                c.execute("INSERT INTO meta(key,value) VALUES('unnamed_review_gate_v1','true')")

    def import_state(self, ident):
        with self.connect() as c:
            row = c.execute('SELECT state FROM imports WHERE id=?', (ident,)).fetchone()
            return row['state'] if row else None

    def imported(self, ident):
        with self.connect() as c:
            row = c.execute('SELECT state FROM imports WHERE id=?', (ident,)).fetchone()
            return bool(row and row['state'] != 'ERROR')

    def enqueue(self, ident, filename, *, origin='scan', reference_day=None):
        now = time.time()
        with self.connect() as c:
            changed = c.execute('''INSERT INTO imports(id,filename,created,updated,origin,reference_day) VALUES(?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET state='WAITING',updated=excluded.updated,error='',
                filename=excluded.filename,progress='{}',started=NULL,completed=NULL
              WHERE imports.state='ERROR' ''', (ident, filename[:150], now, now, origin, reference_day)).rowcount
            if changed:
                self._step(c, ident, now, 'PDF received. Waiting for gallery processing; not a print request.')

    def recover(self):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            for row in list(c.execute("SELECT id FROM imports WHERE state='PROCESSING'")):
                self._step(c, row['id'], time.time(), 'Interrupted processing returned to gallery queue after restart.')
            c.execute("UPDATE imports SET state='WAITING' WHERE state='PROCESSING'")

    def claim(self):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM imports WHERE state='WAITING' ORDER BY created LIMIT 1").fetchone()
            if row:
                now = time.time()
                c.execute("UPDATE imports SET state='PROCESSING',started=coalesce(started,?),updated=? WHERE id=?", (now, now, row['id']))
                self._step(c, row['id'], now, 'Gallery worker started processing the PDF.')
                return dict(row)

    def finish(self, ident, items, warning='', *, publication=None, review_pages=(),
               supersede_previous=False):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            import_row = c.execute(
                'SELECT reprocess_pending FROM imports WHERE id=?', (ident,)
            ).fetchone()
            reprocessing = bool(import_row and import_row['reprocess_pending'])
            prior_item_ids = {
                row['id'] for row in c.execute('SELECT id FROM items WHERE import_id=?', (ident,))
            } if reprocessing else set()
            prior_review_files = {
                row['file_id'] for row in c.execute(
                    'SELECT file_id FROM import_review_pages WHERE import_id=?', (ident,)
                )
            }
            current_item_ids = set()
            saved = skipped_existing = 0
            for item in items:
                origin = item.get('origin', 'scan')
                strict_scan = origin == 'scan' and 'work_order_candidates' in item
                work_order = str(item.get('work_order_number') or '') if strict_scan else printed_work_order_number(item['text'])
                if strict_scan and (item.get('work_order_candidates') or len(work_order) != 8
                                    or not work_order.isascii() or not work_order.isdecimal()):
                    work_order = ''
                if strict_scan and not work_order:
                    item = dict(item, text=clear_work_order_identity(item['text']))
                name = printed_lead(item.get('lead_text') or item['text'])
                address = printed_address(item['text'])
                raw_candidates = item.get('work_order_candidates') or ()
                candidates = tuple(dict.fromkeys(
                    value for value in raw_candidates
                    if isinstance(value, str) and len(value) == 8
                    and value.isascii() and value.isdecimal()
                ))
                reads = _work_order_reads(item.get('work_order_reads') or ())
                state = 'ACTIVE' if name else 'REVIEW'
                if strict_scan:
                    state = 'ACTIVE' if work_order else 'REVIEW'
                elif item.get('require_identity'):
                    # Scanned OCR candidates are source-validated before becoming
                    # the durable work-order identity. Morning cards already come
                    # from normalized source data and retain their existing path.
                    state = 'ACTIVE' if work_order else 'REVIEW'
                notes_status = item.get('mod_notes_status', 'legacy') if origin == 'scan' else 'legacy'
                if notes_status not in ('legacy', 'present', 'unknown'):
                    raise ValueError('Invalid MOD notes status')
                if notes_status == 'unknown':
                    state = 'REVIEW'
                    if item.get('replace_existing'):
                        raise ValueError('Unreadable MOD notes cannot replace an existing card')
                if origin == 'morning' and work_order and c.execute("""SELECT 1 FROM items
                        WHERE document_date=? AND work_order_key=? AND state IN ('ACTIVE','REVIEW')
                        AND mod_notes_status!='unknown'""",
                        (item.get('document_date'), work_order_key(work_order))).fetchone():
                    skipped_existing += 1
                    continue
                values = dict(item, state=state, lead_name=name, lead_key=lead_key(name),
                              lead_status='printed' if name else 'needs-name',
                              address=address, address_key=address_key(address),
                              work_order_number=work_order, work_order_key=work_order_key(work_order),
                              work_order_candidates=json.dumps(candidates if origin == 'scan' else []),
                              work_order_reads=json.dumps(reads if origin == 'scan' else []),
                              work_order_evidence=json.dumps(normalize_work_order_evidence(
                                  item.get('work_order_evidence') if origin == 'scan' else {})),
                              recognition_revision=item.get('recognition_revision', 0), origin=origin,
                              mod_notes_status=notes_status,
                              image_revision=item.get('image_revision', item['id']))
                same_import_existing = bool(reprocessing and c.execute(
                    'SELECT 1 FROM items WHERE id=? AND import_id=?',
                    (item['id'], ident),
                ).fetchone())
                if same_import_existing:
                    # A reprocess does not destroy the previous result before the
                    # replacement is ready. Reuse the deterministic card ID so
                    # notes/history survive when the same page/card is recognized.
                    changed = c.execute('''UPDATE items SET page=:page,part=:part,
                        filename=:filename,text=:text,document_date=:document_date,date_status=:date_status,
                        bytes=:bytes,state=:state,lead_name=:lead_name,lead_key=:lead_key,
                        lead_status=:lead_status,address=:address,address_key=:address_key,
                        work_order_number=:work_order_number,work_order_key=:work_order_key,
                        work_order_candidates=:work_order_candidates,work_order_reads=:work_order_reads,
                        work_order_evidence=:work_order_evidence,
                        recognition_revision=:recognition_revision,origin=:origin,
                        mod_notes_status=:mod_notes_status,
                        image_revision=:image_revision,search_revision=search_revision+1
                        WHERE id=:id AND import_id=:import_id AND state IN ('ACTIVE','REVIEW')''',
                        values).rowcount
                    saved += changed
                    current_item_ids.add(item['id'])
                    self._refresh_sales_lead_statuses(c, ' AND id=?', (item['id'],))
                    if changed and origin == 'scan' and state == 'ACTIVE':
                        self._reconcile_morning_cards(
                            c, item['id'], item.get('document_date'), work_order_key(work_order)
                        )
                    continue
                if item.get('replace_existing'):
                    # The scan takes over the existing card; notes retain their item ID.
                    changed = c.execute('''UPDATE items SET import_id=:import_id,page=:page,part=:part,
                        filename=:filename,text=:text,document_date=:document_date,date_status=:date_status,
                        bytes=:bytes,state=:state,lead_name=:lead_name,lead_key=:lead_key,
                        lead_status=:lead_status,address=:address,address_key=:address_key,
                        work_order_number=:work_order_number,work_order_key=:work_order_key,
                        work_order_candidates=:work_order_candidates,work_order_reads=:work_order_reads,
                        work_order_evidence=:work_order_evidence,
                        recognition_revision=:recognition_revision,origin=:origin,
                        mod_notes_status=:mod_notes_status,
                        image_revision=:image_revision,search_revision=search_revision+1
                        WHERE id=:id AND state IN ('ACTIVE','REVIEW')
                        AND document_date=:document_date AND work_order_key=:work_order_key''', values).rowcount
                    saved += changed
                    skipped_existing += not changed
                    if changed:
                        current_item_ids.add(item['id'])
                    self._refresh_sales_lead_statuses(c, ' AND id=?', (item['id'],))
                    if changed and origin == 'scan' and state == 'ACTIVE':
                        self._reconcile_morning_cards(c, item['id'], item.get('document_date'), work_order_key(work_order))
                    continue
                changed = c.execute('''INSERT OR IGNORE INTO items(
                    id,import_id,page,part,filename,text,document_date,date_status,bytes,created,state,
                    lead_name,lead_key,lead_status,address,address_key,work_order_number,work_order_key,
                    work_order_candidates,work_order_reads,work_order_evidence,recognition_revision,origin,
                    mod_notes_status,image_revision)
                    VALUES (
                    :id,:import_id,:page,:part,:filename,:text,:document_date,:date_status,:bytes,:created,:state,
                    :lead_name,:lead_key,:lead_status,:address,:address_key,:work_order_number,:work_order_key,
                    :work_order_candidates,:work_order_reads,:work_order_evidence,:recognition_revision,:origin,
                    :mod_notes_status,:image_revision)''', values).rowcount
                saved += changed
                skipped_existing += not changed
                if changed:
                    current_item_ids.add(item['id'])
                self._refresh_sales_lead_statuses(c, ' AND id=?', (item['id'],))
                if changed and origin == 'scan' and state == 'ACTIVE':
                    self._reconcile_morning_cards(c, item['id'], item.get('document_date'), work_order_key(work_order))
            retired_item_ids = []
            if reprocessing and supersede_previous:
                retired_item_ids = sorted(prior_item_ids - current_item_ids)
                for old_id in retired_item_ids:
                    c.execute('DELETE FROM items WHERE id=? AND import_id=?', (old_id, ident))

            clean_review_pages = []
            for entry in review_pages:
                page = int(entry.get('page', 0))
                file_id = str(entry.get('file_id', ''))
                size = int(entry.get('bytes', -1))
                reason = str(entry.get('reason') or 'no-recognized-forms')[:80]
                if page < 1 or not re.fullmatch(r'[a-f0-9]{64}', file_id) or size < 0:
                    raise ValueError('Invalid Gallery review page')
                clean_review_pages.append((page, file_id, size, reason))
            c.execute('DELETE FROM import_review_pages WHERE import_id=?', (ident,))
            for page, file_id, size, reason in clean_review_pages:
                c.execute('''INSERT INTO import_review_pages(import_id,page,file_id,bytes,reason)
                    VALUES (?,?,?,?,?)''', (ident, page, file_id, size, reason))
            current_review_files = {entry[1] for entry in clean_review_pages}
            retired_review_file_ids = sorted(prior_review_files - current_review_files)

            now = time.time()
            c.execute("""UPDATE imports SET state='COMPLETE',count=?,error=?,updated=?,completed=?,
                      reprocess_pending=0 WHERE id=?""",
                      (len(items), warning[:1000], now, now, ident))
            published = c.execute(
                "SELECT count(*) FROM items WHERE import_id=? AND state='ACTIVE'", (ident,)
            ).fetchone()[0]
            review = c.execute(
                "SELECT count(*) FROM items WHERE import_id=? AND state='REVIEW'", (ident,)
            ).fetchone()[0]
            message = f'Import completed: {len(items)} generated; {published} published to Gallery'
            if review:
                message += f'; {review} need review of their name, work order, or date'
            if publication is not None:
                counts = {key: max(0, int(publication.get(key, 0))) for key in (
                    'prepared', 'saved', 'skipped_existing', 'skipped_blank_notes', 'needs_notes_review')}
                counts['saved'] = saved
                counts['skipped_existing'] += skipped_existing
                counts['needs_notes_review'] = c.execute("""SELECT count(*) FROM items
                    WHERE import_id=? AND state='REVIEW' AND mod_notes_status='unknown'""", (ident,)).fetchone()[0]
                message = (f"Import completed: {counts['prepared']} prepared; {saved} saved; "
                           f"{published} published to Gallery; {counts['skipped_existing']} already present; "
                           f"{counts['skipped_blank_notes']} skipped with blank MOD Notes; "
                           f"{counts['needs_notes_review']} need MOD Notes review")
                progress_row = c.execute('SELECT progress FROM imports WHERE id=?', (ident,)).fetchone()
                progress = json.loads(progress_row['progress']) if progress_row else {}
                progress.update(publication=counts, stage='complete', message=message + '.')
                c.execute('UPDATE imports SET progress=? WHERE id=?', (json.dumps(progress), ident))
            self._step(c, ident, now, message + '.')
            if warning:
                self._step(c, ident, now, warning[:1000])
            return dict(
                retired_item_ids=retired_item_ids,
                retired_review_file_ids=retired_review_file_ids,
            )

    def card_for_work_order(self, day, number):
        if not day or not work_order_key(number):
            return None
        with self.connect() as c:
            rows = c.execute("""SELECT id,origin FROM items WHERE document_date=? AND work_order_key=?
                AND state IN ('ACTIVE','REVIEW') AND mod_notes_status!='unknown'
                ORDER BY created,id LIMIT 2""",
                (day, work_order_key(number))).fetchall()
            return dict(rows[0]) if len(rows) == 1 else None

    def retired_morning_cards(self):
        """Pending file cleanup after an exact card reconciliation committed."""
        with self.connect() as c:
            return [row['id'] for row in c.execute("SELECT id FROM items WHERE origin='morning' AND state='DELETING'")]

    def update_notes_status(self, ident, expected_image_revision, status):
        """Record a notes-only retry without changing accepted or pending identity."""
        if status not in ('present', 'unknown'):
            raise ValueError('Invalid MOD notes retry status')
        with self.connect() as c:
            return c.execute("""UPDATE items SET mod_notes_status=?,
                recognition_attempts=CASE WHEN ?='present' THEN 0 ELSE recognition_attempts+1 END,
                recognition_retry_at=CASE WHEN ?='present' THEN 0 ELSE ? END,
                search_revision=search_revision+1
                WHERE id=? AND image_revision=? AND origin='scan'
                AND state='REVIEW' AND mod_notes_status='unknown'""",
                (status, status, status, time.time() + 300, ident, expected_image_revision)).rowcount

    def discard_candidate(self, ident, expected_image_revision):
        """Claim only an unchanged unknown-notes scan now confirmed blank."""
        with self.connect() as c:
            return c.execute("""UPDATE items SET state='DELETING',mod_notes_status='blank'
                WHERE id=? AND image_revision=? AND origin='scan'
                AND state='REVIEW' AND mod_notes_status='unknown'""",
                (ident, expected_image_revision)).rowcount

    def discarded_scan_candidates(self):
        """Retryable file cleanup claims, separate from manual card deletion."""
        with self.connect() as c:
            return [row['id'] for row in c.execute("""SELECT id FROM items
                WHERE origin='scan' AND state='DELETING' AND mod_notes_status='blank'""")]

    @staticmethod
    def _reconcile_morning_cards(c, ident, day, key):
        """Keep the accepted scan ID and move matching placeholders' user history."""
        if not day or not key:
            return
        if not c.execute("""SELECT 1 FROM items WHERE id=? AND origin='scan'
                AND state='ACTIVE' AND mod_notes_status!='unknown' AND work_order_key=?
                AND document_date=? AND date_status IN ('printed','confirmed')""", (ident, key, day)).fetchone():
            return
        placeholders = [row['id'] for row in c.execute("""SELECT id FROM items
            WHERE id!=? AND origin='morning' AND document_date=? AND work_order_key=?
            AND state IN ('ACTIVE','REVIEW')""", (ident, day, key))]
        if not placeholders:
            return
        for placeholder in placeholders:
            # Calls and messages are notes too. Their IDs remain unchanged so
            # contact history survives the handoff and retries stay idempotent.
            c.execute('UPDATE notes SET item_id=? WHERE item_id=?', (ident, placeholder))
            c.execute("UPDATE items SET state='DELETING',notes_text='' WHERE id=?", (placeholder,))
        notes = '\n'.join(row['author'] + ': ' + row['body'] for row in c.execute(
            'SELECT author,body FROM notes WHERE item_id=? ORDER BY created,id', (ident,)))
        c.execute('UPDATE items SET notes_text=?,search_revision=search_revision+1 WHERE id=?',
                  (notes, ident))

    def failed(self, ident, message, retry=False):
        with self.connect() as c:
            now = time.time()
            previous = c.execute('SELECT state,error FROM imports WHERE id=?', (ident,)).fetchone()
            state = 'WAITING' if retry else 'ERROR'
            c.execute('UPDATE imports SET state=?,error=?,updated=?,completed=? WHERE id=?',
                      (state, message[:1000], now, None if retry else now, ident))
            if previous and (previous['state'], previous['error']) != (state, message[:1000]):
                self._step(c, ident, now, message[:1000])

    def reset_for_reprocess(self, ident):
        """Queue a fresh run while keeping the last usable Gallery result in place."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT id,filename,state FROM imports WHERE id=?', (ident,)).fetchone()
            if not row:
                raise LookupError('This gallery job is unavailable.')
            if row['state'] not in ('COMPLETE', 'ERROR'):
                raise ValueError('Only completed or failed gallery jobs can be reprocessed.')
            now = time.time()
            message = ('Reprocess requested. Existing Gallery cards are being kept until '
                       'a fresh copy of the original email PDF finishes processing.')
            c.execute("""UPDATE imports SET state='ERROR',error=?,progress='{}',started=NULL,
                completed=NULL,updated=?,reprocess_pending=1 WHERE id=?""",
                      (message, now, ident))
            self._step(c, ident, now, message)
            return dict(id=ident, filename=row['filename'])

    def import_item(self, import_id, item_id):
        with self.connect() as c:
            row = c.execute("""SELECT id,import_id,page,part,bytes,document_date,date_status,
                    lead_name,lead_status,sales_lead_status,address,work_order_number,work_order_candidates,
                    work_order_reads,work_order_evidence,image_revision,mod_notes_status,
                    assigned_service_resource,reference_kind,reference_source_id,state FROM items
                WHERE id=? AND import_id=? AND state IN ('ACTIVE','REVIEW')""",
                (item_id, import_id)).fetchone()
            return self._recognition_view(row)

    def correct_import_item_lead(self, import_id, item_id, value, key):
        """Internal compatibility path; no Gallery UI exposes name editing."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("""SELECT page,part,state FROM items
                WHERE id=? AND import_id=? AND state IN ('ACTIVE','REVIEW')""",
                (item_id, import_id)).fetchone()
            if not row:
                raise LookupError('This generated card is unavailable.')
            c.execute("""UPDATE items
                SET lead_name=?,lead_key=?,lead_status='confirmed'
                WHERE id=? AND import_id=? AND state IN ('ACTIVE','REVIEW')""",
                (value, key, item_id, import_id))
            self._step(
                c, import_id, time.time(),
                f"Manually corrected lead name on page {row['page']} card {row['part']}."
            )
            return dict(row)

    def correct_import_item_work_order(self, import_id, item_id, number):
        """Correct one retained generated card's work-order identity."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("""SELECT page,part,state FROM items
                WHERE id=? AND import_id=? AND state IN ('ACTIVE','REVIEW')""",
                (item_id, import_id)).fetchone()
            if not row:
                raise LookupError('This generated card is unavailable.')
            c.execute("""UPDATE items SET
                text=?,work_order_number=?,work_order_key=?,work_order_candidates='[]',
                lead_name='',lead_key='',lead_status='needs-name',
                address='',address_key='',assigned_service_resource='',
                sales_lead_status='',lead_source_id='',reference_kind='',reference_source_id='',
                document_date=CASE WHEN origin='scan' AND date_status='reference' AND work_order_key!=?
                    THEN NULL ELSE document_date END,
                date_status=CASE WHEN origin='scan' AND date_status='reference' AND work_order_key!=?
                    THEN 'needs-date' ELSE date_status END,
                state=CASE WHEN mod_notes_status='unknown' THEN 'REVIEW' ELSE 'ACTIVE' END,
                search_revision=search_revision+1
                WHERE id=? AND import_id=? AND state IN ('ACTIVE','REVIEW')""",
                ('Work Order Number: ' + number, number, work_order_key(number),
                 work_order_key(number), work_order_key(number), item_id, import_id))
            day = c.execute('SELECT document_date FROM items WHERE id=?', (item_id,)).fetchone()['document_date']
            self._reconcile_morning_cards(c, item_id, day, work_order_key(number))
            self._step(
                c, import_id, time.time(),
                f"Manually corrected work order on page {row['page']} card {row['part']} to {number}."
            )
            return dict(row)

    def approve_import_item(self, import_id, item_id):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("""SELECT page,part,state,mod_notes_status,document_date,work_order_key FROM items
                WHERE id=? AND import_id=?""", (item_id, import_id)).fetchone()
            if not row or row['state'] not in ('ACTIVE','REVIEW'):
                raise LookupError('This generated card is unavailable.')
            if row['mod_notes_status'] == 'unknown':
                raise ValueError('MOD Notes could not be read. Reprocess this scan before publishing it.')
            if row['state'] == 'ACTIVE':
                return False
            c.execute("UPDATE items SET state='ACTIVE' WHERE id=? AND import_id=? AND state='REVIEW'",
                      (item_id, import_id))
            self._reconcile_morning_cards(c, item_id, row['document_date'], row['work_order_key'])
            self._step(c, import_id, time.time(),
                       f"Manual approval published page {row['page']} card {row['part']} to Gallery.")
            return True

    def claim_import_item_delete(self, import_id, item_id):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("""SELECT page,part,state FROM items
                WHERE id=? AND import_id=? AND state IN ('ACTIVE','REVIEW')""",
                (item_id, import_id)).fetchone()
            if not row:
                raise LookupError('This generated card is unavailable.')
            c.execute("UPDATE items SET state='DELETING' WHERE id=? AND import_id=?",
                      (item_id, import_id))
            return dict(row)

    def restore_import_item(self, import_id, item_id, state):
        if state not in ('ACTIVE','REVIEW'):
            return
        with self.connect() as c:
            c.execute("""UPDATE items SET state=CASE WHEN mod_notes_status='unknown' THEN 'REVIEW' ELSE ? END
                WHERE id=? AND import_id=? AND state='DELETING'""",
                      (state, item_id, import_id))

    def finish_import_item_delete(self, import_id, item_id, page, part):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("DELETE FROM items WHERE id=? AND import_id=? AND state='DELETING'",
                             (item_id, import_id)).rowcount:
                raise LookupError('This generated card is unavailable.')
            self._step(c, import_id, time.time(),
                       f'Manually deleted page {page} card {part} from this gallery job.')

    def set_state(self, value):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO meta VALUES('state',?)", (json.dumps(value),))

    def overview(self):
        with self.connect() as c:
            row = c.execute("SELECT value FROM meta WHERE key='state'").fetchone()
            result = json.loads(row[0]) if row else {}
            result.update(dict(c.execute('''SELECT count(*) AS count,coalesce(sum(bytes),0) AS image_bytes,
              coalesce(avg(bytes),0) AS average_bytes,sum(document_date IS NULL) AS undated,
              min(created) AS first_import FROM items WHERE state='ACTIVE' ''').fetchone()))
            result['waiting'] = c.execute("SELECT count(*) FROM imports WHERE state IN ('WAITING','PROCESSING')").fetchone()[0]
            result['recent'] = [dict(r) for r in c.execute('SELECT filename,state,error,count FROM imports WHERE filename!=? ORDER BY updated DESC LIMIT 8', ('',))]
            result['recent_crops'] = c.execute("SELECT count(*) FROM items WHERE created>=? AND state='ACTIVE'", (time.time()-7*86400,)).fetchone()[0]
            return result

    def list_items(self, expression='', offset=0, *, same_lead=None, document_date=''):
        clause = "WHERE i.state='ACTIVE'"
        params = []
        if same_lead is not None:
            clause += ' AND i.lead_key=? AND i.lead_key!=\'\''
            params.append(same_lead)
        if expression:
            clause += ' AND i.rowid IN (SELECT rowid FROM search WHERE search MATCH ?)'
            params.append(expression)
        with self.connect() as c:
            # Dates describe the complete search/related scope, not just this page
            # or selected day. Swipes must work beyond the 24-card pagination limit.
            c.execute('BEGIN')
            buckets = [dict(r) for r in c.execute(
                'SELECT i.document_date AS date,count(*) AS count FROM items i ' + clause +
                ' GROUP BY i.document_date ORDER BY i.document_date DESC', params)]
            if document_date == 'undated':
                clause += ' AND i.document_date IS NULL'
            elif document_date:
                clause += ' AND i.document_date=?'
                params.append(document_date)
            total = c.execute('SELECT count(*) FROM items i ' + clause, params).fetchone()[0]
            rows = c.execute('''SELECT i.id,i.filename,i.page,i.part,i.document_date,i.date_status,i.bytes,
               i.lead_name,i.lead_status,i.sales_lead_status,i.address,i.work_order_number,i.assigned_service_resource,
               i.origin,i.image_revision,i.search_revision,
               (SELECT count(*) FROM notes n WHERE n.item_id=i.id) AS notes_count FROM items i JOIN imports source ON source.id=i.import_id ''' + clause +
               ' ORDER BY i.document_date IS NULL,i.document_date DESC,source.created,source.id,i.page,i.part,i.id LIMIT 24 OFFSET ?', [*params, offset])
            return dict(total=total, items=[dict(r) for r in rows], dates=buckets)

    def offline_items(self):
        """Return the complete active-card index for an authorized offline sync."""
        with self.connect() as c:
            rows = c.execute(
                """SELECT i.id,i.filename,i.page,i.part,i.document_date,i.date_status,
                          i.bytes,i.lead_name,i.lead_status,i.sales_lead_status,i.address,
                          i.work_order_number,i.assigned_service_resource,i.origin,i.image_revision,i.search_revision,
                          (SELECT count(*) FROM notes n WHERE n.item_id=i.id) AS notes_count
                   FROM items i JOIN imports source ON source.id=i.import_id
                   WHERE i.state='ACTIVE'
                   ORDER BY i.document_date IS NULL,i.document_date DESC,
                            source.created,source.id,i.page,i.part,i.id"""
            )
            return [dict(row) for row in rows]

    def item(self, ident):
        with self.connect() as c:
            r = c.execute("SELECT * FROM items WHERE id=? AND state='ACTIVE'", (ident,)).fetchone()
            if r:
                result = dict(r)
                result['work_order_evidence'] = _work_order_evidence(result.get('work_order_evidence'))
                result['notes'] = [dict(n) for n in c.execute('SELECT id,author,body,created FROM notes WHERE item_id=? ORDER BY created,id', (ident,))]
                return result

    def add_note(self, ident, note_id, author, body):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("SELECT 1 FROM items WHERE id=? AND state='ACTIVE'", (ident,)).fetchone():
                raise LookupError('This image has expired or is unavailable.')
            existing = c.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
            if existing:
                if (existing['item_id'], existing['author'], existing['body']) != (ident, author, body):
                    raise ValueError('Conflicting note. Reload and try again.')
                return
            c.execute('INSERT INTO notes VALUES(?,?,?,?,?)', (note_id, ident, author, body, time.time()))
            c.execute('UPDATE items SET notes_text=notes_text || ? WHERE id=?', ('\n' + author + ': ' + body, ident))

    def related_candidates(self):
        with self.connect() as c:
            rows = c.execute("""SELECT i.id,i.filename,i.page,i.part,i.document_date,i.date_status,
                    i.bytes,i.lead_name,i.lead_key,i.lead_status,i.sales_lead_status,i.address,i.address_key,
                    i.work_order_number,i.work_order_key,i.assigned_service_resource,
                    i.origin,i.image_revision,i.search_revision,
                    source.created AS source_created,
                    (SELECT count(*) FROM notes n WHERE n.item_id=i.id) AS notes_count
                FROM items i JOIN imports source ON source.id=i.import_id
                WHERE i.state='ACTIVE'
                ORDER BY i.document_date IS NULL,i.document_date DESC,
                         source.created,source.id,i.page,i.part,i.id""")
            return [dict(row) for row in rows]

    def rename_leads(self, item_ids, value, key):
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            raise LookupError('No active related work orders are available.')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            changed = 0
            for ident in ids:
                changed += c.execute("""UPDATE items
                    SET lead_name=?,lead_key=?,lead_status='confirmed'
                    WHERE id=? AND state='ACTIVE'""", (value, key, ident)).rowcount
            if not changed:
                raise LookupError('No active related work orders are available.')
            return changed

    def rename_one_active_lead(self, ident, value, key):
        with self.connect() as c:
            changed = c.execute("""UPDATE items
                SET lead_name=?,lead_key=?,lead_status='confirmed'
                WHERE id=? AND state='ACTIVE'""", (value, key, ident)).rowcount
            if not changed:
                raise LookupError('This image has expired or is unavailable.')
            return changed

    def correct_lead(self, ident, value):
        with self.connect() as c:
            if not c.execute("UPDATE items SET lead_name=?,lead_key=?,lead_status='confirmed' WHERE id=? AND state='ACTIVE'",
                             (value, lead_key(value), ident)).rowcount:
                raise LookupError('This image has expired or is unavailable.')

    def correct_work_order(self, ident, number):
        """Replace one active card's work order and clear data tied to the old one."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("""UPDATE items SET
                    text=?,work_order_number=?,work_order_key=?,work_order_candidates='[]',
                    lead_name='',lead_key='',lead_status='needs-name',
                    address='',address_key='',assigned_service_resource='',
                    sales_lead_status='',lead_source_id='',reference_kind='',reference_source_id='',
                    document_date=CASE WHEN origin='scan' AND date_status='reference' AND work_order_key!=?
                        THEN NULL ELSE document_date END,
                    date_status=CASE WHEN origin='scan' AND date_status='reference' AND work_order_key!=?
                        THEN 'needs-date' ELSE date_status END,
                    search_revision=search_revision+1
                    WHERE id=? AND state='ACTIVE'""",
                    ('Work Order Number: ' + number, number, work_order_key(number),
                     work_order_key(number), work_order_key(number), ident)).rowcount:
                raise LookupError('This image has expired or is unavailable.')
            day = c.execute('SELECT document_date FROM items WHERE id=?', (ident,)).fetchone()['document_date']
            self._reconcile_morning_cards(c, ident, day, work_order_key(number))

    def correct_date(self, ident, value):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute("""UPDATE items SET
                    search_revision=search_revision+CASE WHEN document_date IS NOT ? THEN 1 ELSE 0 END,
                    document_date=?,date_status='confirmed'
                    WHERE id=? AND state='ACTIVE'""", (value, value, ident)).rowcount:
                raise LookupError('This image has expired or is unavailable.')
            key = c.execute('SELECT work_order_key FROM items WHERE id=?', (ident,)).fetchone()['work_order_key']
            self._reconcile_morning_cards(c, ident, value, key)

    def expiring(self, cutoff):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            # Return only rows claimed by this retention pass. Manual per-card
            # deletion uses the same DELETING state and must not be stolen by
            # concurrent retention cleanup.
            ids = [row['id'] for row in c.execute(
                "SELECT id FROM items WHERE state IN ('ACTIVE','REVIEW') AND document_date<=? LIMIT 100",
                (cutoff,))]
            if ids:
                c.executemany(
                    "UPDATE items SET state='DELETING' WHERE id=? AND state IN ('ACTIVE','REVIEW')",
                    [(ident,) for ident in ids])
            return ids

    def forget(self, ident):
        with self.connect() as c:
            c.execute("DELETE FROM items WHERE id=? AND state='DELETING'", (ident,))

    def housekeeping(self, cutoff):
        with self.connect() as c:
            # Hash-only import receipts survive retention, not PDF bytes or history.
            c.execute('''DELETE FROM import_steps WHERE import_id IN (SELECT id FROM imports
                WHERE updated<? AND state IN ('COMPLETE','ERROR')
                AND NOT EXISTS(SELECT 1 FROM items WHERE import_id=imports.id)
                AND NOT EXISTS(SELECT 1 FROM import_review_pages WHERE import_id=imports.id))''', (cutoff,))
            c.execute("""UPDATE imports SET filename='',error='',progress='{}'
                WHERE updated<? AND state IN ('COMPLETE','ERROR')
                AND NOT EXISTS(SELECT 1 FROM items WHERE import_id=imports.id)
                AND NOT EXISTS(SELECT 1 FROM import_review_pages WHERE import_id=imports.id)""", (cutoff,))
            c.execute("""DELETE FROM work_order_leads
                WHERE NOT EXISTS(SELECT 1 FROM items WHERE items.work_order_key=work_order_leads.work_order_key)
                AND NOT EXISTS(SELECT 1 FROM appointment_references
                    WHERE appointment_references.work_order_key=work_order_leads.work_order_key)""")
            c.execute("""DELETE FROM lead_status_snapshots
                WHERE NOT EXISTS(SELECT 1 FROM items WHERE items.lead_source_id=lead_status_snapshots.lead_source_id)
                AND NOT EXISTS(SELECT 1 FROM work_order_leads
                    WHERE work_order_leads.lead_source_id=lead_status_snapshots.lead_source_id)""")
        with self.connect() as c:
            c.execute('PRAGMA wal_checkpoint(PASSIVE)')

    @staticmethod
    def _step(c, ident, now, message):
        c.execute('INSERT INTO import_steps(import_id,at,message) VALUES (?,?,?)', (ident,now,message))
        # Bound diagnostics even if a source repeatedly fails or is retried.
        c.execute("""DELETE FROM import_steps WHERE import_id=? AND id NOT IN
            (SELECT id FROM import_steps WHERE import_id=? ORDER BY id DESC LIMIT 500)""", (ident,ident))

    def progress(self, ident, value):
        serialized = json.dumps(value, sort_keys=True)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT state,progress FROM imports WHERE id=?', (ident,)).fetchone()
            if not row or row['state'] != 'PROCESSING' or row['progress'] == serialized:
                return
            now = time.time()
            c.execute('UPDATE imports SET progress=?,updated=? WHERE id=?', (serialized,now,ident))
            self._step(c, ident, now, value['message'])

    @staticmethod
    def _import_row(row):
        result = dict(row)
        result['progress'] = json.loads(result['progress'])
        return result

    def import_queue(self, state='', offset=0, limit=25):
        with self.connect() as c:
            c.execute('BEGIN')
            counts = {r['state']:r['n'] for r in c.execute(
                "SELECT state,count(*) AS n FROM imports WHERE filename!='' GROUP BY state")}
            where, params = "WHERE filename!=''", []
            if state == 'pending':
                where += " AND state IN ('WAITING','PROCESSING')"
            elif state:
                where += ' AND state=?'; params.append(state)
            total = c.execute('SELECT count(*) FROM imports '+where, params).fetchone()[0]
            rows = c.execute("""SELECT imports.*,
                    (SELECT count(*) FROM items WHERE import_id=imports.id AND state='REVIEW') AS pending_review
                FROM imports """+where+
                " ORDER BY CASE WHEN state IN ('PROCESSING','WAITING') THEN 0 ELSE 1 END,updated DESC,id LIMIT ? OFFSET ?",
                (*params,limit,offset))
            result = dict(counts=counts,total=total,items=[self._import_row(row) for row in rows])
            result['review_total'] = c.execute(
                "SELECT count(*) FROM items WHERE state='REVIEW'").fetchone()[0]
            heartbeat = c.execute("SELECT value FROM meta WHERE key='state'").fetchone()
            result['worker'] = json.loads(heartbeat[0]) if heartbeat else {}
            return result

    def import_job(self, ident, offset=0):
        with self.connect() as c:
            c.execute('BEGIN')
            row = c.execute("SELECT * FROM imports WHERE id=? AND filename!=''", (ident,)).fetchone()
            if not row:
                return None
            result = self._import_row(row)
            result['steps'] = [dict(s) for s in c.execute(
                'SELECT at,message FROM import_steps WHERE import_id=? ORDER BY id', (ident,))]
            result['published'] = c.execute(
                "SELECT count(*) FROM items WHERE import_id=? AND state='ACTIVE'", (ident,)
            ).fetchone()[0]
            result['pending_review'] = c.execute(
                "SELECT count(*) FROM items WHERE import_id=? AND state='REVIEW'", (ident,)
            ).fetchone()[0]
            result['retained'] = result['published'] + result['pending_review']
            result['items'] = [self._recognition_view(i) for i in c.execute(
                """SELECT id,page,part,bytes,document_date,date_status,lead_name,sales_lead_status,
                    work_order_number,work_order_candidates,work_order_reads,work_order_evidence,
                    image_revision,mod_notes_status,reference_kind,state
                FROM items WHERE import_id=? AND state IN ('ACTIVE','REVIEW')
                ORDER BY CASE state WHEN 'REVIEW' THEN 0 ELSE 1 END,page,part,id LIMIT 24 OFFSET ?""",
                (ident,offset))]
            result['review_pages'] = [dict(page) for page in c.execute(
                """SELECT page,file_id,bytes,reason FROM import_review_pages
                    WHERE import_id=? ORDER BY page""", (ident,)
            )]
            return result

    def import_review_page(self, ident, page):
        with self.connect() as c:
            row = c.execute(
                """SELECT page,file_id,bytes,reason FROM import_review_pages
                    WHERE import_id=? AND page=?""", (ident, int(page))
            ).fetchone()
            return dict(row) if row else None

    def review_page_files(self, ident):
        with self.connect() as c:
            return [row['file_id'] for row in c.execute(
                'SELECT file_id FROM import_review_pages WHERE import_id=?', (ident,)
            )]

    def expiring_review_pages(self, cutoff):
        with self.connect() as c:
            return [dict(row) for row in c.execute(
                """SELECT p.import_id,p.page,p.file_id FROM import_review_pages p
                    JOIN imports i ON i.id=p.import_id
                    WHERE i.updated<? AND i.state IN ('COMPLETE','ERROR')
                    ORDER BY i.updated,p.page""", (float(cutoff),)
            )]

    def forget_review_page(self, import_id, page, file_id):
        with self.connect() as c:
            c.execute(
                'DELETE FROM import_review_pages WHERE import_id=? AND page=? AND file_id=?',
                (import_id, int(page), file_id),
            )

    def recognition_candidate(self, now):
        with self.connect() as c:
            row = c.execute("""SELECT id,text,lead_status,state,work_order_key,work_order_candidates,
                    work_order_evidence,image_revision,document_date,date_status,mod_notes_status FROM items
                WHERE recognition_attempts<3 AND recognition_retry_at<=? AND (
                    (state='ACTIVE' AND recognition_revision<1)
                    OR (state='REVIEW' AND work_order_key='' AND work_order_candidates='[]')
                    OR (state='REVIEW' AND mod_notes_status='unknown')
                )
                ORDER BY (state='ACTIVE'),(lead_key!=''),created,id LIMIT 1""",
                (now,)).fetchone()
            return self._recognition_view(row)

    def repair_recognition(
            self, ident, text, name, key, address, address_normalized,
            work_order_number='', work_order_normalized=''):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            # An edit/expiry during OCR wins. Notes, IDs, images, dates and print
            # receipts are not modified. The existing FTS trigger reindexes text.
            c.execute("""UPDATE items SET text=?,recognition_revision=1,
                recognition_attempts=0,recognition_retry_at=0,address=?,address_key=?,
                lead_source_id=CASE WHEN work_order_key!=? THEN '' ELSE lead_source_id END,
                sales_lead_status=CASE WHEN work_order_key!=? THEN '' ELSE sales_lead_status END,
                search_revision=search_revision+CASE WHEN work_order_key!=? THEN 1 ELSE 0 END,
                work_order_number=?,work_order_key=?,
                state=CASE WHEN ?!='' AND mod_notes_status!='unknown' THEN 'ACTIVE' ELSE state END,
                lead_name=CASE WHEN lead_status='confirmed' OR ?='' THEN lead_name ELSE ? END,
                lead_key=CASE WHEN lead_status='confirmed' OR ?='' THEN lead_key ELSE ? END,
                lead_status=CASE WHEN lead_status='confirmed' OR ?='' THEN lead_status ELSE 'printed' END
                WHERE id=? AND (
                    (state='ACTIVE' AND recognition_revision<1)
                    OR (state='REVIEW' AND work_order_key='' AND work_order_candidates='[]')
                )""",
                (text,address,address_normalized,work_order_normalized,work_order_normalized,work_order_normalized,
                 work_order_number,work_order_normalized,work_order_number,
                 name,name,name,key,name,ident))
            self._refresh_sales_lead_statuses(c, ' AND id=?', (ident,))

    def defer_recognition(self, ident, now):
        with self.connect() as c:
            c.execute("""UPDATE items SET recognition_attempts=recognition_attempts+1,
                recognition_retry_at=? WHERE id=? AND (
                    (state='ACTIVE' AND recognition_revision<1)
                    OR (state='REVIEW' AND (work_order_key='' OR mod_notes_status='unknown'))
                )""",
                (now+300,ident))


    def replace_reference_snapshot(self, day, kind, records, captured):
        """Replace one normalized snapshot atomically; shrinking is valid."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM appointment_references WHERE day=? AND kind=?', (day, kind))
            for record in records:
                resources = record.get('assigned_service_resources', ())
                c.execute("""INSERT INTO appointment_references(
                    day,kind,source_id,work_order_number,work_order_key,lead_name,lead_key,
                    address,address_key,phone,scheduled_start,assigned_service_resources,
                    product_interest,source,sub_source,local_scheduled_start_time,canvass_set_by,
                    set_by,work_type,lead_description)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    day, kind, record.get('source_id',''),
                    record.get('work_order_number',''), work_order_key(record.get('work_order_number','')),
                    record.get('lead_name',''), lead_key(record.get('lead_name','')),
                    record.get('address',''), address_key(record.get('address','')),
                    record.get('phone',''), record.get('scheduled_start',''),
                    json.dumps(list(resources)),
                    record.get('product_interest',''), record.get('source',''), record.get('sub_source',''),
                    record.get('local_scheduled_start_time',''), record.get('canvass_set_by',''),
                    record.get('set_by',''), record.get('work_type',''), record.get('lead_description',''),
                ))
            c.execute("""INSERT INTO appointment_reference_snapshots(day,kind,captured,count)
                VALUES (?,?,?,?) ON CONFLICT(day,kind) DO UPDATE SET
                captured=excluded.captured,count=excluded.count""",
                (day, kind, float(captured), len(records)))
            # Reference-derived contact data can change without changing OCR
            # text (for example, an exact match becoming ambiguous).
            c.execute("""UPDATE items SET search_revision=search_revision+1
                WHERE document_date=? AND state IN ('ACTIVE','REVIEW')""", (day,))

    def has_reference_snapshot(self, day, kind):
        """Distinguish an authoritative empty snapshot from one never received."""
        with self.connect() as c:
            return c.execute(
                'SELECT 1 FROM appointment_reference_snapshots WHERE day=? AND kind=?',
                (day, kind),
            ).fetchone() is not None

    def reference_snapshot(self, day, kind):
        with self.connect() as c:
            snap = c.execute(
                'SELECT day,kind,captured,count FROM appointment_reference_snapshots WHERE day=? AND kind=?',
                (day, kind),
            ).fetchone()
            rows = c.execute(
                'SELECT * FROM appointment_references WHERE day=? AND kind=? ORDER BY source_id',
                (day, kind),
            )
            result = []
            for row in rows:
                value = dict(row)
                value['assigned_service_resources'] = tuple(json.loads(value['assigned_service_resources']))
                result.append(value)
            return (dict(snap) if snap else None), result

    def reference_items(self, day):
        with self.connect() as c:
            return [dict(row) for row in c.execute("""SELECT id,text,document_date,lead_name,lead_key,
                address,address_key,work_order_number,work_order_key,assigned_service_resource,
                reference_kind,reference_source_id,sales_lead_status,lead_source_id,state
                FROM items WHERE state IN ('ACTIVE','REVIEW') AND (
                    document_date=? OR (document_date IS NULL AND work_order_key IN (
                        SELECT work_order_key FROM appointment_references
                        WHERE day=? AND work_order_key!=''
                    ))
                ) ORDER BY created,id""", (day, day))]

    def reference_identity_candidates(self, day, lead_name='', address='', include_phone=False):
        """Return normalized cached source rows that could identify one OCR card."""
        name = lead_key(lead_name)
        address_normalized = address_key(address)
        clauses = []
        params = []
        if day:
            clauses.append('day=?')
            params.append(day)
        if name:
            clauses.append('lead_key=?')
            params.append(name)
        if address_normalized:
            clauses.append('address_key=?')
            params.append(address_normalized)

        with self.connect() as c:
            if name or address_normalized:
                identity_parts = []
                identity_params = []
                if name:
                    identity_parts.append('lead_key=?')
                    identity_params.append(name)
                if address_normalized:
                    identity_parts.append('address_key=?')
                    identity_params.append(address_normalized)
                where = ('day=? AND ' if day else '') + '(' + ' OR '.join(identity_parts) + ')'
                query_params = ([day] if day else []) + identity_params
                rows = c.execute(
                    """SELECT * FROM appointment_references WHERE """ + where
                    + """ ORDER BY CASE kind WHEN 'final' THEN 0 ELSE 1 END,day DESC LIMIT 100""",
                    query_params,
                )
            elif include_phone and day:
                rows = c.execute(
                    """SELECT * FROM appointment_references
                    WHERE day=? AND phone!=''
                    ORDER BY CASE kind WHEN 'final' THEN 0 ELSE 1 END LIMIT 200""",
                    (day,),
                )
            else:
                return []

            result = []
            for row in rows:
                value = dict(row)
                value['assigned_service_resources'] = tuple(json.loads(value['assigned_service_resources']))
                result.append(value)
            return result

    def reference_matches(self, day, kind, number):
        """Read the indexed work-order candidates, using the latest day when undated."""
        with self.connect() as c:
            if day:
                rows = c.execute("""SELECT * FROM appointment_references
                    WHERE day=? AND kind=? AND work_order_key=? LIMIT 2""",
                    (day, kind, work_order_key(number)))
            else:
                rows = c.execute("""SELECT * FROM appointment_references
                    WHERE kind=? AND work_order_key=? AND day=(
                        SELECT max(day) FROM appointment_references
                        WHERE kind=? AND work_order_key=?
                    ) LIMIT 2""",
                    (kind, work_order_key(number), kind, work_order_key(number)))
            result = []
            for row in rows:
                value = dict(row)
                value['assigned_service_resources'] = tuple(json.loads(value['assigned_service_resources']))
                result.append(value)
            return result

    def reference_dates(self):
        with self.connect() as c:
            return [row['document_date'] for row in c.execute("""SELECT DISTINCT document_date
                FROM items WHERE state IN ('ACTIVE','REVIEW') AND document_date IS NOT NULL
                ORDER BY document_date""")]

    def reference_item(self, ident):
        with self.connect() as c:
            row = c.execute("""SELECT id,text,document_date,date_status,lead_name,lead_key,address,address_key,
                work_order_number,work_order_key,assigned_service_resource,reference_kind,
                reference_source_id,sales_lead_status,lead_source_id,state,origin,
                work_order_evidence,image_revision,mod_notes_status FROM items
                WHERE id=? AND state IN ('ACTIVE','REVIEW')""", (ident,)).fetchone()
            if row:
                result = dict(row)
                result['work_order_evidence'] = _work_order_evidence(result.get('work_order_evidence'))
                return result

    def work_order_items(self, number):
        """All retained cards carrying this exact normalized work-order identity."""
        key = work_order_key(number)
        if not key:
            return []
        with self.connect() as c:
            return [dict(row) for row in c.execute("""SELECT id,text,document_date,date_status,lead_name,address,
                    work_order_number,work_order_key,assigned_service_resource,state
                FROM items WHERE work_order_key=? AND state IN ('ACTIVE','REVIEW')
                ORDER BY created,id""", (key,))]

    def apply_work_order_reference(self, ident, expected_work_order_key, source_id, text, name,
                                   address, assigned_resource, appointment_date,
                                   lead_source_id, sales_lead_status):
        """Apply authoritative normalized source data resolved directly by work order."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT document_date,origin FROM items WHERE id=?', (ident,)).fetchone()
            changed = c.execute("""UPDATE items SET
                search_revision=search_revision+1,
                state='ACTIVE',
                document_date=CASE WHEN coalesce(document_date,'')='' AND ?!='' THEN ? ELSE document_date END,
                date_status=CASE WHEN coalesce(document_date,'')='' AND ?!='' THEN 'reference' ELSE date_status END,
                assigned_service_resource=coalesce(?,assigned_service_resource),
                reference_kind='work-order',reference_source_id=?,text=?,
                lead_name=CASE WHEN ?='' THEN lead_name ELSE ? END,
                lead_key=CASE WHEN ?='' THEN lead_key ELSE ? END,
                lead_status=CASE WHEN ?='' THEN lead_status ELSE 'printed' END,
                address=CASE WHEN ?='' THEN address ELSE ? END,
                address_key=CASE WHEN ?='' THEN address_key ELSE ? END,
                lead_source_id=?,sales_lead_status=?
                WHERE id=? AND state IN ('ACTIVE','REVIEW') AND work_order_key=?
                AND mod_notes_status!='unknown'""",
                (appointment_date, appointment_date, appointment_date,
                 assigned_resource, source_id, text,
                 name, name, name, lead_key(name), name,
                 address, address, address, address_key(address),
                 lead_source_id, sales_lead_status, ident, expected_work_order_key)).rowcount
            if changed and row['origin'] == 'scan':
                self._reconcile_morning_cards(c, ident, row['document_date'], expected_work_order_key)
            return changed

    def sales_status_for_lead(self, lead_source_id):
        with self.connect() as c:
            row = c.execute('SELECT sales_lead_status FROM lead_status_snapshots WHERE lead_source_id=?',
                            (lead_source_id,)).fetchone()
            return row['sales_lead_status'] if row else ''

    def missing_work_order_items(self):
        with self.connect() as c:
            return [dict(row) for row in c.execute("""SELECT id,text,work_order_number,work_order_key,
                    work_order_candidates,state
                FROM items WHERE state IN ('ACTIVE','REVIEW') AND sales_lead_status=''
                ORDER BY id""")]

    def repair_missing_work_order(self, item, number):
        """Reparse one unchanged unresolved card without touching its other content."""
        if item.get('work_order_candidates') not in (None, '', '[]'):
            return 0
        if number == item['work_order_number']:
            return 0
        with self.connect() as c:
            return c.execute("""UPDATE items SET work_order_number=?,work_order_key=?,
                lead_source_id='',sales_lead_status='',search_revision=search_revision+1,
                state=CASE WHEN ?='' THEN 'REVIEW' ELSE state END
                WHERE id=? AND state IN ('ACTIVE','REVIEW') AND sales_lead_status=''
                AND text=? AND work_order_number=? AND work_order_key=? AND state=?""",
                (number, work_order_key(number), number, item['id'], item['text'],
                 item['work_order_number'], item['work_order_key'], item['state'])).rowcount

    def work_order_numbers(self, *, missing_only=False):
        """All retained cards, with no appointment date requirement."""
        with self.connect() as c:
            rows = c.execute("""SELECT work_order_key,min(work_order_number) AS number
                FROM items WHERE state IN ('ACTIVE','REVIEW') AND work_order_key!=''"""
                + (" AND sales_lead_status=''" if missing_only else '')
                + ' GROUP BY work_order_key ORDER BY work_order_key')
            return [row['number'] for row in rows]

    def work_order_lookup_numbers(self):
        """Accepted work orders plus OCR candidates waiting for source validation."""
        with self.connect() as c:
            rows = c.execute("""SELECT work_order_number,work_order_candidates
                FROM items WHERE state IN ('ACTIVE','REVIEW')
                AND (work_order_key!='' OR work_order_candidates!='[]')""")
            values = {}
            for row in rows:
                if row['work_order_number']:
                    values.setdefault(work_order_key(row['work_order_number']), row['work_order_number'])
                try:
                    candidates = json.loads(row['work_order_candidates'])
                except (TypeError, ValueError, json.JSONDecodeError):
                    candidates = []
                for candidate in candidates if isinstance(candidates, list) else ():
                    if isinstance(candidate, str) and len(candidate) == 8 and candidate.isascii() and candidate.isdecimal():
                        values.setdefault(work_order_key(candidate), candidate)
            return [values[key] for key in sorted(values)]

    def work_order_candidate_items(self):
        """Cards waiting for one source-confirmed OCR work-order candidate."""
        with self.connect() as c:
            result = []
            for row in c.execute("""SELECT id,text,work_order_candidates,work_order_evidence,
                    image_revision,document_date,date_status,mod_notes_status,state
                FROM items WHERE state='REVIEW' AND work_order_key='' AND work_order_candidates!='[]'
                ORDER BY created,id"""):
                value = dict(row)
                value['work_order_evidence'] = _work_order_evidence(value.get('work_order_evidence'))
                try:
                    candidates = json.loads(value['work_order_candidates'])
                except (TypeError, ValueError, json.JSONDecodeError):
                    candidates = []
                value['candidates'] = tuple(
                    candidate for candidate in candidates if isinstance(candidate, str)
                    and len(candidate) == 8 and candidate.isascii() and candidate.isdecimal()
                )
                result.append(value)
            return result

    def save_work_order_candidates(self, ident, candidates, *, expected_text=None, reads=(),
                                   evidence=_UNSET, expected_image_revision=None):
        """Persist one completed multi-read OCR result without accepting its identity."""
        clean = tuple(dict.fromkeys(
            value for value in candidates if isinstance(value, str)
            and len(value) == 8 and value.isascii() and value.isdecimal()
        ))
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("""SELECT text,work_order_evidence,image_revision FROM items
                WHERE id=? AND work_order_key=''
                AND work_order_candidates='[]' AND (state='REVIEW'
                    OR (state='ACTIVE' AND recognition_revision<1))""", (ident,)).fetchone()
            if not row or (expected_text is not None and row['text'] != expected_text):
                return 0
            if expected_image_revision is not None and row['image_revision'] != expected_image_revision:
                return 0
            saved_evidence = (row['work_order_evidence'] if evidence is _UNSET else
                              json.dumps(normalize_work_order_evidence(evidence)))
            return c.execute("""UPDATE items SET text=?,state='REVIEW',work_order_candidates=?,
                work_order_reads=?,work_order_evidence=?,recognition_revision=1,
                search_revision=search_revision+1,
                recognition_attempts=CASE WHEN ? THEN 0 ELSE recognition_attempts+1 END,
                recognition_retry_at=? WHERE id=?""",
                (clear_work_order_identity(row['text']), json.dumps(clean), json.dumps(_work_order_reads(reads)),
                 saved_evidence,
                 bool(clean), 0 if clean else time.time() + 300, ident)).rowcount

    def apply_validated_work_order_reference(
            self, ident, expected_candidates, number, source_id, text, name, address,
            assigned_resource, appointment_date, lead_source_id, sales_lead_status, *,
            expected_evidence=_UNSET, expected_image_revision=None):
        """Atomically accept one OCR candidate only after the source resolved it."""
        serialized = json.dumps(list(expected_candidates))
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT work_order_evidence,image_revision,document_date,origin FROM items WHERE id=?',
                            (ident,)).fetchone()
            if not row:
                return 0
            if expected_image_revision is not None and row['image_revision'] != expected_image_revision:
                return 0
            if (expected_evidence is not _UNSET and
                    _work_order_evidence(row['work_order_evidence']) !=
                    normalize_work_order_evidence(expected_evidence)):
                return 0
            changed = c.execute("""UPDATE items SET
                search_revision=search_revision+1,state='ACTIVE',
                work_order_number=?,work_order_key=?,work_order_candidates='[]',
                document_date=CASE WHEN coalesce(document_date,'')='' AND ?!='' THEN ? ELSE document_date END,
                date_status=CASE WHEN coalesce(document_date,'')='' AND ?!='' THEN 'reference' ELSE date_status END,
                assigned_service_resource=coalesce(?,assigned_service_resource),
                reference_kind='work-order',reference_source_id=?,text=?,
                lead_name=CASE WHEN ?='' THEN lead_name ELSE ? END,
                lead_key=CASE WHEN ?='' THEN lead_key ELSE ? END,
                lead_status=CASE WHEN ?='' THEN lead_status ELSE 'printed' END,
                address=CASE WHEN ?='' THEN address ELSE ? END,
                address_key=CASE WHEN ?='' THEN address_key ELSE ? END,
                lead_source_id=?,sales_lead_status=?
                WHERE id=? AND state='REVIEW' AND work_order_key='' AND work_order_candidates=?
                AND mod_notes_status!='unknown'""",
                (number, work_order_key(number),
                 appointment_date, appointment_date, appointment_date,
                 assigned_resource, source_id, text,
                 name, name, name, lead_key(name), name,
                 address, address, address, address_key(address),
                 lead_source_id, sales_lead_status, ident, serialized)).rowcount
            if changed and row['origin'] == 'scan':
                self._reconcile_morning_cards(c, ident, row['document_date'], work_order_key(number))
            return changed

    def replace_work_order_lead_statuses(self, work_order_numbers, records, captured, *, missing_only=False):
        """Publish one completed direct lookup; absent or ambiguous orders lose their mapping."""
        requested = {work_order_key(number) for number in work_order_numbers} - {''}
        matches = {key: [] for key in requested}
        for record in records:
            key = work_order_key(record.get('work_order_number', ''))
            if key in matches:
                matches[key].append(record)
        captured = float(captured)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            statuses_by_lead = {}
            for key, rows in matches.items():
                lead_ids = {row.get('lead_source_id', '') for row in rows}
                lead_id = next(iter(lead_ids)) if len(lead_ids) == 1 else ''
                c.execute("""INSERT INTO work_order_leads(work_order_key,lead_source_id,captured)
                    VALUES (?,?,?) ON CONFLICT(work_order_key) DO UPDATE SET
                    lead_source_id=CASE
                        WHEN excluded.captured>work_order_leads.captured THEN excluded.lead_source_id
                        WHEN excluded.lead_source_id=work_order_leads.lead_source_id
                            THEN work_order_leads.lead_source_id
                        ELSE '' END,
                    captured=excluded.captured
                    WHERE excluded.captured>=work_order_leads.captured""", (key, lead_id, captured))
                if lead_id:
                    statuses_by_lead.setdefault(lead_id, set()).update(
                        row.get('sales_lead_status', '') for row in rows)
            for lead_id, statuses in statuses_by_lead.items():
                status = next(iter(statuses)) if len(statuses) == 1 else ''
                c.execute("""INSERT INTO lead_status_snapshots(lead_source_id,sales_lead_status,captured)
                    VALUES (?,?,?) ON CONFLICT(lead_source_id) DO UPDATE SET
                    sales_lead_status=CASE
                        WHEN excluded.captured>lead_status_snapshots.captured THEN excluded.sales_lead_status
                        WHEN excluded.sales_lead_status=lead_status_snapshots.sales_lead_status
                            THEN lead_status_snapshots.sales_lead_status
                        ELSE '' END,
                    captured=excluded.captured
                    WHERE excluded.captured>=lead_status_snapshots.captured""", (lead_id, status, captured))
            return self._refresh_sales_lead_statuses(c, " AND sales_lead_status=''" if missing_only else '')

    @staticmethod
    def _refresh_sales_lead_statuses(c, guard='', parameters=()):
        # A cached empty mapping is authoritative. No cache entry preserves the
        # legacy association until its first successful direct lookup completes.
        lead = """coalesce((SELECT lead_source_id FROM work_order_leads
            WHERE work_order_key=items.work_order_key),items.lead_source_id)"""
        status = f"""coalesce((SELECT sales_lead_status FROM lead_status_snapshots
            WHERE lead_source_id={lead}),CASE WHEN EXISTS(SELECT 1 FROM work_order_leads
                WHERE work_order_key=items.work_order_key) THEN '' ELSE items.sales_lead_status END)"""
        return c.execute(f"""UPDATE items SET lead_source_id={lead},sales_lead_status={status},
            search_revision=search_revision+1 WHERE state IN ('ACTIVE','REVIEW')
            AND (lead_source_id!={lead} OR sales_lead_status!={status})""" + guard, parameters).rowcount

    def apply_reference(self, ident, source_id, kind, assigned_resource, text, name, address,
                        *, reference_day='', expected_day=_UNSET,
                        expected_work_order_key=_UNSET):
        guard, parameters = '', []
        if expected_day is not _UNSET:
            guard += ' AND document_date IS ?'
            parameters.append(expected_day)
        if expected_work_order_key is not _UNSET:
            guard += ' AND work_order_key=?'
            parameters.append(expected_work_order_key)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return c.execute("""UPDATE items SET
                search_revision=search_revision+CASE
                    WHEN text!=? OR (document_date IS NULL AND ?!='') THEN 1 ELSE 0 END,
                document_date=CASE WHEN document_date IS NULL AND ?!='' THEN ? ELSE document_date END,
                date_status=CASE WHEN document_date IS NULL AND ?!='' THEN 'reference' ELSE date_status END,
                assigned_service_resource=?,reference_kind=?,
                reference_source_id=?,text=?,
                lead_name=CASE WHEN ?='' THEN lead_name ELSE ? END,
                lead_key=CASE WHEN ?='' THEN lead_key ELSE ? END,
                lead_status=CASE WHEN ?='' OR lead_name=? THEN lead_status ELSE 'printed' END,
                address=CASE WHEN ?='' THEN address ELSE ? END,
                address_key=CASE WHEN ?='' THEN address_key ELSE ? END
                WHERE id=? AND state IN ('ACTIVE','REVIEW')
                AND (text!=? OR (document_date IS NULL AND ?!='')
                     OR assigned_service_resource!=? OR reference_kind!=? OR reference_source_id!=?
                     OR (?!='' AND lead_name!=?) OR (?!='' AND address!=?))""" + guard,
                (text, reference_day, reference_day, reference_day, reference_day,
                 assigned_resource, kind, source_id, text,
                 name, name, name, lead_key(name), name, name,
                 address, address, address, address_key(address), ident,
                 text, reference_day, assigned_resource, kind, source_id, name, name, address, address,
                 *parameters)).rowcount

    def refresh_sales_lead_status(self, ident, *, expected_work_order_key=_UNSET):
        """Attach the current work order's cached Lead and latest shared status."""
        guard, parameters = ' AND id=?', [ident]
        if expected_work_order_key is not _UNSET:
            guard += ' AND work_order_key=?'
            parameters.append(expected_work_order_key)
        with self.connect() as c:
            return self._refresh_sales_lead_statuses(c, guard, parameters)
