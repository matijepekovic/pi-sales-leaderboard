"""Daily MOD Sheet automation and immediate test-print regressions."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from printer_app.db import Database
from printer_app.mod_sheets.policy import (
    DailyModSheetSchedule,
    ModSheetAutomationSettings,
)
from printer_app.mod_sheets.repository import (
    ModSheetAutomationRepository, REFERENCE_BACKFILL_KEY, REFERENCE_OUTBOX_KEY, SETTINGS_KEY,
)
from printer_app.mod_sheets.service import (
    DailyModSheetService,
    ModSheetReferenceDeliveryService,
    ModSheetSettingsService,
    ModSheetTestPrintService,
)
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.print_options import PrintOptions
from printer_app.print_queue_repository import PrintQueueRepository


ZONE = ZoneInfo('America/Los_Angeles')


def _stamp(year, month, day, hour, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=ZONE).timestamp()


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class FakeSource:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.lead_calls = []
        self.lead_results = ()
        self.work_order_calls = []
        self.work_order_results = ()

    def lead_statuses(self, work_order_numbers):
        self.lead_calls.append(tuple(work_order_numbers))
        if isinstance(self.lead_results, Exception):
            raise self.lead_results
        return self.lead_results

    def work_orders(self, work_order_numbers):
        self.work_order_calls.append(tuple(work_order_numbers))
        if isinstance(self.work_order_results, Exception):
            raise self.work_order_results
        return self.work_order_results

    def records(self, **filters):
        self.calls.append(filters)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeReferenceSink:
    def __init__(self, fail=False, days=()):
        self.fail = fail
        self.days = days
        self.published = []
        self.pdf_payloads = []
        self.numbers = ()
        self.lead_published = []
        self.work_order_published = []
        self.lead_scopes = []
        self.repair_calls = 0

    def repair_missing_work_orders(self):
        self.repair_calls += 1
        return {'repaired': 0, 'review': 0}

    def work_order_numbers(self, *, missing_only=False):
        self.lead_scopes.append(('read', missing_only))
        return self.numbers

    def publish_lead_statuses(self, work_order_numbers, records, captured, *, missing_only=False):
        if self.fail:
            raise RuntimeError('reference sink unavailable')
        self.lead_published.append((tuple(work_order_numbers), tuple(records), captured))
        self.lead_scopes.append(('publish', missing_only))
        return {'count': len(records), 'enriched': len(records)}

    def publish_work_order_records(self, work_order_numbers, records, captured):
        if self.fail:
            raise RuntimeError('reference sink unavailable')
        records = tuple(records)
        self.work_order_published.append((tuple(work_order_numbers), records, captured))
        return {'count': len(records), 'enriched': len(records)}

    def dates(self):
        return self.days

    def publish(self, day, kind, records, captured, *, pdf_payload=None):
        if self.fail:
            raise RuntimeError('reference sink unavailable')
        records = tuple(records)
        self.published.append((day, kind, records, captured))
        self.pdf_payloads.append(pdf_payload)
        return {'day': day, 'kind': kind, 'count': len(records), 'enriched': 0}


class FakeQueue:
    def __init__(self):
        self.enqueued = []
        self.immediate = []
        self.statuses = {}

    def enqueue_generated_pdf(self, identity, path, pages, options, now):
        self.enqueued.append((identity, path, pages, options, now))
        return 41, True

    def enqueue_immediate_generated_pdf(self, identity, path, pages, options, now):
        self.immediate.append((identity, path, pages, options, now))
        return 77, True

    def job_status(self, job_id):
        return self.statuses.get(job_id)


def _mod_print_options():
    return PrintOptions(
        paper='letter',
        orientation='portrait',
        color='color',
        sides='one-sided',
        copies=2,
        pdf_scaling='fit',
    )


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
        print_options=_mod_print_options(),
    ))
    queue = FakeQueue()
    service = DailyModSheetService(
        repository,
        source,
        queue,
        renderer,
        tmp_path,
        'America/Los_Angeles',
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


def test_daily_run_uses_current_day_and_mod_owned_print_settings(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    source = FakeSource([tuple(
        ModSheetRecord(source_id=f'source-{index}', work_order_number=f'{index:04d}')
        for index in range(1, 5)
    )])
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
    assert queue.enqueued[0][3] == _mod_print_options().snapshot()
    assert queue.enqueued[0][1].read_bytes() == b'%PDF-fake'
    assert service.due() is False
    assert repository.state()['message'] == 'Queued 4 appointments'


def test_old_saved_mod_settings_gain_independent_default_print_settings(tmp_path):
    db = Database(tmp_path / 'printer.db')
    db.set(SETTINGS_KEY, {
        'market_segment': 'Olympia',
        'product_category': 'All',
        'source_type': 'All',
        'remove_canceled': True,
        'remove_unconfirmed': True,
        'color_code': True,
    })

    settings = ModSheetAutomationRepository(db).settings()

    assert settings.market_segment == 'Olympia'
    assert settings.print_options == PrintOptions()


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


def test_test_print_uses_unsaved_values_today_and_does_not_change_daily_settings(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 18, 15))
    db = Database(tmp_path / 'printer.db')
    repository = ModSheetAutomationRepository(db)
    saved = ModSheetAutomationSettings(
        market_segment='Saved Market',
        print_options=PrintOptions(paper='legal', copies=1),
    )
    repository.save_settings(saved)
    source = FakeSource([('today-record',)])
    queue = FakeQueue()
    test_settings = ModSheetAutomationSettings(
        market_segment='Unsaved Test Market',
        product_category='Windows',
        source_type='Internet',
        remove_canceled=False,
        remove_unconfirmed=False,
        color_code=False,
        print_options=_mod_print_options(),
    )
    service = ModSheetTestPrintService(
        repository,
        source,
        queue,
        lambda records, color_code=False: b'%PDF-test',
        tmp_path,
        clock=clock,
    )

    state = service.run(
        test_settings,
        'America/Los_Angeles',
        'a' * 32,
    )

    assert source.calls == [{
        'start_date': '9/21/2026',
        'end_date': '9/21/2026',
        'market_segment': 'Unsaved Test Market',
        'product_category': 'Windows',
        'source_type': 'Internet',
        'remove_canceled': False,
        'remove_unconfirmed': False,
        'limit': 1000,
    }]
    assert state['status'] == 'queued'
    assert state['job_id'] == 77
    assert queue.immediate[0][0] == 'pdf:mod-test:' + ('a' * 32)
    assert queue.immediate[0][3] == _mod_print_options().snapshot()
    assert queue.immediate[0][1].read_bytes() == b'%PDF-test'
    assert repository.settings() == saved
    assert repository.state() == {}
    assert repository.db.get(REFERENCE_OUTBOX_KEY) is None
    assert repository.test_state()['message'] == 'Test print queued for immediate printing'


def test_test_print_no_appointments_never_enters_print_queue(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 12, 0))
    db = Database(tmp_path / 'printer.db')
    repository = ModSheetAutomationRepository(db)
    source = FakeSource([()])
    queue = FakeQueue()
    service = ModSheetTestPrintService(
        repository,
        source,
        queue,
        lambda records, color_code=False: b'%PDF-test',
        tmp_path,
        clock=clock,
    )

    state = service.run(
        ModSheetAutomationSettings(print_options=_mod_print_options()),
        'America/Los_Angeles',
        'b' * 32,
    )

    assert state['status'] == 'no_appointments'
    assert queue.immediate == []
    assert repository.test_state()['message'] == 'No appointments'


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


def test_immediate_generated_pdf_is_selected_before_older_normal_queue_jobs(tmp_path):
    db = Database(tmp_path / 'printer.db')
    queue = PrintQueueRepository(db)
    pdf = tmp_path / 'test.pdf'
    pdf.write_bytes(b'%PDF-fake')
    options = _mod_print_options().snapshot()

    normal_id, _ = queue.enqueue_generated_pdf(
        'pdf:older-normal', pdf, 1, PrintOptions().snapshot(), 100.0
    )
    immediate_id, created = queue.enqueue_immediate_generated_pdf(
        'pdf:mod-test:token', pdf, 1, options, 101.0
    )

    assert created is True
    assert normal_id < immediate_id
    assert queue.due_jobs(101.0, True)[0]['id'] == normal_id
    immediate = queue.immediate_jobs(101.0)
    assert [job['id'] for job in immediate] == [immediate_id]
    assert db.job_print_settings(immediate_id) == options

    db.execute(
        "UPDATE jobs SET status='PRINTED',completed=?,updated=? WHERE id=?",
        (102.0, 102.0, immediate_id),
    )
    assert queue.immediate_jobs(102.0) == []


def test_failed_morning_document_write_does_not_save_reference_handoff(tmp_path, monkeypatch):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    records = (ModSheetRecord(source_id='source-1', work_order_number='0001'),)
    daily, repository, queue = _service(tmp_path, FakeSource([records]), clock)

    def failed_write(*args, **kwargs):
        raise OSError('temporary storage failure')

    monkeypatch.setattr('printer_app.mod_sheets.service._write_pdf', failed_write)
    assert daily.run_due()['status'] == 'retry_wait'
    assert repository.db.get(REFERENCE_OUTBOX_KEY) is None
    assert queue.enqueued == []


def test_morning_reference_is_delivered_only_after_mod_job_prints(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    records = (
        ModSheetRecord(source_id='source-1', work_order_number='0001', lead_name='Jordan'),
    )
    source = FakeSource([records])
    payload = b'%PDF-exact-morning-document'
    daily, repository, queue = _service(
        tmp_path, source, clock, renderer=lambda records, color_code=False: payload,
    )
    state = daily.run_due()
    # The document path and source records must survive a process restart.
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    pending = repository.pending_morning_references()
    assert Path(pending[0]['pdf_path']) == queue.enqueued[0][1]
    sink = FakeReferenceSink()
    delivery = ModSheetReferenceDeliveryService(
        repository,
        FakeSource([]),
        queue,
        sink,
        'America/Los_Angeles',
        clock=clock,
    )

    queue.statuses[state['job_id']] = {'id': state['job_id'], 'status': 'READY'}
    assert delivery.deliver_printed_mornings() == 0
    assert sink.published == []

    queue.statuses[state['job_id']] = {'id': state['job_id'], 'status': 'PRINTED'}
    assert delivery.deliver_printed_mornings() == 1
    assert sink.published[0][0:2] == ('2026-09-21', 'morning')
    assert sink.published[0][2] == records
    assert sink.pdf_payloads == [payload]
    assert delivery.deliver_printed_mornings() == 0
    assert len(sink.published) == 1


def test_morning_reference_failure_never_breaks_print_state(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    records = (ModSheetRecord(source_id='source-1', work_order_number='0001'),)
    daily, repository, queue = _service(tmp_path, FakeSource([records]), clock)
    state = daily.run_due()
    queue.statuses[state['job_id']] = {'id': state['job_id'], 'status': 'PRINTED'}
    sink = FakeReferenceSink(fail=True)
    delivery = ModSheetReferenceDeliveryService(
        repository,
        FakeSource([]),
        queue,
        sink,
        'America/Los_Angeles',
        clock=clock,
    )

    assert delivery.deliver_printed_mornings() == 0
    assert repository.state()['status'] == 'queued'
    assert repository.pending_morning_references()
    sink.fail = False
    assert delivery.deliver_printed_mornings() == 1
    assert sink.pdf_payloads == [b'%PDF-fake']
    assert repository.pending_morning_references() == []


@pytest.mark.parametrize('failure', ['missing', 'unreadable'])
def test_morning_document_read_failure_remains_pending_for_retry(tmp_path, monkeypatch, failure):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    records = (ModSheetRecord(source_id='source-1', work_order_number='0001'),)
    daily, repository, queue = _service(tmp_path, FakeSource([records]), clock)
    state = daily.run_due()
    queue.statuses[state['job_id']] = {'id': state['job_id'], 'status': 'PRINTED'}
    path = queue.enqueued[0][1]
    sink = FakeReferenceSink()
    delivery = ModSheetReferenceDeliveryService(
        repository, FakeSource([]), queue, sink, 'America/Los_Angeles', clock=clock,
    )
    with monkeypatch.context() as patch:
        if failure == 'missing':
            path.unlink()
        else:
            original_read = Path.read_bytes

            def unreadable(target):
                if target == path:
                    raise PermissionError('document temporarily unreadable')
                return original_read(target)

            patch.setattr(Path, 'read_bytes', unreadable)
        assert delivery.deliver_printed_mornings() == 0
    assert sink.published == []
    assert repository.pending_morning_references()
    assert repository.state()['status'] == 'queued'

    path.write_bytes(b'%PDF-fake')
    assert delivery.deliver_printed_mornings() == 1
    assert sink.pdf_payloads == [b'%PDF-fake']


def test_legacy_morning_outbox_without_document_still_delivers_reference_data(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    records = (ModSheetRecord(source_id='source-1', work_order_number='0001'),)
    daily, repository, queue = _service(tmp_path, FakeSource([records]), clock)
    state = daily.run_due()
    outbox = repository.db.get(REFERENCE_OUTBOX_KEY)
    del outbox['2026-09-21']['pdf_path']
    repository.db.set(REFERENCE_OUTBOX_KEY, outbox)
    queue.statuses[state['job_id']] = {'id': state['job_id'], 'status': 'PRINTED'}
    sink = FakeReferenceSink()
    delivery = ModSheetReferenceDeliveryService(
        repository, FakeSource([]), queue, sink, 'America/Los_Angeles', clock=clock,
    )

    assert delivery.deliver_printed_mornings() == 1
    assert sink.published[0][2] == records
    assert sink.pdf_payloads == [None]
    assert repository.pending_morning_references() == []


def test_final_reference_pull_runs_at_11_pm_and_uses_current_day(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 22, 59))
    db = Database(tmp_path / 'printer.db')
    repository = ModSheetAutomationRepository(db)
    repository.save_settings(ModSheetAutomationSettings(
        market_segment='Olympia',
        product_category='All',
        source_type='All',
        remove_canceled=True,
        remove_unconfirmed=True,
    ))
    final_records = (
        ModSheetRecord(
            source_id='source-final',
            work_order_number='0009',
            lead_name='Jordan Example',
            assigned_service_resources=('Final Rep',),
        ),
    )
    source = FakeSource([final_records])
    sink = FakeReferenceSink()
    delivery = ModSheetReferenceDeliveryService(
        repository,
        source,
        FakeQueue(),
        sink,
        'America/Los_Angeles',
        clock=clock,
    )

    assert delivery.final_due() is False
    clock.value = _stamp(2026, 9, 21, 23, 0)
    assert delivery.final_due() is True
    state = delivery.run_final()

    assert state['status'] == 'complete'
    assert state['appointments'] == 1
    assert source.calls == [{
        'start_date': '2026-09-21', 'end_date': '2026-09-21',
        'market_segment': '', 'product_category': '', 'source_type': '',
        'remove_canceled': False, 'remove_unconfirmed': False, 'limit': None,
    }]
    assert sink.published[0][0:2] == ('2026-09-21', 'final')
    assert sink.published[0][2] == final_records
    assert delivery.final_due() is False


def test_references_run_on_weekends_without_print_settings(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 20, 23))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    sink = FakeReferenceSink()
    delivery = ModSheetReferenceDeliveryService(
        repository, FakeSource([()]), FakeQueue(), sink, 'America/Los_Angeles', clock=clock,
    )

    assert delivery.final_due()
    assert delivery.run_final()['status'] == 'complete'
    assert sink.published[0][0] == '2026-09-20'


def test_hourly_references_use_today_without_print_filters_and_survive_restart(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 20, 10, 15))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    records = (ModSheetRecord(
        source_id='source-1', work_order_number='0011',
        assigned_service_resources=('First Rep', 'Second Rep'),
    ),)
    source, queue, sink = FakeSource([records, records]), FakeQueue(), FakeReferenceSink()
    delivery = ModSheetReferenceDeliveryService(
        repository, source, queue, sink, 'America/Los_Angeles', clock=clock,
    )

    assert delivery.hourly_due()
    assert delivery.run_hourly()['status'] == 'complete'
    assert source.calls == [{
        'start_date': '2026-09-20', 'end_date': '2026-09-20',
        'market_segment': '', 'product_category': '', 'source_type': '',
        'remove_canceled': False, 'remove_unconfirmed': False, 'limit': None,
    }]
    assert sink.published[0][0:3] == ('2026-09-20', 'final', records)
    assert sink.pdf_payloads == [None]
    restarted = ModSheetReferenceDeliveryService(
        ModSheetAutomationRepository(Database(tmp_path / 'printer.db')),
        source, queue, sink, 'America/Los_Angeles', clock=clock,
    )
    clock.value = _stamp(2026, 9, 20, 10, 59)
    assert not restarted.hourly_due()
    restarted.run_hourly()
    assert len(source.calls) == 1
    clock.value = _stamp(2026, 9, 20, 11)
    assert restarted.hourly_due()
    assert restarted.run_hourly()['status'] == 'complete'
    assert len(source.calls) == 2
    assert queue.enqueued == queue.immediate == []
    assert repository.state() == repository.final_reference_state() == {}


def test_hourly_refresh_leaves_11_pm_to_final_and_rolls_over_to_current_day(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 22, 59))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    source, sink = FakeSource([(), (), ()]), FakeReferenceSink()
    delivery = ModSheetReferenceDeliveryService(
        repository, source, FakeQueue(), sink, 'America/Los_Angeles', clock=clock,
    )

    assert delivery.run_hourly()['status'] == 'complete'
    clock.value = _stamp(2026, 9, 21, 23)
    assert delivery.final_due()
    assert not delivery.hourly_due()
    assert delivery.run_final()['status'] == 'complete'
    clock.value = _stamp(2026, 9, 21, 23, 59)
    delivery.run_hourly()
    assert len(source.calls) == 2
    assert not delivery.final_due()
    clock.value = _stamp(2026, 9, 22, 0)
    assert delivery.hourly_due()
    assert delivery.run_hourly()['day'] == '2026-09-22'
    assert [call['start_date'] for call in source.calls] == [
        '2026-09-21', '2026-09-21', '2026-09-22',
    ]
    assert all(call['end_date'] == call['start_date'] for call in source.calls)
    assert repository.final_reference_state()['day'] == '2026-09-21'


@pytest.mark.parametrize('failure', ['source', 'sink'])
def test_failed_hourly_refresh_retries_next_hour_without_blocking_final(tmp_path, failure):
    clock = MutableClock(_stamp(2026, 9, 21, 21))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    source = FakeSource([RuntimeError('unavailable') if failure == 'source' else (), ()])
    sink = FakeReferenceSink(fail=failure == 'sink')
    delivery = ModSheetReferenceDeliveryService(
        repository, source, FakeQueue(), sink, 'America/Los_Angeles', clock=clock,
    )

    assert delivery.run_hourly()['status'] == 'failed'
    assert not delivery.hourly_due()
    delivery.run_hourly()
    assert len(source.calls) == 1
    clock.value = _stamp(2026, 9, 21, 22)
    sink.fail = False
    assert delivery.hourly_due()
    assert delivery.run_hourly()['status'] == 'complete'
    assert delivery.final_due(_stamp(2026, 9, 21, 23))


def test_interrupted_hourly_refresh_is_recovered_in_same_hour(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 10, 30))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    repository.save_hourly_reference_state({
        'day': '2026-09-21', 'hour': '2026-09-21T10-07:00', 'status': 'running',
    })
    source = FakeSource([()])
    delivery = ModSheetReferenceDeliveryService(
        repository, source, FakeQueue(), FakeReferenceSink(), 'America/Los_Angeles', clock=clock,
    )

    assert delivery.hourly_due()
    assert delivery.run_hourly()['status'] == 'complete'
    assert not delivery.hourly_due()
    assert len(source.calls) == 1


def test_hourly_refresh_distinguishes_repeated_daylight_saving_hour(tmp_path):
    clock = MutableClock(datetime(2026, 11, 1, 1, tzinfo=ZONE, fold=0).timestamp())
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    source = FakeSource([(), ()])
    delivery = ModSheetReferenceDeliveryService(
        repository, source, FakeQueue(), FakeReferenceSink(), 'America/Los_Angeles', clock=clock,
    )

    first = delivery.run_hourly()
    clock.value = datetime(2026, 11, 1, 1, tzinfo=ZONE, fold=1).timestamp()
    assert delivery.hourly_due()
    second = delivery.run_hourly()
    assert first['hour'] != second['hour']
    assert first['day'] == second['day'] == '2026-11-01'
    assert len(source.calls) == 2


def test_hourly_refresh_is_optional_without_gallery_sink(tmp_path):
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    source = FakeSource([])
    delivery = ModSheetReferenceDeliveryService(
        repository, source, FakeQueue(), None, 'America/Los_Angeles',
        clock=MutableClock(_stamp(2026, 9, 21, 12)),
    )

    assert not delivery.hourly_due()
    assert delivery.run_hourly() == {}
    assert source.calls == []


@pytest.fixture
def manual_references(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 10, 15))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    records = (ModSheetRecord(source_id='source-1', work_order_number='0011',
                              assigned_service_resources=('Current Rep',)),)
    service = ModSheetReferenceDeliveryService(
        repository, FakeSource([records, records]), FakeQueue(), FakeReferenceSink(),
        'America/Los_Angeles', clock=clock,
    )
    return service, clock


def test_manual_reference_requests_coalesce_concurrent_clicks_and_running_request(manual_references, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import UUID

    service, clock = manual_references
    assert service.refresh_status() == {}
    assert not service.requested_due()
    assert service.run_requested() == {}
    barrier = Barrier(6)

    def click(_):
        barrier.wait()
        return service.request_refresh()

    with ThreadPoolExecutor(max_workers=6) as executor:
        requests = list(executor.map(click, range(6)))
    queued = requests[0]
    assert UUID(queued['id'])
    assert all(request == queued for request in requests)
    assert queued == {'id': queued['id'], 'status': 'queued', 'day': '2026-09-21', 'updated': clock()}
    assert service.requested_due()
    assert service.source.calls == service.reference_sink.published == []
    source_records = service.source.records

    def records(**filters):
        running = service.refresh_status()
        assert running['status'] == 'running'
        assert running['id'] == queued['id']
        assert service.request_refresh() == running
        return source_records(**filters)

    monkeypatch.setattr(service.source, 'records', records)
    complete = service.run_requested()
    assert complete['status'] == 'complete'
    assert complete['id'] == queued['id']
    assert complete['appointments'] == 1
    assert complete['enriched'] == 0
    assert service.refresh_status() == complete
    assert not service.requested_due()
    assert service.run_requested() == complete
    assert len(service.source.calls) == 1
    assert service.queue.enqueued == service.queue.immediate == []
    assert service.repository.db.rows('SELECT id FROM jobs') == []


@pytest.mark.parametrize(('automatic', 'hour'), [('hourly', 10), ('final', 23)])
def test_manual_reference_refresh_forces_today_after_automatic_pull(manual_references, automatic, hour):
    service, clock = manual_references
    clock.value = _stamp(2026, 9, 21, hour, 15)
    automatic_state = getattr(service, 'run_' + automatic)()
    assert automatic_state['status'] == 'complete'

    queued = service.request_refresh()
    complete = service.run_requested()

    assert complete['status'] == 'complete'
    assert complete['id'] == queued['id']
    assert len(service.source.calls) == 2
    assert all(call == {
        'start_date': '2026-09-21', 'end_date': '2026-09-21',
        'market_segment': '', 'product_category': '', 'source_type': '',
        'remove_canceled': False, 'remove_unconfirmed': False, 'limit': None,
    } for call in service.source.calls)
    assert getattr(service.repository, automatic + '_reference_state')() == automatic_state
    assert not service.hourly_due()
    assert not service.final_due()
    assert service.reference_sink.pdf_payloads == [None, None]
    assert service.queue.enqueued == service.queue.immediate == []
    assert service.request_refresh()['id'] != complete['id']


@pytest.mark.parametrize('status', ['queued', 'running'])
def test_manual_reference_request_survives_restart_and_uses_execution_day(manual_references, status):
    service, clock = manual_references
    clock.value = _stamp(2026, 9, 21, 23, 59)
    requested = service.request_refresh()
    if status == 'running':
        service.repository.save_reference_refresh_state(dict(requested, status='running'))
    clock.value = _stamp(2026, 9, 22, 0)
    restarted = ModSheetReferenceDeliveryService(
        ModSheetAutomationRepository(Database(service.repository.db.path)),
        service.source, service.queue, service.reference_sink, 'America/Los_Angeles', clock=clock,
    )

    assert restarted.refresh_status()['status'] == status
    assert restarted.request_refresh()['id'] == requested['id']
    assert restarted.requested_due()
    complete = restarted.run_requested()

    assert complete['id'] == requested['id']
    assert complete['status'] == 'complete'
    assert complete['day'] == '2026-09-22'
    assert complete['updated'] == clock()
    assert service.source.calls[0]['start_date'] == service.source.calls[0]['end_date'] == '2026-09-22'
    assert service.reference_sink.published[0][0:2] == ('2026-09-22', 'final')
    assert service.refresh_status() == complete
    assert service.repository.hourly_reference_state() == service.repository.final_reference_state() == {}


@pytest.mark.parametrize('failure', ['source', 'sink'])
def test_manual_reference_failure_is_visible_and_new_click_retries(manual_references, failure):
    service, _ = manual_references
    if failure == 'source':
        service.source.outcomes[0] = RuntimeError('Source unavailable')
    else:
        service.reference_sink.fail = True
    requested = service.request_refresh()

    failed = service.run_requested()

    assert failed['id'] == requested['id']
    assert failed['status'] == 'failed'
    assert 'unavailable' in failed['error']
    assert service.refresh_status() == failed
    assert not service.requested_due()
    assert service.run_requested() == failed
    assert len(service.source.calls) == 1
    service.reference_sink.fail = False
    retried = service.request_refresh()
    assert retried['id'] != failed['id']
    assert retried['status'] == 'queued'
    assert 'error' not in retried
    assert service.run_requested()['status'] == 'complete'
    assert len(service.source.calls) == 2
    assert service.queue.enqueued == service.queue.immediate == []


def test_manual_reference_request_without_sink_finishes_with_visible_error(manual_references):
    service, _ = manual_references
    service.reference_sink = None
    requested = service.request_refresh()

    failed = service.run_requested()

    assert failed['id'] == requested['id']
    assert failed['status'] == 'failed'
    assert failed['error'] == 'Card refresh is unavailable.'
    assert not service.requested_due()
    assert service.source.calls == []


def test_existing_cards_backfill_once_by_card_date_without_querying_tomorrow(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 12))
    db = Database(tmp_path / 'printer.db')
    repository = ModSheetAutomationRepository(db)
    db.set(REFERENCE_BACKFILL_KEY, 'full-card-search')  # Earlier cards lack lead status.
    sink = FakeReferenceSink(days=('2026-09-18', '2026-09-21', '2026-09-22'))
    source = FakeSource([(), ()])
    delivery = ModSheetReferenceDeliveryService(
        repository, source, FakeQueue(), sink, 'America/Los_Angeles', clock=clock,
    )

    delivery.backfill_existing()

    assert [call['start_date'] for call in source.calls] == ['2026-09-18', '2026-09-21']
    assert [entry[0:2] for entry in sink.published] == [
        ('2026-09-18', 'final'), ('2026-09-21', 'final'),
    ]
    assert repository.reference_backfill_complete()
    assert db.get(REFERENCE_BACKFILL_KEY) == 'work-order-lead-status'
    # The completed marker survives a worker restart.
    restarted = ModSheetReferenceDeliveryService(
        ModSheetAutomationRepository(Database(tmp_path / 'printer.db')),
        source, FakeQueue(), sink, 'America/Los_Angeles', clock=clock,
    )
    restarted.backfill_existing()
    assert len(source.calls) == 2
    # An initial daytime fill must not suppress tonight's final assignments.
    assert delivery.final_due(_stamp(2026, 9, 21, 23))


@pytest.mark.parametrize('trigger', ['manual', 'hourly', 'final'])
@pytest.mark.parametrize('appointment_failure', [False, True])
def test_card_refresh_resolves_all_work_orders_even_without_appointments(tmp_path, trigger, appointment_failure):
    from printer_app.mod_sheet_contract import WorkOrderLeadStatus

    clock = MutableClock(_stamp(2026, 9, 21, 23 if trigger == 'final' else 12))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    source = FakeSource([RuntimeError('appointments unavailable') if appointment_failure else ()])
    source.lead_results = (WorkOrderLeadStatus('0001', 'lead-one', 'Sold'),
                           WorkOrderLeadStatus('0002', 'lead-one', 'Sold'))
    sink = FakeReferenceSink()
    sink.numbers = ('0001', '0002')  # Scope comes from all retained cards, not today's results.
    delivery = ModSheetReferenceDeliveryService(repository, source, FakeQueue(), sink,
                                                'America/Los_Angeles', clock=clock)
    if trigger == 'manual':
        delivery.request_refresh()
        state = delivery.run_requested()
    else:
        state = getattr(delivery, 'run_' + trigger)()

    assert source.lead_calls == [('0001', '0002')]
    assert sink.lead_published == [(sink.numbers, source.lead_results, clock())]
    assert state['status'] == ('failed' if appointment_failure else 'complete')
    if not appointment_failure:
        assert state['lead_statuses'] == state['enriched'] == 2
    else:
        assert 'appointments unavailable' in state['error']


def test_failed_lead_pull_keeps_status_cache_and_does_not_block_reps(manual_references):
    service, _ = manual_references
    service.reference_sink.numbers = ('0001',)
    service.source.lead_results = RuntimeError('Lead permission denied')
    service.request_refresh()
    state = service.run_requested()
    assert state['status'] == 'failed'
    assert 'Lead permission denied' in state['error']
    assert len(service.reference_sink.published) == 1
    assert service.reference_sink.lead_published == []
    assert service.source.lead_calls == [('0001', '0011')]


def test_startup_direct_work_order_lookup_enriches_retained_cards_without_date_filter(tmp_path):
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    repository.complete_reference_backfill()
    source = FakeSource([])
    source.work_order_results = (
        ModSheetRecord(
            source_id='wo-source', work_order_number='0003',
            appointment_date='2026-09-21', lead_name='Resolved Customer',
            address='123 Resolved St', assigned_service_resources=('Resolved Rep',),
        ),
    )
    sink = FakeReferenceSink(days=())
    sink.numbers = ('0003',)
    delivery = ModSheetReferenceDeliveryService(
        repository, source, FakeQueue(), sink, 'America/Los_Angeles', clock=lambda: 100
    )

    delivery.backfill_existing()

    assert source.work_order_calls == [('0003',)]
    assert sink.work_order_published == [(sink.numbers, source.work_order_results, 100)]


def test_startup_status_refresh_ignores_completed_date_backfill_marker(tmp_path):
    from printer_app.mod_sheet_contract import WorkOrderLeadStatus

    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    repository.complete_reference_backfill()
    source = FakeSource([])
    source.lead_results = (WorkOrderLeadStatus('0003', 'lead-one', 'Sold'),)
    sink = FakeReferenceSink(days=())  # Undated cards still have work orders.
    sink.numbers = ('0003',)
    delivery = ModSheetReferenceDeliveryService(repository, source, FakeQueue(), sink,
                                                'America/Los_Angeles', clock=lambda: 100)
    delivery.backfill_existing()
    delivery.backfill_existing()  # Restart retries cards still missing status.
    assert source.calls == []
    assert source.lead_calls == [('0003',), ('0003',)]
    assert len(sink.lead_published) == 2
    assert sink.repair_calls == 2
    assert sink.lead_scopes == [
        ('read', False), ('read', True), ('publish', True),
        ('read', False), ('read', True), ('publish', True),
    ]


def test_startup_status_failure_retries_in_next_hour_without_clearing_cache(tmp_path):
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    repository.complete_reference_backfill()
    source = FakeSource([()])
    source.lead_results = RuntimeError('Lead lookup unavailable')
    sink = FakeReferenceSink()
    sink.numbers = ('0004',)
    delivery = ModSheetReferenceDeliveryService(repository, source, FakeQueue(), sink,
                                                'America/Los_Angeles', clock=lambda: _stamp(2026, 9, 21, 12))
    delivery.backfill_existing()
    assert sink.lead_published == []
    source.lead_results = ()
    assert delivery.run_hourly()['status'] == 'complete'
    assert source.lead_calls == [('0004',), ('0004',)]
    assert len(sink.lead_published) == 1


def test_startup_repairs_and_refreshes_only_missing_status_cards_across_dates(tmp_path):
    from printer_app.gallery.bootstrap import GalleryReferenceInbox
    from printer_app.mod_sheet_contract import WorkOrderLeadStatus
    from printer_app.tests.test_gallery_reference import _card

    sink = GalleryReferenceInbox(tmp_path)
    sink.service.initialize()
    _card(sink.service, 'older', '02278850 1', day='2026-09-01')
    _card(sink.service, 'undated', '02278851', day=None)
    _card(sink.service, 'known', '02278852', day='2026-09-25')
    sink.publish_lead_statuses(('02278852',), (WorkOrderLeadStatus('02278852', 'shared', 'Open'),), 1)
    with sink.service.repository.connect() as c:
        c.execute("UPDATE items SET work_order_number='022788501',work_order_key='022788501' WHERE id='older'")
    before = sink.service.item('known')
    source = FakeSource([])
    source.lead_results = (WorkOrderLeadStatus('02278850', 'shared', 'Sold'),
                           WorkOrderLeadStatus('02278851', 'other', 'Open'))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    repository.complete_reference_backfill()
    delivery = ModSheetReferenceDeliveryService(repository, source, FakeQueue(), sink,
                                                'America/Los_Angeles', clock=lambda: 100)

    delivery.backfill_existing()

    assert source.calls == []
    assert source.lead_calls == [('02278850', '02278851')]
    assert sink.service.item('older')['work_order_number'] == '02278850'
    assert sink.service.item('older')['sales_lead_status'] == 'Sold'
    assert sink.service.item('undated')['sales_lead_status'] == 'Open'
    assert sink.service.item('known') == before
    delivery.backfill_existing()
    assert source.lead_calls == [('02278850', '02278851')]


def test_refresh_links_real_cards_by_work_order_without_any_appointment(tmp_path):
    from printer_app.gallery.bootstrap import GalleryReferenceInbox
    from printer_app.mod_sheet_contract import WorkOrderLeadStatus
    from printer_app.tests.test_gallery_reference import _card

    sink = GalleryReferenceInbox(tmp_path)
    sink.service.initialize()
    _card(sink.service, 'older', '00000001', day='2026-09-01')
    _card(sink.service, 'undated', '00000002', day=None)
    _card(sink.service, 'future', '00000003', day='2026-09-25')
    _card(sink.service, 'other-lead-same-name', '00000004', day='2026-09-21')
    source = FakeSource([()])
    source.lead_results = tuple(WorkOrderLeadStatus(number, 'shared', 'Sold')
                               for number in ('00000001', '00000002', '00000003')) + (
        WorkOrderLeadStatus('00000004', 'different', 'Open'),)
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    delivery = ModSheetReferenceDeliveryService(repository, source, FakeQueue(), sink,
                                                'America/Los_Angeles', clock=lambda: _stamp(2026, 9, 21, 12))
    delivery.request_refresh()
    result = delivery.run_requested()

    assert result['status'] == 'complete'
    assert set(source.lead_calls[0]) == {'00000001', '00000002', '00000003', '00000004'}
    for ident in ('older', 'undated', 'future'):
        assert sink.service.item(ident)['sales_lead_status'] == 'Sold'
        assert sink.service.item(ident)['lead_source_id'] == 'shared'
    assert sink.service.item('other-lead-same-name')['sales_lead_status'] == 'Open'


def test_refresh_prepares_current_work_order_status_before_scan_arrives(tmp_path):
    from printer_app.gallery.bootstrap import GalleryReferenceInbox
    from printer_app.mod_sheet_contract import WorkOrderLeadStatus
    from printer_app.tests.test_gallery_reference import _card

    sink = GalleryReferenceInbox(tmp_path)
    sink.service.initialize()
    # Old references alone must not grow the hourly lookup forever.
    sink.publish('2026-01-01', 'final', [ModSheetRecord('old', work_order_number='9999')], 1)
    source = FakeSource([(ModSheetRecord('today', work_order_number='00000010'),)])
    source.lead_results = (WorkOrderLeadStatus('00000010', 'shared', 'Sold'),)
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    delivery = ModSheetReferenceDeliveryService(repository, source, FakeQueue(), sink,
                                                'America/Los_Angeles', clock=lambda: _stamp(2026, 9, 21, 12))
    assert delivery.run_hourly()['status'] == 'complete'
    assert source.lead_calls == [('00000010',)]
    _card(sink.service, 'later-scan', '00000010', day=None)
    assert sink.service.item('later-scan')['sales_lead_status'] == 'Sold'


@pytest.mark.parametrize('marker', [None, False, True, 'previous-contract', 'full-card-search'])
def test_backfill_requires_the_current_full_search_contract(tmp_path, marker):
    db = Database(tmp_path / 'printer.db')
    db.set(REFERENCE_BACKFILL_KEY, marker)
    repository = ModSheetAutomationRepository(db)
    assert not repository.reference_backfill_complete()
    repository.complete_reference_backfill()
    assert repository.reference_backfill_complete()
    assert db.get(REFERENCE_BACKFILL_KEY) == 'work-order-lead-status'


def test_failed_backfill_keeps_other_dates_and_can_retry_on_restart(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 12))
    repository = ModSheetAutomationRepository(Database(tmp_path / 'printer.db'))
    sink = FakeReferenceSink(days=('2026-09-18', '2026-09-19'))
    source = FakeSource([RuntimeError('unavailable'), ()])
    delivery = ModSheetReferenceDeliveryService(
        repository, source, FakeQueue(), sink, 'America/Los_Angeles', clock=clock,
    )

    delivery.backfill_existing()

    assert not repository.reference_backfill_complete()
    assert [entry[0] for entry in sink.published] == ['2026-09-19']
    source.outcomes = [(), ()]
    delivery.backfill_existing()
    assert repository.reference_backfill_complete()


def test_final_reference_failure_leaves_gallery_optional(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 23, 20))
    db = Database(tmp_path / 'printer.db')
    repository = ModSheetAutomationRepository(db)
    repository.save_settings(ModSheetAutomationSettings())
    delivery = ModSheetReferenceDeliveryService(
        repository,
        FakeSource([RuntimeError('source unavailable')]),
        FakeQueue(),
        FakeReferenceSink(),
        'America/Los_Angeles',
        clock=clock,
    )

    state = delivery.run_final()

    assert state['status'] == 'failed'
    assert 'source unavailable' in state['error']
    assert delivery.final_due() is False


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


def test_mod_sheet_automation_has_no_salesforce_field_structures():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for path in (root / 'mod_sheets').glob('*.py'):
        text = path.read_text()
        assert 'FSSK__' not in text, str(path)
        assert 'Lead__r' not in text, str(path)

    assert not (root / 'salesforce_sandbox/pdf_renderer.py').exists()
    assert not (root / 'static/salesforce_sandbox.js').exists()
    assert not (root / 'static/salesforce_sandbox.css').exists()

    runtime = (root / 'static/mod_sheets/runtime.js').read_text()
    styles = (root / 'static/mod_sheets/shared.css').read_text()
    worker = (root / 'worker.py').read_text()
    assert 'Salesforce' not in runtime
    assert '.sf-' not in styles
    assert worker.index('engine.queue.immediate_jobs(now)') < worker.index('engine.tick()')
    assert 'captured.print_options' not in worker


def test_mod_print_form_maps_only_to_mod_print_options():
    from flask import Flask

    from printer_app.mod_sheets.web import _settings_from_form

    app = Flask(__name__)
    with app.test_request_context('/mod-sheets/settings', method='POST', data={
        'marketsegment': 'Olympia',
        'productCategory': 'Roofing',
        'sourceType': 'Canvass',
        'removeCanceled': '1',
        'removeUnconfirmed': '1',
        'colorCode': '1',
        'printPaper': 'letter',
        'printOrientation': 'portrait',
        'printColor': 'color',
        'printSides': 'one-sided',
        'printCopies': '3',
        'pdfScaling': 'fit',
    }):
        settings = _settings_from_form()

    assert settings.market_segment == 'Olympia'
    assert settings.product_category == 'Roofing'
    assert settings.print_options == PrintOptions(
        paper='letter',
        orientation='portrait',
        color='color',
        sides='one-sided',
        copies=3,
        pdf_scaling='fit',
    )


def test_mod_settings_page_has_separate_print_settings_and_immediate_test():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / 'templates/mod_sheet_settings.html').read_text()
    base = (root / 'templates/base.html').read_text()

    assert 'Save Settings' in template
    assert 'Test Print Now' in template
    assert 'MOD Print Settings' in template
    for field in (
        'printPaper', 'printOrientation', 'printColor',
        'printSides', 'printCopies', 'pdfScaling',
    ):
        assert f'name="{field}"' in template
    assert 'goes ahead of waiting software-queue jobs' in template
    assert 'does not save them' in template
    assert 'always the current day' in template
    assert 'name="startdate"' not in template
    assert 'name="enddate"' not in template
    assert "url_for('mod_sheets.settings_page')" in base
    assert '>MOD Sheets<' in base
    assert '>MOD Settings<' in base
