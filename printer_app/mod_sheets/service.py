"""MOD-sheet settings, automatic workflow, and one-off test printing."""
from __future__ import annotations

from datetime import datetime
import logging
import os
import time
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from .policy import (
    DailyModSheetSchedule,
    ModSheetAutomationSettings,
    RETRY_DELAY_SECONDS,
)


log = logging.getLogger(__name__)
TERMINAL = frozenset({'queued', 'no_appointments', 'failed'})


def _write_pdf(data_dir: Path, filename: str, payload: bytes) -> Path:
    directory = Path(data_dir) / 'mod-sheets'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / filename
    temporary = directory / ('.' + filename + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.chmod(0o600)
    temporary.replace(target)
    return target


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

        test_state = self.repository.test_state()
        test_queue_state = None
        if test_state.get('job_id'):
            test_queue_state = self.queue.job_status(int(test_state['job_id']))

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
            'test_state': test_state,
            'test_queue_state': test_queue_state,
        }


class ModSheetTestPrintService:
    """Generate today's MOD PDF and request worker-first printing once."""

    def __init__(self, repository, source, queue, renderer, data_dir: Path, clock=None):
        self.repository = repository
        self.source = source
        self.queue = queue
        self.renderer = renderer
        self.data_dir = Path(data_dir)
        self.clock = clock or time.time

    def _state(self, *, status, now, **extra):
        state = {'status': status, 'updated': now}
        state.update(extra)
        return self.repository.save_test_state(state)

    def run(self, settings: ModSheetAutomationSettings, timezone: str, token: str) -> dict:
        now = self.clock()
        local_day = datetime.fromtimestamp(now, ZoneInfo(timezone)).date()
        day = local_day.isoformat()
        display_date = local_day.strftime('%-m/%-d/%Y')
        self._state(
            status='running',
            now=now,
            day=day,
            message='Generating test MOD Sheet',
        )
        try:
            records = tuple(self.source.records(
                start_date=display_date,
                end_date=display_date,
                market_segment=settings.market_segment,
                product_category=settings.product_category,
                source_type=settings.source_type,
                remove_canceled=settings.remove_canceled,
                remove_unconfirmed=settings.remove_unconfirmed,
                limit=1000,
            ))
            finished = self.clock()
            if not records:
                return self._state(
                    status='no_appointments',
                    now=finished,
                    day=day,
                    appointments=0,
                    message='No appointments',
                )

            payload = self.renderer(records, color_code=settings.color_code)
            target = _write_pdf(
                self.data_dir,
                f'MOD-Sheet-test-{token}.pdf',
                payload,
            )
            pages = (len(records) + 2) // 3
            job_id, created = self.queue.enqueue_immediate_generated_pdf(
                f'pdf:mod-test:{token}',
                target,
                pages,
                settings.print_options.snapshot(),
                finished,
            )
            return self._state(
                status='queued',
                now=self.clock(),
                day=day,
                appointments=len(records),
                pages=pages,
                job_id=job_id,
                created=created,
                message='Test print queued for immediate printing',
            )
        except Exception as exc:
            detail = str(exc).strip()[:500] or type(exc).__name__
            log.warning('MOD Sheet test print failed: %s', type(exc).__name__)
            return self._state(
                status='failed',
                now=self.clock(),
                day=day,
                message='Test print failed',
                error=detail,
            )


class DailyModSheetService:
    def __init__(
        self,
        repository,
        source,
        queue,
        renderer,
        data_dir: Path,
        timezone: str,
        clock=None,
    ):
        self.repository = repository
        self.source = source
        self.queue = queue
        self.renderer = renderer
        self.data_dir = Path(data_dir)
        self.schedule = DailyModSheetSchedule(timezone)
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
            target = _write_pdf(
                self.data_dir,
                f'MOD-Sheet-{occurrence.day}.pdf',
                payload,
            )
            # Keep the exact rendered document with its normalized source snapshot.
            # Delivery waits until the linked print job is confirmed PRINTED.
            self.repository.save_morning_reference(
                occurrence.day, records, finished, pdf_path=target
            )
            pages = (len(records) + 2) // 3
            job_id, created = self.queue.enqueue_generated_pdf(
                f'pdf:daily-mod:{occurrence.day}',
                target,
                pages,
                settings.print_options.snapshot(),
                finished,
            )
            self.repository.bind_morning_reference_job(occurrence.day, job_id)
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


