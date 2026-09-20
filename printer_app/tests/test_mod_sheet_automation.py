"""Daily MOD Sheet automation regressions."""
from datetime import datetime
from zoneinfo import ZoneInfo

from printer_app.db import Database
from printer_app.mod_sheets.policy import (
    DailyModSheetSchedule,
    ModSheetAutomationSettings,
)
from printer_app.mod_sheets.repository import ModSheetAutomationRepository
from printer_app.mod_sheets.service import DailyModSheetService, ModSheetSettingsService
from printer_app.print_options import PrintOptions
from printer_app.print_queue_repository import PrintQueueRepository


ZONE = ZoneInfo('America/Los_Angeles')


def _stamp(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ZONE).timestamp()


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class FakeSource:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def records(self, **filters):
        self.calls.append(filters)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeQueue:
    def __init__(self):
        self.enqueued = []
        self.statuses = {}

    def enqueue_generated_pdf(self, identity, path, pages, options, now):
        self.enqueued.append((identity, path, pages, options, now))
        return 41, True

    def job_status(self, job_id):
        return self.statuses.get(job_id)


def _service(tmp_path, source, clock, renderer=lambda records, color_code=False: b'%PDF-fake'):
    db = Database(tmp_path / 'printer.db')
    repository = ModSheetAutomationRepository(db)
    repository.save_settings(ModSheetAutomationSettings(
        market_segment='Olympia',
        product_category='All',
        source_type='All',
        remove_canceled=True,
        remove_unconfirmed=True,
        color_code=True,
    ))
    queue = FakeQueue()
    service = DailyModSheetService(
        repository,
        source,
        queue,
        renderer,
        tmp_path,
        'America/Los_Angeles',
        PrintOptions(),
        clock=clock,
    )
    return service, repository, queue


def test_daily_schedule_is_weekdays_at_seven_and_catches_up_same_day():
    schedule = DailyModSheetSchedule('America/Los_Angeles')

    assert schedule.occurrence_due(_stamp(2026, 9, 21, 6, 59)) is None
    due = schedule.occurrence_due(_stamp(2026, 9, 21, 7, 0))
    assert due.day == '2026-09-21'
    assert due.display_date == '9/21/2026'

    late = schedule.occurrence_due(_stamp(2026, 9, 21, 15, 30))
    assert late.day == '2026-09-21'
    assert schedule.occurrence_due(_stamp(2026, 9, 19, 9, 0)) is None


def test_daily_run_always_queries_current_day_and_queues_existing_printer_pipeline(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    source = FakeSource([('record-1', 'record-2', 'record-3', 'record-4')])
    service, repository, queue = _service(tmp_path, source, clock)

    state = service.run_due()

    assert source.calls == [{
        'start_date': '9/21/2026',
        'end_date': '9/21/2026',
        'market_segment': 'Olympia',
        'product_category': 'All',
        'source_type': 'All',
        'remove_canceled': True,
        'remove_unconfirmed': True,
        'limit': 1000,
    }]
    assert state['status'] == 'queued'
    assert state['appointments'] == 4
    assert state['pages'] == 2
    assert state['job_id'] == 41
    assert queue.enqueued[0][0] == 'pdf:daily-mod:2026-09-21'
    assert queue.enqueued[0][2] == 2
    assert queue.enqueued[0][1].read_bytes() == b'%PDF-fake'
    assert service.due() is False
    assert repository.state()['message'] == 'Queued 4 appointments'


def test_no_appointments_does_not_print_and_is_marked(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    source = FakeSource([()])
    service, repository, queue = _service(tmp_path, source, clock)

    state = service.run_due()

    assert state['status'] == 'no_appointments'
    assert state['message'] == 'No appointments'
    assert state['appointments'] == 0
    assert queue.enqueued == []
    assert service.due() is False
    assert repository.state()['day'] == '2026-09-21'


def test_failure_retries_once_after_two_minutes_then_stops(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    source = FakeSource([RuntimeError('first failure'), RuntimeError('second failure')])
    service, repository, queue = _service(tmp_path, source, clock)

    first = service.run_due()
    assert first['status'] == 'retry_wait'
    assert first['attempt'] == 1
    assert first['next_attempt'] == clock.value + 120

    clock.value = _stamp(2026, 9, 21, 7, 1, 59)
    assert service.due() is False

    clock.value = _stamp(2026, 9, 21, 7, 2)
    assert service.due() is True
    second = service.run_due()
    assert second['status'] == 'failed'
    assert second['attempt'] == 2
    assert second['message'] == 'Failed after retry'
    assert queue.enqueued == []
    assert service.due() is False
    assert repository.state()['status'] == 'failed'


def test_generated_pdf_queue_identity_is_durable_and_not_duplicated(tmp_path):
    db = Database(tmp_path / 'printer.db')
    queue = PrintQueueRepository(db)
    pdf = tmp_path / 'daily.pdf'
    pdf.write_bytes(b'%PDF-fake')
    options = PrintOptions().snapshot()

    first, created = queue.enqueue_generated_pdf(
        'pdf:daily-mod:2026-09-21', pdf, 1, options, 100.0
    )
    second, created_again = queue.enqueue_generated_pdf(
        'pdf:daily-mod:2026-09-21', pdf, 1, options, 101.0
    )

    assert created is True
    assert created_again is False
    assert first == second
    job = queue.job_status(first)
    assert job['status'] == 'READY'
    assert job['page_count'] == 1
    assert db.job_print_settings(first) == options



def test_settings_status_shows_due_now_after_seven_until_today_is_handled(tmp_path):
    db = Database(tmp_path / 'printer.db')
    repository = ModSheetAutomationRepository(db)
    queue = FakeQueue()
    service = ModSheetSettingsService(repository, queue)
    repository.save_settings(ModSheetAutomationSettings(market_segment='Olympia'))

    snapshot = service.snapshot(
        'America/Los_Angeles',
        _stamp(2026, 9, 21, 7, 5),
    )
    assert snapshot['due_now'] is True

    repository.save_state({
        'day': '2026-09-21',
        'status': 'no_appointments',
        'message': 'No appointments',
    })
    handled = service.snapshot(
        'America/Los_Angeles',
        _stamp(2026, 9, 21, 7, 6),
    )
    assert handled['due_now'] is False
    assert handled['state']['message'] == 'No appointments'


def test_mod_settings_page_is_separate_and_dates_are_not_persisted():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / 'templates/mod_sheet_settings.html').read_text()
    base = (root / 'templates/base.html').read_text()

    assert 'Save Settings' in template
    assert 'always the current day' in template
    assert 'name="startdate"' not in template
    assert 'name="enddate"' not in template
    assert "url_for('mod_sheets.settings_page')" in base
    assert '>MOD Sheets<' in base
    assert '>MOD Settings<' in base
