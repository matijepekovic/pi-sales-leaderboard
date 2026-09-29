"""Job map local-history, bounded sync, web, and architecture regressions."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from printer_app.db import Database
from printer_app.job_map.contract import (
    MapDiagnostics, MapFilterView, MapFilters, MapJob, MapQuery, MapRecord,
    MapSyncRequest, MapSyncView, MapView,
)
from printer_app.job_map.repository import JobMapRepository
from printer_app.job_map.service import JobMapService, JobMapSyncService
from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter


def _result(payload):
    return SimpleNamespace(stdout=json.dumps(payload), stderr='', returncode=0)


def _source_row(
        ident='08p000000000001AAA',
        *,
        work='0WO000000000001AAA',
        number='02257311',
        lead='00Q000000000001AAA',
        name='Customer One',
        status='Working',
        market='Olympia',
        product='Bath',
        rep='Rep One',
        lat='47.25',
        lon='-122.45',
        scheduled='2026-09-24T17:00:00.000+0000',
        created='2026-09-24T16:00:00.000+0000',
        appointment_status='Scheduled'):
    return {
        'Id': ident,
        'StatusCategory': appointment_status,
        'SchedStartTime': scheduled,
        'CreatedDate': created,
        'Latitude': lat,
        'Longitude': lon,
        'FSSK__FSK_Work_Order__c': work,
        'FSSK__FSK_Assigned_Service_Resource__r': {'Name': rep},
        'FSSK__FSK_Work_Order__r': {
            'WorkOrderNumber': number,
            'Product_Interest__c': product,
            'Lead__r': {
                'Id': lead,
                'Name': name,
                'Status': status,
                'Market__c': market,
            },
        },
    }


def _record(
        ident,
        work,
        number,
        *,
        scheduled_at=100.0,
        created_at=90.0,
        day='2026-09-24',
        canceled=False,
        status='Working',
        lat=47.02,
        lon=-122.0,
        market='Olympia',
        product='Bath',
        rep='Rep One'):
    return MapRecord(
        source_record_id=ident,
        work_order_id=work,
        work_order_number=number,
        scheduled_at=scheduled_at,
        scheduled_day=day,
        created_at=created_at,
        canceled=canceled,
        lead_name='Customer ' + number,
        lead_status=status,
        latitude=lat,
        longitude=lon,
        source_record_url='https://example.test/lead/' + number,
        market=market,
        product_type=product,
        assigned_rep=rep,
    )


def test_salesforce_map_history_is_bounded_by_market_and_dates_only():
    calls = []
    rows = [_source_row()]

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:3] == ['org', 'display']:
            return _result({'status': 0, 'result': {
                'username': 'rep@example.test',
                'alias': 'work',
                'instanceUrl': 'https://example.my.salesforce.com',
                'id': '00D000000000123',
                'connectedStatus': 'Connected',
            }})
        query = command[command.index('--query') + 1]
        if ' FROM User ' in query:
            return _result({'status': 0, 'result': {
                'records': [{'TimeZoneSidKey': 'America/Los_Angeles'}],
            }})
        assert ' FROM ServiceAppointment WHERE ' in query
        page = [] if ' AND Id > ' in query else rows
        return _result({'status': 0, 'result': {'records': page}})

    adapter = SalesforceCliAdapter(runner=runner, executable='/fake/sf')
    records = adapter.map_records(
        start_date='2026-09-01',
        end_date='2026-09-29',
        market='Olympia',
    )

    assert len(records) == 1
    record = records[0]
    assert record.source_record_id == '08p000000000001AAA'
    assert record.work_order_number == '02257311'
    assert record.assigned_rep == 'Rep One'
    assert (record.latitude, record.longitude) == (47.25, -122.45)
    assert record.scheduled_day == '2026-09-24'

    queries = [
        command[command.index('--query') + 1]
        for command, _ in calls if command[1:3] == ['data', 'query']
    ]
    appointment = next(q for q in queries if ' FROM ServiceAppointment WHERE ' in q)
    assert "Lead__r.Market__c = 'Olympia'" in appointment
    assert 'SchedStartTime >=' in appointment
    assert 'SchedStartTime <' in appointment
    assert 'Product_Interest__c INCLUDES' not in appointment
    assert 'Assigned_Service_Resource__r.Name =' not in appointment
    assert 'Latitude >=' not in appointment
    assert 'Longitude >=' not in appointment
    first_appointment_call = next(
        kwargs for command, kwargs in calls
        if command[1:3] == ['data', 'query']
        and ' FROM ServiceAppointment WHERE ' in command[command.index('--query') + 1]
    )
    assert first_appointment_call['timeout'] == 120


def test_repository_replaces_only_requested_market_date_slice(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    olympia_old = _record('08p000000000001AAA', 'wo1', 'WO1', day='2026-09-01')
    olympia_new = _record('08p000000000002AAA', 'wo2', 'WO2', day='2026-09-02')
    seattle = _record(
        '08p000000000003AAA', 'wo3', 'WO3',
        day='2026-09-01', market='Seattle',
    )

    repository.replace_range('Olympia', '2026-09-01', '2026-09-30',
                             (olympia_old,), 10.0)
    repository.replace_range('Seattle', '2026-09-01', '2026-09-30',
                             (seattle,), 11.0)
    repository.replace_range('Olympia', '2026-09-01', '2026-09-30',
                             (olympia_new,), 12.0)

    assert [r.work_order_number for r in repository.records(market='Olympia')] == ['WO2']
    assert [r.work_order_number for r in repository.records(market='Seattle')] == ['WO3']
    assert repository.latest_sync_time('Olympia') == 12.0
    filters = repository.local_filters()
    assert filters.markets == ('Olympia', 'Seattle')
    assert filters.product_types == ('Bath',)
    assert filters.reps == ('Rep One',)


def test_local_map_groups_before_rep_filter_and_calculates_distance_once():
    records = (
        _record('a1', 'wo1', 'WO1', rep='Rep One', lat=47.02),
        _record('a2', 'wo1', 'WO1', rep='Rep Two', lat=47.02),
        _record('a3', 'wo2', 'WO2', rep='Rep One', lat=47.10),
        _record('a4', 'wo3', 'WO3', rep='Rep One', status='New', lat=47.01),
        _record('a5', 'wo4', 'WO4', rep='Rep One', lat=None, lon=None),
        _record('a6', 'wo5', 'WO5', rep='Rep One', product='Windows', lat=47.01),
    )

    class Repository:
        def records(self, *, market=''):
            assert market == 'Olympia'
            return records

        def coverage(self):
            return {'olympia': {'market': 'Olympia'}}

        def latest_sync_time(self, market=''):
            return 123.0

    service = JobMapService(Repository(), object(), lambda records: b'pdf')
    view = service.view(
        47.0, -122.0,
        market='Olympia', product_type='Bath', rep='Rep One',
    )

    assert [job.work_order_number for job in view.jobs] == ['WO1']
    assert view.jobs[0].assigned_reps == ('Rep One', 'Rep Two')
    assert view.diagnostics.local_records == 5
    assert view.diagnostics.grouped_jobs == 4
    assert view.diagnostics.rep_matched_jobs == 4
    assert view.diagnostics.jobs_with_location == 3
    assert view.diagnostics.jobs_missing_location == 1
    assert view.diagnostics.excluded_status == 1
    assert view.diagnostics.outside_radius == 1
    assert view.diagnostics.visible_jobs == 1
    assert {item.outcome for item in view.diagnostics.candidates} == {
        'visible', 'excluded-status', 'outside-radius'
    }
    assert view.captured_at == 123.0


def test_map_view_never_requests_external_history_when_local_store_is_empty():
    class Repository:
        def records(self, *, market=''):
            return ()

        def coverage(self):
            return {}

        def latest_sync_time(self, market=''):
            return 0.0

    class Source:
        def map_records(self, **kwargs):
            raise AssertionError('browser map view must never call the external source')

    service = JobMapService(Repository(), Source(), lambda records: b'pdf')
    view = service.view(47.0, -122.0, market='Olympia', rep='Rep One')

    assert view.jobs == ()
    assert 'Load a history range first' in view.error


def test_worker_history_sync_splits_year_range_into_bounded_chunks(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    repository.request_sync(
        'sync-1',
        MapSyncRequest('2026-07-01', '2026-09-29', 'Olympia'),
        1.0,
    )
    calls = []

    class Source:
        def map_filters(self):
            return MapFilters()

        def map_records(self, *, start_date, end_date, market):
            calls.append((start_date, end_date, market))
            return (_record(
                'id-' + start_date, 'wo-' + start_date, start_date,
                day=start_date, scheduled_at=float(len(calls)),
            ),)

    service = JobMapSyncService(repository, Source(), clock=lambda: 200.0)
    state = service.run_requested()

    assert state.status == 'complete'
    assert state.total_chunks == state.completed_chunks == 3
    assert calls == [
        ('2026-07-01', '2026-07-31', 'Olympia'),
        ('2026-08-01', '2026-08-31', 'Olympia'),
        ('2026-09-01', '2026-09-29', 'Olympia'),
    ]
    assert len(repository.records(market='Olympia')) == 3
    coverage = repository.coverage()['olympia']
    assert coverage['since_date'] == '2026-07-01'
    assert coverage['through_date'] == '2026-09-29'


def test_worker_incremental_sync_uses_cursor_and_updates_local_record(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    repository.replace_range(
        'Olympia', '2026-09-01', '2026-09-30',
        (_record('a1', 'wo1', 'WO1', status='Working'),),
        100.0,
    )
    repository.update_coverage(
        'Olympia', '2025-09-29', '2026-09-29', 100.0, cursor_at=100.0
    )
    calls = []

    class Source:
        def map_records_changed(
                self, *, modified_since, start_date, end_date, market):
            calls.append((modified_since, start_date, end_date, market))
            return (_record(
                'a1', 'wo1', 'WO1', status='Closed - Sale',
                scheduled_at=100.0, created_at=99.0,
            ),)

    service = JobMapSyncService(repository, Source(), clock=lambda: 5000.0)
    assert service.requested_due() is True
    service.run_requested()

    assert calls == [(
        100.0, '2025-09-29', date.today().isoformat(), 'Olympia'
    )]
    assert repository.records(market='Olympia')[0].lead_status == 'Closed - Sale'
    coverage = repository.coverage()['olympia']
    assert coverage['cursor_at'] == 5000.0
    assert coverage['last_incremental_attempt'] == 5000.0
    assert coverage['incremental_error'] == ''


def test_sync_request_rejects_missing_market_and_accepts_since_date(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    service = JobMapService(
        repository, object(), lambda records: b'pdf', clock=lambda: 50.0
    )

    with pytest.raises(ValueError, match='Choose a market'):
        service.request_sync(
            since_date='2026-08-29',
            through_date='2026-09-29',
            market='',
        )

    state = service.request_sync(
        since_date='2025-09-29',
        through_date='2026-09-29',
        market='Olympia',
    )
    assert state.status == 'queued'
    assert state.since_date == '2025-09-29'
    assert state.through_date == '2026-09-29'


def test_map_web_returns_local_jobs_and_queues_history_sync():
    flask = pytest.importorskip('flask')
    from printer_app.job_map.web import blueprint

    class Service:
        def filters(self, *, force_refresh=False):
            return MapFilterView(
                MapFilters(
                    markets=('Olympia',),
                    product_types=('Bath',),
                    reps=('Rep One',),
                ),
                captured_at=10.0,
            )

        def view(self, latitude, longitude, *, market='', product_type='', rep=''):
            assert (latitude, longitude) == (47.25, -122.45)
            assert (market, rep, product_type) == ('Olympia', 'Rep One', 'Bath')
            return MapView(
                jobs=(MapJob(
                    'wo', '02257311', 'Customer', 'Working', 47.25, -122.45,
                    'https://example.test/lead',
                    market='Olympia', product_type='Bath',
                    assigned_reps=('Rep One',),
                ),),
                captured_at=123.0,
                diagnostics=MapDiagnostics(
                    local_records=4,
                    grouped_jobs=3,
                    rep_matched_jobs=2,
                    jobs_with_location=2,
                    visible_jobs=1,
                ),
            )

        def request_sync(self, *, since_date, through_date, market):
            assert (since_date, through_date, market) == (
                '2025-09-29', '2026-09-29', 'Olympia'
            )
            return MapSyncView(
                status='queued',
                since_date=since_date,
                through_date=through_date,
                market=market,
                updated=50.0,
            )

        def sync_status(self):
            return MapSyncView(status='complete'), {
                'olympia': {
                    'market': 'Olympia',
                    'since_date': '2025-09-29',
                    'through_date': '2026-09-29',
                    'updated': 50.0,
                }
            }

        def mod_sheet(self, number):
            return b'%PDF-map'

    app = flask.Flask(__name__)
    app.secret_key = 'test'
    app.register_blueprint(blueprint(Service()))
    client = app.test_client()

    payload = client.get(
        '/map/api/jobs?lat=47.25&lon=-122.45&market=Olympia&rep=Rep%20One&product=Bath'
    ).get_json()
    assert payload['ok'] is True
    assert payload['jobs'][0]['work_order_number'] == '02257311'
    assert payload['diagnostics']['local_records'] == 4
    assert payload['diagnostics']['rep_matched_jobs'] == 2

    queued = client.post('/map/api/sync', data={
        'since': '2025-09-29',
        'through': '2026-09-29',
        'market': 'Olympia',
    }).get_json()
    assert queued['sync']['status'] == 'queued'

    sync = client.get('/map/api/sync').get_json()
    assert sync['coverage']['olympia']['since_date'] == '2025-09-29'


def test_job_map_architecture_keeps_source_sync_out_of_browser_map_path():
    root = Path(__file__).resolve().parents[1]

    for path in (root / 'job_map').glob('*.py'):
        assert 'salesforce' not in path.read_text().casefold()

    service = (root / 'job_map/service.py').read_text()
    local_service = service.split('class JobMapSyncService', 1)[0]
    assert '.map_records(' not in local_service
    assert 'self.repository.records(' in local_service
    assert service.count('_distance_miles(') == 2
    assert 'SYNC_CHUNK_DAYS = 31' in service
    assert 'INCREMENTAL_INTERVAL_SECONDS = 3600' in service
    assert 'map_records_changed' in service

    repository = (root / 'job_map/repository.py').read_text()
    assert 'job_map_records' in repository
    assert 'replace_range' in repository
    assert 'request_sync' in repository

    worker = (root / 'worker.py').read_text()
    assert 'JobMapSyncService' in worker
    assert 'background.submit(map_sync.run_requested)' in worker

    adapter = (root / 'salesforce_sandbox/adapter.py').read_text()
    assert 'def map_records(self, *, start_date, end_date, market):' in adapter
    assert 'def map_records_changed(' in adapter
    assert 'LastModifiedDate >=' in adapter
    map_block = adapter.split(
        '    def map_records(self, *, start_date, end_date, market):', 1
    )[1].split('    def explorer_objects', 1)[0]
    assert 'SchedStartTime >=' not in map_block
    # Date bounds come from the shared appointment scope, never phone geography.
    assert '_appointment_scope(' in map_block
    assert 'timeout=120' in map_block
    assert 'Latitude >=' not in map_block
    assert 'Longitude >=' not in map_block
    assert 'def map_jobs(' not in adapter

    web = (root / 'job_map/web.py').read_text()
    jobs_block = web.split("    @bp.get('/api/jobs')", 1)[1].split(
        "    @bp.route('/api/sync'", 1
    )[0]
    assert 'request_sync' not in jobs_block
    assert "request.args.get('refresh')" not in jobs_block

    template = (root / 'templates/job_map.html').read_text()
    assert 'id="jobMapLastMonth"' in template
    assert 'id="jobMapLastYear"' in template
    assert 'id="jobMapSince"' in template
    assert 'data-sync-url=' in template

    runtime = (root / 'static/job_map/map.js').read_text()
    assert "body.set('since'" in runtime
    assert "body.set('through'" in runtime
    assert "body.set('market'" in runtime
    assert "url.searchParams.set('refresh'" not in runtime
    assert 'Checking locally loaded jobs…' in runtime
    assert 'Local records after market/product:' in runtime

    schema = (root / 'db.py').read_text()
    assert 'CREATE TABLE IF NOT EXISTS job_map_records' in schema
