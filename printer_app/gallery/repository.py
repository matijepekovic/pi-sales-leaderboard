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
            columns = {row['name'] for row in c.execute('PRAGMA table_info(items)')}
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
            c.execute('''INSERT INTO imports(id,filename,created,updated) VALUES(?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET state='WAITING',updated=excluded.updated,error=''
              WHERE imports.state='ERROR' ''', (ident, filename[:150], now, now))

    def recover(self):
        with self.connect() as c:
            c.execute("UPDATE imports SET state='WAITING' WHERE state='PROCESSING'")

    def claim(self):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute("SELECT * FROM imports WHERE state='WAITING' ORDER BY created LIMIT 1").fetchone()
            if row:
                c.execute("UPDATE imports SET state='PROCESSING',updated=? WHERE id=?", (time.time(), row['id']))
                return dict(row)

    def finish(self, ident, items, warning=''):
        with self.connect() as c:
            for item in items:
                name = printed_lead(item['text'])
                c.execute('''INSERT OR IGNORE INTO items(id,import_id,page,part,filename,text,document_date,date_status,bytes,created,lead_name,lead_key,lead_status)
                    VALUES (:id,:import_id,:page,:part,:filename,:text,:document_date,:date_status,:bytes,:created,:lead_name,:lead_key,:lead_status)''',
                    dict(item, lead_name=name, lead_key=lead_key(name), lead_status='printed' if name else 'needs-name'))
            c.execute("UPDATE imports SET state='COMPLETE',count=?,error=?,updated=? WHERE id=?",
                      (len(items), warning[:1000], time.time(), ident))

    def failed(self, ident, message, retry=False):
        with self.connect() as c:
            c.execute('UPDATE imports SET state=?,error=?,updated=? WHERE id=?',
                      ('WAITING' if retry else 'ERROR', message[:1000], time.time(), ident))

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

    def list_items(self, expression='', offset=0, *, same_lead=None):
        clause = "WHERE i.state='ACTIVE'"
        params = []
        if same_lead is not None:
            clause += ' AND i.lead_key=? AND i.lead_key!=\'\''
            params.append(same_lead)
        if expression:
            clause += ' AND i.rowid IN (SELECT rowid FROM search WHERE search MATCH ?)'
            params.append(expression)
        with self.connect() as c:
            total = c.execute('SELECT count(*) FROM items i ' + clause, params).fetchone()[0]
            rows = c.execute('''SELECT i.id,i.filename,i.page,i.part,i.document_date,i.date_status,i.bytes,i.lead_name,i.lead_status,
               (SELECT count(*) FROM notes n WHERE n.item_id=i.id) AS notes_count FROM items i ''' + clause +
               ' ORDER BY i.document_date IS NULL,i.document_date DESC,i.created DESC,i.id LIMIT 24 OFFSET ?', [*params, offset])
            return dict(total=total, items=[dict(r) for r in rows])

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
            c.execute("UPDATE imports SET filename='',error='' WHERE updated<? AND state IN ('COMPLETE','ERROR') AND NOT EXISTS(SELECT 1 FROM items WHERE import_id=imports.id)", (cutoff,))
        with self.connect() as c:
            c.execute('PRAGMA wal_checkpoint(PASSIVE)')
