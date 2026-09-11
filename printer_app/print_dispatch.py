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
        waiting = job['status'] in ('PREPARING', 'READY') and not self.allow(job)
        return dict(job, waiting_for_schedule=waiting,
                    queue_status='QUEUED' if waiting and job['status'] == 'READY' else job['status'])
