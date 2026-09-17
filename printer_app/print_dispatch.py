"""Print timing workflow, independent of email collection and CUPS execution."""
from __future__ import annotations

import logging
import time

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
        info = self.repository.removal_info(job['attachment_id']) if job['attachment_id'] else None
        cancelled = bool(info and info['cancelled_at'] is not None)
        removable = bool(info and not cancelled and not info['has_attempts'] and not info['terminal_job']
                         and info['state'] != 'DOWNLOADING'
                         and (info['state'] in ('PENDING','PROCESSING') or info['unfinished']))
        waiting = not cancelled and job['status'] in ('PREPARING', 'READY') and not self.allow(job)
        return dict(job, waiting_for_schedule=waiting, can_remove=removable,
                    queue_status='CANCELLED' if cancelled else
                    'QUEUED' if waiting and job['status'] == 'READY' else job['status'])

    def removal_info(self, attachment_id):
        item = self.repository.removal_info(attachment_id)
        if not item:
            raise LookupError('This attachment is no longer available.')
        return item

    def remove(self, attachment_id):
        changed = self.repository.cancel_attachment(attachment_id, self.clock())
        if changed:
            log.info('User removed print attachment %s; no gallery data changed', attachment_id)
        return changed
