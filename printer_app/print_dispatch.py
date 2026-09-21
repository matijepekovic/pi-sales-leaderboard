"""Print timing workflow, independent of email collection and CUPS execution."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .print_queue_repository import PrintQueueRepository
from .print_schedule import PrintSchedule

log = logging.getLogger(__name__)


class PrintDispatchService:
    def __init__(self, repository: PrintQueueRepository, schedule: PrintSchedule,
                 timezone: str, clock=None):
        self.repository, self.schedule, self.timezone = repository, schedule, timezone
        self.clock = clock or time.time
        self.signature = schedule.signature(timezone)

    def configure(self) -> dict:
        now = self.clock()
        return self.repository.configure(self.signature, self.schedule.next_after(now, self.timezone), now)

    def release_due(self) -> None:
        now = self.clock()
        state = self.configure()
        if state['next_run'] is not None and now >= state['next_run']:
            cutoff = self.schedule.latest_due(now, self.timezone)
            count = self.repository.release_due(self.signature, state['next_run'], cutoff,
                self.schedule.next_after(now, self.timezone), now)
            log.info('Scheduled print batch released: attachments=%s scheduled_for=%s timezone=%s',
                     count, cutoff, self.timezone)
        count = self.repository.release_requested(now)
        if count:
            log.info('User requested print batch released: attachments=%s', count)

    def allow(self, job: dict) -> bool:
        return self.repository.eligible(job, self.schedule.mode == 'immediate')

    def due_jobs(self) -> list[dict]:
        self.release_due()
        return self.repository.due_jobs(self.clock(), self.schedule.mode == 'immediate')

    def request_print_now(self) -> None:
        self.repository.request_manual_release(self.clock())

    def summary(self) -> dict:
        # Web reads never advance the schedule or release jobs. The worker owns
        # applying revisions; compute a display-only next time until it does.
        now = self.clock()
        state = self.repository.state()
        applied = bool(state and state['signature'] == self.signature)
        return dict(mode=self.schedule.mode, description=self.schedule.description(self.timezone),
            timezone=self.timezone, applied=applied,
            next_run=state['next_run'] if applied else self.schedule.next_after(now, self.timezone),
            last_run=state.get('last_run') if state else None,
            waiting=self.repository.waiting())

    def describe_job(self, job: dict) -> dict:
        info = self.removal_info(job['attachment_id']) if job['attachment_id'] and job['status'] in (
            'PREPARING', 'READY', 'PRINTER ERROR') else None
        cancelled = bool(info and info['cancelled_at'] is not None)
        waiting = not cancelled and job['status'] in ('PREPARING', 'READY') and not self.allow(job)
        status = 'CANCELLED' if cancelled else job['status']
        error_sheet = bool(job.get('is_error'))
        label, tone, detail = {
            'PREPARING': ('Preparing', 'pending', 'Preparing the document for printing.'),
            'READY': ('Waiting for schedule' if waiting else 'Ready to print', 'pending',
                      'Waiting for the saved print schedule.' if waiting else 'Waiting for the printer worker.'),
            'SUBMITTED': ('Sent to printer', 'pending', 'Waiting for printer completion.'),
            'PRINTED': ('Printed', 'good', 'Printer queue confirmed completion.'),
            'ERROR PRINTED': ('Error sheet printed', 'error', 'The report was not confirmed printed. Only the error sheet completed.'),
            'PRINTER ERROR': ('Needs attention', 'error', job.get('latest_step') or 'Printer unavailable; waiting for retry or confirmation.'),
            'PRINT UNKNOWN': ('Outcome unknown', 'error', 'Printing could not be confirmed. Check the printer before printing again.'),
            'CANCELLED': ('Cancelled', 'neutral', 'Removed from the print queue.'),
        }.get(status, (status, 'neutral', ''))
        if error_sheet and status in ('PREPARING', 'READY', 'SUBMITTED', 'PRINTER ERROR'):
            label = {'READY': 'Error sheet queued', 'SUBMITTED': 'Error sheet sent'}.get(status, label)
            tone = 'error'
            detail = 'The report was not confirmed printed. ' + detail
        generated = not job.get('attachment_id') and str(job.get('group_key', '')).startswith('pdf:')
        name = job.get('filename') or (
            Path(job.get('generated_filename') or job.get('printable') or '').name or 'Generated PDF'
            if generated else 'Test print')
        return dict(job, waiting_for_schedule=waiting, can_remove=bool(info and info['can_remove']),
                    queue_status='CANCELLED' if cancelled else
                    'QUEUED' if waiting and status == 'READY' else status,
                    display_name=name,
                    display_source=job.get('subject') or ('Generated document' if generated else 'Local test'),
                    status_label=label, status_tone=tone, status_detail=detail,
                    receipt=job.get('attempt_request_id') or '')

    def activity(self) -> dict:
        """Read-only print results; a receipt alone never means a completed report."""
        jobs = [self.describe_job(job) for job in self.repository.recent_activity()]
        counts = {'printed': 0, 'pending': 0, 'attention': 0, 'cancelled': 0}
        categories = {'good': 'printed', 'pending': 'pending', 'error': 'attention', 'neutral': 'cancelled'}
        for job in jobs:
            counts[categories[job['status_tone']]] += 1
        return dict(jobs=jobs, counts=counts, worker_alive=self.clock() - self.repository.worker_heartbeat() < 30,
                    last_report_printed=self.repository.last_report_printed())

    def removal_info(self, attachment_id):
        item = self.repository.removal_info(attachment_id)
        if not item:
            raise LookupError('This attachment is no longer available.')
        item['can_remove'] = bool(item['cancelled_at'] is None and not item['has_attempts']
            and not item['terminal_job'] and item['state'] != 'DOWNLOADING'
            and (item['state'] in ('PENDING', 'PROCESSING') or item['unfinished']))
        return item

    def remove(self, attachment_id):
        changed = self.repository.cancel_attachment(attachment_id, self.clock())
        if changed:
            log.info('User removed print attachment %s; no gallery data changed', attachment_id)
        return changed
