"""The gallery's SQLite schema, search index, import receipts, and notes."""
import json
import sqlite3
import time
from contextlib import contextmanager

from .policy import lead_key, printed_lead

SCHEMA = '''
CREATE TABLE IF NOT EXISTS imports (
 id TEXT PRIMARY KEY, filename TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'WAITING',
 created REAL NOT NULL, updated REAL NOT NULL, error TEXT NOT NULL DEFAULT '', count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS import_steps (
 id INTEGER PRIMARY KEY, import_id TEXT NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
 at REAL NOT NULL, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS gallery_import_steps ON import_steps(import_id,id);
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
'''


class GalleryRepository:
    def __init__(self, path):
        self.path = path

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
            for name, definition in (('progress', "TEXT NOT NULL DEFAULT '{}'"), ('started', 'REAL'), ('completed', 'REAL')):
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
            c.execute('CREATE INDEX IF NOT EXISTS gallery_items_lead ON items(state,lead_key,document_date)')
            if 'lead_name' not in {row['name'] for row in c.execute('PRAGMA table_info(search)')}:
                # Replace the one search index, not a parallel implementation.
                for event in ('insert', 'delete', 'update'):
                    c.execute('DROP TRIGGER IF EXISTS gallery_' + event)
                c.execute('DROP TABLE search')
                c.execute("""CREATE VIRTUAL TABLE search USING fts5(text,notes_text,filename,lead_name,
                    content='items',content_rowid='rowid',
                    tokenize='unicode61 remove_diacritics 2',prefix='2 3 4')""")
                add = 'INSERT INTO search(rowid,text,notes_text,filename,lead_name) VALUES(new.rowid,new.text,new.notes_text,new.filename,new.lead_name);'
                remove = "INSERT INTO search(search,rowid,text,notes_text,filename,lead_name) VALUES('delete',old.rowid,old.text,old.notes_text,old.filename,old.lead_name);"
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

    def import_state(self, ident):
        with self.connect() as c:
            row = c.execute('SELECT state FROM imports WHERE id=?', (ident,)).fetchone()
            return row['state'] if row else None

    def imported(self, ident):
        with self.connect() as c:
            row = c.execute('SELECT state FROM imports WHERE id=?', (ident,)).fetchone()
            return bool(row and row['state'] != 'ERROR')

    def enqueue(self, ident, filename):
        now = time.time()
        with self.connect() as c:
            changed = c.execute('''INSERT INTO imports(id,filename,created,updated) VALUES(?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET state='WAITING',updated=excluded.updated,error='',
                filename=excluded.filename,progress='{}',started=NULL,completed=NULL
              WHERE imports.state='ERROR' ''', (ident, filename[:150], now, now)).rowcount
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

    def finish(self, ident, items, warning=''):
        with self.connect() as c:
            for item in items:
                name = printed_lead(item.get('lead_text') or item['text'])
                c.execute('''INSERT OR IGNORE INTO items(id,import_id,page,part,filename,text,document_date,date_status,bytes,created,lead_name,lead_key,lead_status,recognition_revision)
                    VALUES (:id,:import_id,:page,:part,:filename,:text,:document_date,:date_status,:bytes,:created,:lead_name,:lead_key,:lead_status,:recognition_revision)''',
                    dict(item, lead_name=name, lead_key=lead_key(name), lead_status='printed' if name else 'needs-name',
                         recognition_revision=item.get('recognition_revision', 0)))
            now = time.time()
            c.execute("UPDATE imports SET state='COMPLETE',count=?,error=?,updated=?,completed=? WHERE id=?",
                      (len(items), warning[:1000], now, now, ident))
            self._step(c, ident, now, f'Import completed: {len(items)} work-order image(s) saved.')
            if warning:
                self._step(c, ident, now, warning[:1000])

    def failed(self, ident, message, retry=False):
        with self.connect() as c:
            now = time.time()
            previous = c.execute('SELECT state,error FROM imports WHERE id=?', (ident,)).fetchone()
            state = 'WAITING' if retry else 'ERROR'
            c.execute('UPDATE imports SET state=?,error=?,updated=?,completed=? WHERE id=?',
                      (state, message[:1000], now, None if retry else now, ident))
            if previous and (previous['state'], previous['error']) != (state, message[:1000]):
                self._step(c, ident, now, message[:1000])

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
            rows = c.execute('''SELECT i.id,i.filename,i.page,i.part,i.document_date,i.date_status,i.bytes,i.lead_name,i.lead_status,
               (SELECT count(*) FROM notes n WHERE n.item_id=i.id) AS notes_count FROM items i JOIN imports source ON source.id=i.import_id ''' + clause +
               ' ORDER BY i.document_date IS NULL,i.document_date DESC,source.created,source.id,i.page,i.part,i.id LIMIT 24 OFFSET ?', [*params, offset])
            return dict(total=total, items=[dict(r) for r in rows], dates=buckets)

    def item(self, ident):
        with self.connect() as c:
            r = c.execute("SELECT * FROM items WHERE id=? AND state='ACTIVE'", (ident,)).fetchone()
            if r:
                result = dict(r)
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

    def correct_lead(self, ident, value):
        with self.connect() as c:
            if not c.execute("UPDATE items SET lead_name=?,lead_key=?,lead_status='confirmed' WHERE id=? AND state='ACTIVE'",
                             (value, lead_key(value), ident)).rowcount:
                raise LookupError('This image has expired or is unavailable.')

    def correct_date(self, ident, value):
        with self.connect() as c:
            if not c.execute("UPDATE items SET document_date=?,date_status='confirmed' WHERE id=? AND state='ACTIVE'", (value, ident)).rowcount:
                raise LookupError('This image has expired or is unavailable.')

    def expiring(self, cutoff):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            # Once claimed, date edits fail rather than racing a file deletion.
            c.execute("UPDATE items SET state='DELETING' WHERE id IN (SELECT id FROM items WHERE state='ACTIVE' AND document_date<=? LIMIT 100)", (cutoff,))
            return [r[0] for r in c.execute("SELECT id FROM items WHERE state='DELETING'")]

    def forget(self, ident):
        with self.connect() as c:
            c.execute("DELETE FROM items WHERE id=? AND state='DELETING'", (ident,))

    def housekeeping(self, cutoff):
        with self.connect() as c:
            # Hash-only import receipts survive retention, not PDF bytes or history.
            c.execute('''DELETE FROM import_steps WHERE import_id IN (SELECT id FROM imports
                WHERE updated<? AND state IN ('COMPLETE','ERROR')
                AND NOT EXISTS(SELECT 1 FROM items WHERE import_id=imports.id))''', (cutoff,))
            c.execute("UPDATE imports SET filename='',error='',progress='{}' WHERE updated<? AND state IN ('COMPLETE','ERROR') AND NOT EXISTS(SELECT 1 FROM items WHERE import_id=imports.id)", (cutoff,))
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
            rows = c.execute('SELECT * FROM imports '+where+
                " ORDER BY CASE WHEN state IN ('PROCESSING','WAITING') THEN 0 ELSE 1 END,updated DESC,id LIMIT ? OFFSET ?",
                (*params,limit,offset))
            result = dict(counts=counts,total=total,items=[self._import_row(row) for row in rows])
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
            result['retained'] = c.execute("SELECT count(*) FROM items WHERE import_id=? AND state='ACTIVE'", (ident,)).fetchone()[0]
            result['items'] = [dict(i) for i in c.execute("""SELECT id,page,part,bytes,document_date,date_status,lead_name
                FROM items WHERE import_id=? AND state='ACTIVE' ORDER BY page,part,id LIMIT 24 OFFSET ?""", (ident,offset))]
            return result


    def recognition_candidate(self, now):
        with self.connect() as c:
            row = c.execute("""SELECT id,text,lead_status FROM items WHERE state='ACTIVE'
                AND recognition_revision<1 AND recognition_attempts<3 AND recognition_retry_at<=?
                ORDER BY (lead_key!=''),created,id LIMIT 1""", (now,)).fetchone()
            return dict(row) if row else None

    def repair_recognition(self, ident, text, name, key):
        with self.connect() as c:
            # An edit/expiry during OCR wins. Notes, IDs, images, dates and print
            # receipts are not modified. The existing FTS trigger reindexes text.
            c.execute("""UPDATE items SET text=?,recognition_revision=1,
                recognition_attempts=0,recognition_retry_at=0,
                lead_name=CASE WHEN lead_status='confirmed' OR ?='' THEN lead_name ELSE ? END,
                lead_key=CASE WHEN lead_status='confirmed' OR ?='' THEN lead_key ELSE ? END,
                lead_status=CASE WHEN lead_status='confirmed' OR ?='' THEN lead_status ELSE 'printed' END
                WHERE id=? AND state='ACTIVE' AND recognition_revision<1""",
                (text,name,name,name,key,name,ident))

    def defer_recognition(self, ident, now):
        with self.connect() as c:
            c.execute("""UPDATE items SET recognition_attempts=recognition_attempts+1,
                recognition_retry_at=? WHERE id=? AND state='ACTIVE' AND recognition_revision<1""",
                (now+300,ident))