class ModSheetReferenceDeliveryService:
    """Deliver normalized MOD references without making Gallery a print dependency."""

    FINAL_HOUR = 23
    FINAL_MINUTE = 0

    def __init__(self, repository, source, queue, reference_sink, timezone, clock=None):
        self.repository = repository
        self.source = source
        self.queue = queue
        self.reference_sink = reference_sink
        self.timezone = timezone
        self.zone = ZoneInfo(timezone)
        self.clock = clock or time.time

    def request_refresh(self):
        """Queue a source refresh without calling the source from the web process."""
        now = self.clock()
        day = datetime.fromtimestamp(now, self.zone).date().isoformat()
        return self.repository.request_reference_refresh(str(uuid4()), day, now)

    def refresh_status(self):
        return self.repository.reference_refresh_state()

    def requested_due(self):
        # The worker's single reference future owns execution; running means an
        # interrupted request should resume after a process restart.
        return self.refresh_status().get('status') in ('queued', 'running')

    def run_requested(self):
        state = self.refresh_status()
        if state.get('status') not in ('queued', 'running'):
            return state
        now = self.clock()
        # A request waiting across midnight must refresh today's assignments.
        state = dict(state, status='running', updated=now,
                     day=datetime.fromtimestamp(now, self.zone).date().isoformat())
        self.repository.save_reference_refresh_state(state)
        try:
            if self.reference_sink is None:
                raise RuntimeError('Card refresh is unavailable.')
            result = self._refresh_cards(state['day'])
            return self.repository.save_reference_refresh_state(dict(
                state, status='complete', updated=self.clock(), **result,
            ))
        except Exception as exc:
            detail = str(exc).strip()[:500] or type(exc).__name__
            log.warning('Requested MOD reference pull failed; keeping saved card references.')
            return self.repository.save_reference_refresh_state(dict(
                state, status='failed', updated=self.clock(), error=detail,
            ))

    def deliver_printed_mornings(self):
        if self.reference_sink is None:
            return 0
        delivered = 0
        for entry in self.repository.pending_morning_references():
            job = self.queue.job_status(entry['job_id'])
            if not job or job.get('status') != 'PRINTED':
                continue
            try:
                document = {}
                if entry.get('pdf_path'):
                    document['pdf_payload'] = Path(entry['pdf_path']).read_bytes()
                self.reference_sink.publish(
                    entry['day'],
                    'morning',
                    entry['records'],
                    entry['captured_at'],
                    **document,
                )
            except Exception:
                # Gallery delivery is optional. Never turn a Gallery
                # failure into a printer-worker failure.
                log.warning('Morning MOD reference delivery failed; printing is unaffected.')
                continue
            self.repository.mark_morning_reference_delivered(
                entry['day'], self.clock()
            )
            delivered += 1
        return delivered

    def final_due(self, stamp=None):
        now = self.clock() if stamp is None else float(stamp)
        if self.reference_sink is None:
            return False
        local = datetime.fromtimestamp(now, self.zone)
        if (local.hour, local.minute) < (self.FINAL_HOUR, self.FINAL_MINUTE):
            return False
        state = self.repository.final_reference_state()
        if state.get('day') != local.date().isoformat():
            return True
        # A process restart can leave an in-progress pull behind. Retry that
        # interrupted run once the worker is back; completed/failed days stay terminal.
        return state.get('status') == 'running'

    def hourly_due(self, stamp=None):
        now = self.clock() if stamp is None else float(stamp)
        if self.reference_sink is None:
            return False
        local = datetime.fromtimestamp(now, self.zone)
        # The final pull owns 11 PM, so hourly refreshes cannot replace it.
        if (local.hour, local.minute) >= (self.FINAL_HOUR, self.FINAL_MINUTE):
            return False
        state = self.repository.hourly_reference_state()
        # Include the UTC offset to distinguish the repeated hour when DST ends.
        if state.get('hour') != local.isoformat(timespec='hours'):
            return True
        return state.get('status') == 'running'

    def run_hourly(self, stamp=None):
        now = self.clock() if stamp is None else float(stamp)
        if not self.hourly_due(now):
            return self.repository.hourly_reference_state()
        local = datetime.fromtimestamp(now, self.zone)
        state = {
            'day': local.date().isoformat(),
            'hour': local.isoformat(timespec='hours'),
            'status': 'running',
            'updated': now,
        }
        self.repository.save_hourly_reference_state(state)
        try:
            result = self._refresh_cards(state['day'])
            return self.repository.save_hourly_reference_state(dict(
                state, status='complete', updated=self.clock(), **result,
            ))
        except Exception as exc:
            detail = str(exc).strip()[:500] or type(exc).__name__
            log.warning('Hourly MOD reference pull failed; keeping saved card references.')
            return self.repository.save_hourly_reference_state(dict(
                state, status='failed', updated=self.clock(), error=detail,
            ))

    def _refresh_lead_statuses(self, current_work_orders=(), *, missing_only=False):
        """Resolve retained work orders independently of appointment dates."""
        numbers = tuple(dict.fromkeys((
            *self.reference_sink.work_order_numbers(missing_only=missing_only), *current_work_orders)))
        if not numbers:
            return {'lead_statuses': 0, 'enriched': 0}
        captured = self.clock()
        records = tuple(self.source.lead_statuses(numbers))
        result = self.reference_sink.publish_lead_statuses(numbers, records, captured, missing_only=missing_only)
        return {'lead_statuses': len(records), 'enriched': int(result.get('enriched', 0))}

    def _refresh_work_orders(self):
        """Resolve retained Gallery cards directly by work-order number, without a date prerequisite."""
        numbers = tuple(dict.fromkeys(self.reference_sink.work_order_numbers()))
        if not numbers:
            return {'work_orders': 0, 'enriched': 0}
        captured = self.clock()
        records = tuple(self.source.work_orders(numbers))
        result = self.reference_sink.publish_work_order_records(numbers, records, captured)
        return {'work_orders': len(records), 'enriched': int(result.get('enriched', 0))}

    def _refresh_cards(self, day):
        # The direct work-order lookup owns Gallery identity/date enrichment.
        # Day snapshots remain independent support for the existing MOD workflow.
        result = {'appointments': 0, 'work_orders': 0, 'lead_statuses': 0, 'enriched': 0}
        errors = []
        current_work_orders = ()
        try:
            direct = self._refresh_work_orders()
            result['work_orders'] = direct['work_orders']
            result['enriched'] += direct['enriched']
        except Exception as exc:
            errors.append('Work orders: ' + (str(exc).strip() or type(exc).__name__))
        try:
            appointments = self._publish_day(day)
            current_work_orders = appointments.pop('work_order_numbers')
            result.update(appointments)
        except Exception as exc:
            errors.append('Appointments: ' + (str(exc).strip() or type(exc).__name__))
        try:
            statuses = self._refresh_lead_statuses(current_work_orders)
            result['lead_statuses'] = statuses['lead_statuses']
            result['enriched'] += statuses['enriched']
        except Exception as exc:
            errors.append('Lead status: ' + (str(exc).strip() or type(exc).__name__))
        if errors:
            raise RuntimeError('; '.join(errors))
        return result

    def _publish_day(self, day):
        # Card references cover this day, independently of print filters. The
        # source includes canceled appointments as fallback work-order matches.
        records = tuple(self.source.records(
            start_date=day,
            end_date=day,
            market_segment='',
            product_category='',
            source_type='',
            remove_canceled=False,
            remove_unconfirmed=False,
            limit=None,
        ))
        # Both refreshes and the nightly pull update the saved authoritative
        # snapshot, which also supplies assignments for scans uploaded later.
        result = self.reference_sink.publish(day, 'final', records, self.clock())
        enriched = int(result.get('enriched', 0)) if isinstance(result, dict) else 0
        return {'appointments': len(records), 'enriched': enriched,
                'work_order_numbers': tuple(record.work_order_number for record in records
                                            if record.work_order_number)}

    def backfill_existing(self):
        """Repair retained identities, then enrich every known work order directly on startup."""
        if self.reference_sink is None:
            return
        try:
            self.reference_sink.repair_missing_work_orders()
        except Exception as exc:
            log.warning('Stored work-order repair failed; Gallery worker will retry images: %s', exc)
        try:
            self._refresh_work_orders()
        except Exception as exc:
            log.warning('Direct work-order lookup failed; hourly refresh will retry: %s', exc)
        try:
            self._refresh_lead_statuses(missing_only=True)
        except Exception as exc:
            log.warning('Card Lead status lookup failed; hourly refresh will retry: %s', exc)
        if self.repository.reference_backfill_complete():
            return
        today = datetime.fromtimestamp(self.clock(), self.zone).date().isoformat()
        complete = True
        for day in self.reference_sink.dates():
            if day > today:
                continue
            try:
                self._publish_day(day)
            except Exception:
                complete = False
                log.warning('Card reference lookup failed for %s; will retry on restart.', day)
        if complete:
            self.repository.complete_reference_backfill()

    def run_final(self, stamp=None):
        now = self.clock() if stamp is None else float(stamp)
        local = datetime.fromtimestamp(now, self.zone)
        day = local.date().isoformat()
        if self.reference_sink is None:
            return self.repository.final_reference_state()
        if not self.final_due(now):
            return self.repository.final_reference_state()

        self.repository.save_final_reference_state({
            'day': day,
            'status': 'running',
            'updated': now,
        })
        try:
            result = self._refresh_cards(day)
            return self.repository.save_final_reference_state({
                'day': day,
                'status': 'complete',
                'updated': self.clock(),
                **result,
            })
        except Exception as exc:
            detail = str(exc).strip()[:500] or type(exc).__name__
            log.warning('Final MOD reference pull failed; Gallery keeps its existing behavior.')
            return self.repository.save_final_reference_state({
                'day': day,
                'status': 'failed',
                'updated': self.clock(),
                'error': detail,
            })
