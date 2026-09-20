"""Daily MOD-sheet workflow: current-day source -> PDF -> existing print queue."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from .policy import (
    DailyModSheetSchedule,
    ModSheetAutomationSettings,
    RETRY_DELAY_SECONDS,
)


log = logging.getLogger(__name__)
TERMINAL = frozenset({'queued', 'no_appointments', 'failed'})


class ModSheetSettingsService:
    """Permanent automatic MOD settings and display status."""

    def __init__(self, repository, queue):
        self.repository = repository
        self.queue = queue

    def save(self, settings: ModSheetAutomationSettings) -> None:
        self.repository.save_settings(settings)

    def snapshot(self, timezone: str, stamp=None) -> dict:
        now = time.time() if stamp is None else float(stamp)
        settings = self.repository.settings()
        state = self.repository.state()
        queue_state = None
        if state.get('job_id'):
            queue_state = self.queue.job_status(int(state['job_id']))
        schedule = DailyModSheetSchedule(timezone)
        occurrence = schedule.occurrence_due(now)
        due_now = False
        next_run = schedule.next_after(now)
        if settings is not None and occurrence is not None:
            same_day = state.get('day') == occurrence.day
            status = state.get('status', '') if same_day else ''
            if status == 'retry_wait' and now < float(state.get('next_attempt') or 0):
                next_run = float(state['next_attempt'])
            elif status not in TERMINAL:
                due_now = True
        return {
            'configured': settings is not None,
            'settings': settings or ModSheetAutomationSettings(),
            'schedule': schedule.description(),
            'next_run': next_run,
            'due_now': due_now,
            'state': state,
            'queue_state': queue_state,
        }


class DailyModSheetService:
    def __init__(
        self,
        repository,
        source,
        queue,
        renderer,
        data_dir: Path,
        timezone: str,
        print_options,
        clock=None,
    ):
        self.repository = repository
        self.source = source
        self.queue = queue
        self.renderer = renderer
        self.data_dir = Path(data_dir)
        self.schedule = DailyModSheetSchedule(timezone)
        self.print_options = print_options
        self.clock = clock or time.time

    def due(self, stamp=None) -> bool:
        now = self.clock() if stamp is None else float(stamp)
        if self.repository.settings() is None:
            return False
        occurrence = self.schedule.occurrence_due(now)
        if occurrence is None:
            return False
        state = self.repository.state()
        if state.get('day') != occurrence.day:
            return True
        status = state.get('status', '')
        if status in TERMINAL:
            return False
        if status == 'retry_wait':
            return now >= float(state.get('next_attempt') or 0)
        # Recover an interrupted in-process attempt without creating a duplicate.
        return True

    def _state(self, occurrence, *, status, attempt, now, **extra):
        state = {
            'day': occurrence.day,
            'scheduled_for': occurrence.scheduled_for,
            'status': status,
            'attempt': attempt,
            'updated': now,
        }
        state.update(extra)
        return self.repository.save_state(state)

    def _write_pdf(self, day: str, payload: bytes) -> Path:
        directory = self.data_dir / 'mod-sheets'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = directory / f'MOD-Sheet-{day}.pdf'
        temporary = directory / f'.MOD-Sheet-{day}.tmp'
        with temporary.open('wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        temporary.replace(target)
        return target

    def run_due(self, stamp=None) -> dict:
        now = self.clock() if stamp is None else float(stamp)
        occurrence = self.schedule.occurrence_due(now)
        settings = self.repository.settings()
        if occurrence is None or settings is None:
            return self.repository.state()

        state = self.repository.state()
        if state.get('day') == occurrence.day and state.get('status') in TERMINAL:
            return state
        if state.get('day') == occurrence.day and state.get('status') == 'retry_wait':
            if now < float(state.get('next_attempt') or 0):
                return state
            attempt = 2
        elif state.get('day') == occurrence.day and state.get('status') == 'running':
            attempt = max(1, min(2, int(state.get('attempt') or 1)))
        else:
            attempt = 1

        self._state(occurrence, status='running', attempt=attempt, now=now)

        try:
            records = tuple(self.source.records(
                start_date=occurrence.display_date,
                end_date=occurrence.display_date,
                market_segment=settings.market_segment,
                product_category=settings.product_category,
                source_type=settings.source_type,
                remove_canceled=settings.remove_canceled,
                remove_unconfirmed=settings.remove_unconfirmed,
                limit=1000,
            ))
            finished = self.clock()
            if not records:
                log.info('Daily MOD Sheet: no appointments for %s', occurrence.day)
                return self._state(
                    occurrence,
                    status='no_appointments',
                    attempt=attempt,
                    now=finished,
                    appointments=0,
                    message='No appointments',
                )

            payload = self.renderer(records, color_code=settings.color_code)
            target = self._write_pdf(occurrence.day, payload)
            pages = (len(records) + 2) // 3
            job_id, created = self.queue.enqueue_generated_pdf(
                f'pdf:daily-mod:{occurrence.day}',
                target,
                pages,
                self.print_options.snapshot(),
                finished,
            )
            log.info(
                'Daily MOD Sheet queued: day=%s appointments=%s pages=%s job=%s created=%s',
                occurrence.day, len(records), pages, job_id, created,
            )
            return self._state(
                occurrence,
                status='queued',
                attempt=attempt,
                now=self.clock(),
                appointments=len(records),
                pages=pages,
                job_id=job_id,
                message=f'Queued {len(records)} appointments',
            )
        except Exception as exc:
            failed = self.clock()
            detail = str(exc).strip()[:500] or type(exc).__name__
            if attempt < 2:
                log.warning('Daily MOD Sheet failed; one retry scheduled in two minutes: %s', type(exc).__name__)
                return self._state(
                    occurrence,
                    status='retry_wait',
                    attempt=attempt,
                    now=failed,
                    next_attempt=failed + RETRY_DELAY_SECONDS,
                    message='Failed; retry scheduled in 2 minutes',
                    error=detail,
                )
            log.warning('Daily MOD Sheet failed after retry: %s', type(exc).__name__)
            return self._state(
                occurrence,
                status='failed',
                attempt=attempt,
                now=failed,
                message='Failed after retry',
                error=detail,
            )
