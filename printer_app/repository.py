"""The only business-data SQL owner, shared by this app's web and worker processes."""
import json
import time
import uuid
from .db import connect
from .contracts import Message


class Repository:
    def __init__(self, path):
        self.path = path

    def healthy(self):
        with connect(self.path) as c:
            return c.execute("SELECT 1").fetchone()[0] == 1

    def seen(self, source_key):
        with connect(self.path) as c:
            return c.execute("SELECT 1 FROM processed_messages WHERE source_key=?", (source_key,)).fetchone() is not None

    def ingest(self, message: Message):
        with connect(self.path) as c:
            cursor = c.execute(
                "INSERT OR IGNORE INTO processed_messages(source_key,scope,uid,uid_validity,message_id,subject,sender,created) VALUES(?,?,?,?,?,?,?,?)",
                (message.source_key, message.scope, message.uid, message.uid_validity, message.message_id, message.subject, message.sender, time.time()))
            if not cursor.rowcount:
                return False
            for index, a in enumerate(message.attachments):
                c.execute("INSERT INTO attachments(message_id,ordinal,filename,path,sha256,size) VALUES(?,?,?,?,?,?)",
                          (cursor.lastrowid, index, a.filename, str(a.path), a.sha256, a.size))
            return True

    def pending_attachments(self):
        with connect(self.path) as c:
            return [dict(r) for r in c.execute(
                "SELECT a.*,m.subject,m.sender FROM attachments a JOIN processed_messages m ON m.id=a.message_id WHERE a.state!='DONE' ORDER BY a.id")]

    def finish_attachment(self, attachment_id):
        with connect(self.path) as c:
            c.execute("UPDATE attachments SET state='DONE' WHERE id=?", (attachment_id,))

    def job(self, attachment, key, substatus="", job_id=None):
        identity = job_id or uuid.uuid5(uuid.NAMESPACE_URL, f"printer:{attachment['id']}:{key}").hex
        now = time.time()
        with connect(self.path) as c:
            c.execute("INSERT OR IGNORE INTO jobs(id,attachment_id,group_key,substatus,filename,subject,sender,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
                      (identity, attachment.get('id'), key, substatus, attachment['filename'], attachment['subject'], attachment['sender'], now, now))
            return dict(c.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone())

    def set_job(self, job_id, state, error=None, failure_kind=None, page_count=None):
        with connect(self.path) as c:
            c.execute("UPDATE jobs SET state=?,error=COALESCE(?,error),failure_kind=COALESCE(?,failure_kind),page_count=COALESCE(?,page_count),updated=? WHERE id=?",
                      (state, error, failure_kind, page_count, time.time(), job_id))

    def step(self, job_id, detail):
        with connect(self.path) as c:
            c.execute("INSERT INTO steps(job_id,at,detail) VALUES(?,?,?)", (job_id, time.time(), detail[:8000]))

    def add_output(self, job_id, kind, path, pages, printable=False, tabloid=False):
        identity = uuid.uuid5(uuid.NAMESPACE_URL, f"printer-output:{job_id}:{kind}").hex
        with connect(self.path) as c:
            c.execute("INSERT OR IGNORE INTO outputs(id,job_id,kind,path,page_count,state,tabloid) VALUES(?,?,?,?,?,?,?)",
                      (identity, job_id, kind, str(path), pages, 'READY' if printable else 'PREVIEW', int(tabloid)))
        return identity

    def outputs(self, job_id=None):
        with connect(self.path) as c:
            if job_id is not None:
                rows = c.execute("SELECT * FROM outputs WHERE job_id=? ORDER BY rowid", (job_id,))
            else:
                rows = c.execute("SELECT * FROM outputs WHERE state IN ('READY','RETRY','SUBMITTING','UNCERTAIN','SUBMITTED') ORDER BY rowid")
            return [dict(r) for r in rows]

    def output(self, output_id):
        with connect(self.path) as c:
            r = c.execute("SELECT * FROM outputs WHERE id=?", (output_id,)).fetchone()
            return dict(r) if r else None

    def set_output(self, identity, state, request_id=None, delay=0):
        with connect(self.path) as c:
            c.execute("UPDATE outputs SET state=?,request_id=COALESCE(?,request_id),retry_at=? WHERE id=?",
                      (state, request_id, time.time() + delay, identity))

    def begin_attempt(self, output_id):
        identity = uuid.uuid4().hex
        token = 'printer-app-' + identity
        with connect(self.path) as c:
            c.execute("UPDATE outputs SET state='SUBMITTING' WHERE id=?", (output_id,))
            c.execute("INSERT INTO print_attempts(id,output_id,token,started,state) VALUES(?,?,?,?,?)",
                      (identity, output_id, token, time.time(), 'SUBMITTING'))
        return identity, token

    def finish_attempt(self, attempt_id, state, request_id, detail):
        with connect(self.path) as c:
            c.execute("UPDATE print_attempts SET state=?,request_id=?,detail=?,finished=? WHERE id=?",
                      (state, request_id, detail[:8000], time.time(), attempt_id))

    def latest_attempt(self, output_id):
        with connect(self.path) as c:
            r = c.execute("SELECT * FROM print_attempts WHERE output_id=? ORDER BY started DESC LIMIT 1", (output_id,)).fetchone()
            return dict(r) if r else None

    def get(self, key, default=None):
        with connect(self.path) as c:
            row = c.execute("SELECT value FROM runtime WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def put(self, key, value):
        with connect(self.path) as c:
            c.execute("INSERT INTO runtime(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def command(self, kind):
        if kind not in {'run', 'test'}:
            raise ValueError('Unknown command')
        with connect(self.path) as c:
            # Repeated taps do not flood the queue.
            if not c.execute("SELECT 1 FROM commands WHERE kind=? AND done=0", (kind,)).fetchone():
                c.execute("INSERT INTO commands(id,kind,created) VALUES(?,?,?)", (uuid.uuid4().hex, kind, time.time()))

    def commands(self):
        with connect(self.path) as c:
            return [dict(r) for r in c.execute("SELECT * FROM commands WHERE done=0 ORDER BY created")]

    def acknowledge(self, identity):
        with connect(self.path) as c:
            c.execute("UPDATE commands SET done=1 WHERE id=?", (identity,))

    def recent(self, limit=100):
        with connect(self.path) as c:
            return [dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (limit,))]

    def detail(self, job_id):
        with connect(self.path) as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result['outputs'] = [dict(r) for r in c.execute("SELECT * FROM outputs WHERE job_id=? ORDER BY rowid", (job_id,))]
            result['steps'] = [dict(r) for r in c.execute("SELECT * FROM steps WHERE job_id=? ORDER BY id", (job_id,))]
            result['attempts'] = [dict(r) for r in c.execute("SELECT a.* FROM print_attempts a JOIN outputs o ON o.id=a.output_id WHERE o.job_id=? ORDER BY a.started", (job_id,))]
            return result
