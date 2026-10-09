"""Salesforce printing workflow; existing printer services remain unchanged."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import time

from . import converter
from .print_queue_repository import PrintQueueRepository


class ReportPrintingService:
    def __init__(self, repository, source, db, cfg):
        self.repository = repository
        self.source = source
        self.queue = PrintQueueRepository(db)
        self.cfg = cfg

    def run_due(self, now=None):
        now = now or datetime.now(timezone.utc)
        for job in self.repository.list():
            # At startup, catch the current minute only. Never replay old
            # schedules blindly after a downtime.
            since = now.replace(second=0, microsecond=0)
            for occurrence in job.due_occurrences(since, now):
                self.run(job, occurrence.isoformat())

    def run(self, job, occurrence):
        for report in job.reports:
            identity = 'salesforce-report:' + job.job_id + ':' + occurrence + ':' + report.report_id
            if not self.repository.claim(identity):
                continue
            try:
                options = report.effective_options(job.defaults)
                payload = self.source.download_formatted_report(report.report_id)
                directory = self.cfg.data_dir / 'report-printing' / job.job_id / str(abs(hash(identity)))
                # Use a stable filename derived from report and occurrence, not hash()
                import hashlib
                directory = self.cfg.data_dir / 'report-printing' / hashlib.sha256(identity.encode()).hexdigest()
                directory.mkdir(parents=True, exist_ok=True)
                workbook = directory / 'source.xlsx'
                workbook.write_bytes(payload)
                pdf = converter.convert(workbook, directory, replace(self.cfg, print_options=options))
                pages = converter.page_count(pdf)
                if options.page_policy == 'one-page' and pages != 1:
                    raise ValueError('Report exceeds one-page print policy')
                queue_identity = 'pdf:' + identity
                job_id, _ = self.queue.enqueue_generated_pdf(queue_identity, pdf, pages,
                                                              options.snapshot(), time.time())
                self.repository.finish(identity, 'QUEUED', queued_job_id=job_id)
            except Exception as exc:
                # A claimed occurrence is never automatically retried, avoiding
                # duplicate prints when submission state is ambiguous.
                self.repository.finish(identity, 'ERROR', type(exc).__name__ + ': ' + str(exc))
