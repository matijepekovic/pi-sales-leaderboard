"""Daily MOD Sheet automation and immediate test-print regressions."""
from datetime import datetime
from zoneinfo import ZoneInfo

from printer_app.db import Database
from printer_app.mod_sheets.policy import (
    DailyModSheetSchedule,
    ModSheetAutomationSettings,
)
from printer_app.mod_sheets.repository import ModSheetAutomationRepository, SETTINGS_KEY
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

    def dates(self):
        return self.days

    def publish(self, day, kind, records, captured):
        if self.fail:
            raise RuntimeError('reference sink unavailable')
        records = tuple(records)
        self.published.append((day, kind, records, captured))
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


def test_morning_reference_is_delivered_only_after_mod_job_prints(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    records = (
        ModSheetRecord(source_id='source-1', work_order_number='0001', lead_name='Jordan'),
    )
    source = FakeSource([records])
    daily, repository, queue = _service(tmp_path, source, clock)
    state = daily.run_due()
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
    assert delivery.deliver_printed_mornings() == 0
    assert len(sink.published) == 1


def test_morning_reference_failure_never_breaks_print_state(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 7, 0))
    records = (ModSheetRecord(source_id='source-1', work_order_number='0001'),)
    daily, repository, queue = _service(tmp_path, FakeSource([records]), clock)
    state = daily.run_due()
    queue.statuses[state['job_id']] = {'id': state['job_id'], 'status': 'PRINTED'}
    delivery = ModSheetReferenceDeliveryService(
        repository,
        FakeSource([]),
        queue,
        FakeReferenceSink(fail=True),
        'America/Los_Angeles',
        clock=clock,
    )

    assert delivery.deliver_printed_mornings() == 0
    assert repository.state()['status'] == 'queued'
    assert repository.pending_morning_references()


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


def test_existing_cards_backfill_once_by_card_date_without_querying_tomorrow(tmp_path):
    clock = MutableClock(_stamp(2026, 9, 21, 12))
    db = Database(tmp_path / 'printer.db')
    repository = ModSheetAutomationRepository(db)
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
    # The completed marker survives a worker restart.
    restarted = ModSheetReferenceDeliveryService(
        ModSheetAutomationRepository(Database(tmp_path / 'printer.db')),
        source, FakeQueue(), sink, 'America/Los_Angeles', clock=clock,
    )
    restarted.backfill_existing()
    assert len(source.calls) == 2
    # An initial daytime fill must not suppress tonight's final assignments.
    assert delivery.final_due(_stamp(2026, 9, 21, 23))


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
