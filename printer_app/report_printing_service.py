"""Scheduled report printing and preview workflows; printer dispatch is unchanged."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import time

from . import converter
from .print_queue_repository import PrintQueueRepository
from .report_notes_contract import ReportNotesOptions


def _apply_notes(pdf, directory, notes):
    if not notes.enabled:
        return pdf, ()
    from .report_notes_pdf import normalize_pdf, render_notes
    from .report_table_pdf import read_tables
    data = normalize_pdf(pdf.read_bytes())
    tables = read_tables(data, notes.columns)
    output, placements = render_notes(data, tables, notes)
    target = directory / 'report-notes.pdf'
    target.write_bytes(output)
    return target, placements


def prepare_report(payload, directory, cfg, options, notes):
    """One preparation path for scheduled printing and the on-screen PDF preview."""
    workbook = directory / 'source.xlsx'
    workbook.write_bytes(payload)
    pdf = converter.convert(workbook, directory, replace(cfg, print_options=options))
    pdf, placements = _apply_notes(pdf, directory, notes)
    pages = converter.page_count(pdf)
    if options.page_policy == 'one-page' and pages != 1:
        raise ValueError('Report exceeds one-page print policy')
    return pdf, pages, placements


def preview_report(source, report_id, cfg, options, notes=None):
    """Return PDF bytes, column labels, and placement metrics. Never enqueue.

    notes=None requests the column catalog. Temporary exports are deleted after
    the response bytes have been captured; previews do not modify saved jobs.
    """
    cfg.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='report-preview-', dir=cfg.data_dir) as temp:
        pdf, _, placements = prepare_report(source.download_formatted_report(report_id),
            Path(temp), cfg, options, notes if notes is not None else ReportNotesOptions())
        columns = ()
        if notes is None:
            from .report_notes_pdf import normalize_pdf
            from .report_table_pdf import read_tables
            columns = read_tables(normalize_pdf(pdf.read_bytes())).columns
        return pdf.read_bytes(), columns, placements


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
            since = now.replace(second=0, microsecond=0) - timedelta(microseconds=1)
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
                # Stable path allows post-crash diagnosis without relying on Python hash().
                import hashlib
                directory = self.cfg.data_dir / 'report-printing' / hashlib.sha256(identity.encode()).hexdigest()
                directory.mkdir(parents=True, exist_ok=True)
                pdf, pages, _ = prepare_report(payload, directory, self.cfg, options, report.notes)
                queue_identity = 'pdf:' + identity
                job_id, _ = self.queue.enqueue_generated_pdf(queue_identity, pdf, pages,
                                                              options.snapshot(), time.time())
                self.repository.finish(identity, 'QUEUED', queued_job_id=job_id)
            except Exception as exc:
                # A claimed occurrence is never automatically retried, avoiding
                # duplicate prints when submission state is ambiguous.
                self.repository.finish(identity, 'ERROR', type(exc).__name__ + ': ' + str(exc))
