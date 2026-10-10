"""Independent Salesforce report printing persistence; no legacy schema changes."""
import json
import uuid

from .print_options import PrintOptions
from .report_notes_contract import ReportNotesOptions
from .report_printing_contract import ReportPrintingJob, ScheduledReport


class ReportPrintingRepository:
    def __init__(self, db):
        self.db = db
        with db.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS report_printing_jobs (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, checkpoint REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS report_printing_runs (
                    identity TEXT PRIMARY KEY, state TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    queued_job_id INTEGER
                );
            """)

    def list(self):
        with self.db.connect() as conn:
            rows = conn.execute('SELECT payload FROM report_printing_jobs ORDER BY id').fetchall()
        return [self.decode(json.loads(row['payload'])) for row in rows]

    @staticmethod
    def decode(data):
        return ReportPrintingJob(
            job_id=data['job_id'], name=data['name'], timezone=data['timezone'],
            hour=int(data['hour']), minute=int(data['minute']),
            weekdays=tuple(data['weekdays']),
            defaults=PrintOptions(**data['defaults']),
            reports=tuple(ScheduledReport(r['report_id'], r['name'], r['overrides'],
                          ReportNotesOptions.from_dict(r.get('notes', {}))) for r in data['reports']),
            enabled=data['enabled'],
        )

    @staticmethod
    def encode(job):
        return dict(job_id=job.job_id, name=job.name, timezone=job.timezone,
                    hour=job.hour, minute=job.minute, weekdays=list(job.weekdays),
                    defaults=job.defaults.snapshot(), enabled=job.enabled,
                    reports=[dict(report_id=r.report_id, name=r.name, overrides=r.overrides,
                                  notes=r.notes.snapshot()) for r in job.reports])

    def save(self, job):
        payload = json.dumps(self.encode(job))
        with self.db.connect() as conn:
            conn.execute("""INSERT INTO report_printing_jobs(id,payload) VALUES (?,?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload""",
                (job.job_id, payload))

    def delete(self, job_id):
        with self.db.connect() as conn:
            conn.execute('DELETE FROM report_printing_jobs WHERE id=?', (job_id,))

    def claim(self, identity):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            result = conn.execute(
                "INSERT OR IGNORE INTO report_printing_runs(identity,state) VALUES (?,'STARTED')",
                (identity,))
            return result.rowcount == 1

    def finish(self, identity, state, error='', queued_job_id=None):
        with self.db.connect() as conn:
            conn.execute('UPDATE report_printing_runs SET state=?,error=?,queued_job_id=? WHERE identity=?',
                         (state, error[:1000], queued_job_id, identity))

    def runs(self, limit=100):
        return self.db.rows('SELECT * FROM report_printing_runs ORDER BY rowid DESC LIMIT ?', (limit,))
