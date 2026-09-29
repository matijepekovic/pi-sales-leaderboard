"""Job map source, snapshots, exact distance, web, and architecture regressions."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from printer_app.db import Database
from printer_app.job_map.contract import (
    MapCandidateDiagnostic, MapDiagnostics, MapFilterView, MapFilters, MapJob,
    MapQuery, MapSourceDiagnostics, MapSourceSnapshot, MapView,
)
from printer_app.job_map.repository import JobMapRepository
from printer_app.job_map.service import JobMapRefreshService, JobMapService, MAX_RADIUS_MILES
from printer_app.salesforce_sandbox.adapter import PortalField, SalesforceCliAdapter
from printer_app.salesforce_sandbox.service import SalesforceSandboxService


def _result(payload):
    return SimpleNamespace(stdout=json.dumps(payload), stderr='', returncode=0)


def _row(ident, *, work='0WO000000000001AAA', number='02257311', lead='00Q000000000001AAA',
         name='Customer One', status='Working', market='Seattle',
         product='Bath', rep='Rep One', lat='47.25', lon='-122.45',
         scheduled='2026-09-24T17:00:00.000+0000', created='2026-09-24T16:00:00.000+0000',
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


def test_map_source_fetches_filtered_jobs_once_with_service_appointment_location():
    calls = []
    rows = [
        _row('08p000000000001AAA', scheduled='2026-09-23T17:00:00.000+0000'),
        _row('08p000000000002AAA', scheduled='2026-09-25T17:00:00.000+0000',
             appointment_status='Canceled', lat='1.0', lon='2.0'),
    ]

    def runner(command, **kwargs):
        calls.append(command)
        if command[1:3] == ['org', 'display']:
            return _result({'status': 0, 'result': {
                'username': 'rep@example.test', 'alias': 'work',
                'instanceUrl': 'https://example.my.salesforce.com',
                'id': '00D000000000123', 'connectedStatus': 'Connected',
            }})
        query = command[command.index('--query') + 1]
        assert ' FROM ServiceAppointment WHERE ' in query
        page = [] if ' AND Id > ' in query else rows
        return _result({'status': 0, 'result': {'records': page}})

    adapter = SalesforceCliAdapter(runner=runner, executable='/fake/sf')
    query = MapQuery(market='Seattle', product_type='Bath', rep='Rep One')
    snapshot = adapter.map_jobs(query)

    assert snapshot.jobs == (MapJob(
        source_id='0WO000000000001AAA', work_order_number='02257311',
        lead_name='Customer One', lead_status='Working', latitude=47.25, longitude=-122.45,
        source_record_url='https://example.my.salesforce.com/lightning/r/Lead/00Q000000000001AAA/view',
        market='Seattle', product_type='Bath', assigned_reps=('Rep One',),
    ),)
    assert snapshot.diagnostics == MapSourceDiagnostics(
        appointment_rows=2,
        grouped_jobs=1,
        jobs_with_location=1,
        jobs_missing_location=0,
    )

    queries = [
        call[call.index('--query') + 1]
        for call in calls if call[1:3] == ['data', 'query']
    ]
    first = queries[0]
    assert "FSSK__FSK_Work_Order__r.Lead__r.Market__c = 'Seattle'" in first
    assert "FSSK__FSK_Work_Order__r.Product_Interest__c INCLUDES ('Bath')" in first
    assert "FSSK__FSK_Assigned_Service_Resource__r.Name = 'Rep One'" in first
    assert "WorkType.Name LIKE '%Sales%'" in first
    assert 'Latitude, Longitude' in first
    assert 'Latitude >=' not in first
    assert 'Longitude >=' not in first
    assert 'FSSK__FSK_Work_Order__r.Latitude' not in first
    assert ' FROM Lead ' not in ' '.join(queries)


def test_map_source_has_no_location_fallback_when_appointment_location_is_missing():
    rows = [_row('08p000000000001AAA', lat=None, lon=None)]

    def runner(command, **kwargs):
        if command[1:3] == ['org', 'display']:
            return _result({'status': 0, 'result': {
                'username': 'rep@example.test', 'alias': 'work',
                'instanceUrl': 'https://example.my.salesforce.com',
                'id': '00D000000000123', 'connectedStatus': 'Connected',
            }})
        query = command[command.index('--query') + 1]
        return _result({'status': 0, 'result': {
            'records': [] if ' AND Id > ' in query else rows,
        }})

    adapter = SalesforceCliAdapter(runner=runner, executable='/fake/sf')
    snapshot = adapter.map_jobs(MapQuery(
        market='Seattle', product_type='Bath', rep='Rep One',
    ))
    assert snapshot.jobs == ()
    assert snapshot.diagnostics == MapSourceDiagnostics(
        appointment_rows=1,
        grouped_jobs=1,
        jobs_with_location=0,
        jobs_missing_location=1,
    )


def test_map_source_boundary_returns_normalized_filter_choices():
    class Adapter:
        def portal_field(self, key):
            values = {
                'market_segment': ('Seattle', 'Tacoma'),
                'product_category': ('Bath', 'Windows'),
            }[key]
            return PortalField(key, key, values)

    class RepRepository:
        def snapshot(self):
            return ('Rep One', 'Rep Two'), {}

    service = SalesforceSandboxService(Adapter(), rep_repository=RepRepository())
    assert service.map_filters() == MapFilters(
        markets=('Seattle', 'Tacoma'),
        product_types=('Bath', 'Windows'),
        reps=('Rep One', 'Rep Two'),
    )


def test_map_repository_round_trips_filter_only_snapshot_and_invalidates_old_contract(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    query = MapQuery(market='Seattle', product_type='Bath', rep='Rep One')
    filters = MapFilters(
        markets=('Seattle', 'Tacoma'),
        product_types=('Bath', 'Windows'),
        reps=('Rep One', 'Rep Two'),
    )
    job = MapJob(
        'wo', '02257311', 'Customer', 'Working', 47.25, -122.45,
        'https://example.test/lead', market='Seattle', product_type='Bath',
        assigned_reps=('Rep One',),
    )

    repository.replace_filter_snapshot(filters, 90.0)
    assert repository.filter_snapshot() == {'filters': filters, 'captured_at': 90.0}

    source_diagnostics = MapSourceDiagnostics(
        appointment_rows=3,
        grouped_jobs=2,
        jobs_with_location=1,
        jobs_missing_location=1,
    )
    repository.replace_snapshot(query, (job,), 100.0, source_diagnostics)
    assert repository.snapshot() == {
        'query': query,
        'jobs': (job,),
        'captured_at': 100.0,
        'diagnostics': source_diagnostics,
    }

    state = repository.request_refresh('refresh-1', query, 101.0)
    assert state['status'] == 'queued'
    assert state['query'] == query
    repository.save_refresh_state(dict(state, status='running', updated=102.0))
    assert repository.refresh_state()['status'] == 'running'

    source = (Path(__file__).resolve().parents[1] / 'job_map/repository.py').read_text()
    assert "SNAPSHOT_KEY = 'job_map_snapshot_v3'" in source
    assert "REFRESH_KEY = 'job_map_refresh_v3'" in source


def test_map_service_loads_filter_choices_before_any_location_query():
    requested = []

    class Repository:
        def filter_snapshot(self):
            return None

        def filter_refresh_state(self):
            return {}

        def request_filter_refresh(self, ident, now):
            requested.append((ident, now))
            return {'id': ident, 'status': 'queued', 'updated': now}

    service = JobMapService(Repository(), object(), lambda records: b'pdf', clock=lambda: 50.0)
    view = service.filters()

    assert view.filters == MapFilters()
    assert view.refreshing is True
    assert len(requested) == 1


def test_map_service_reuses_filtered_snapshot_at_any_phone_location_and_checks_distance_once():
    query = MapQuery(market='Seattle', product_type='Bath', rep='Rep One')
    jobs = (
        MapJob('near', 'WO1', 'Near', 'Working', 47.02, -122.0, ''),
        MapJob('far', 'WO2', 'Far', 'Working', 47.10, -122.0, ''),
        MapJob('new', 'WO3', 'New', 'New', 47.01, -122.0, ''),
        MapJob('confirmed', 'WO4', 'Confirmed', 'Scheduled Confirmed', 47.03, -122.0, ''),
    )
    requested = []

    class Repository:
        def snapshot(self):
            return {
                'query': query,
                'jobs': jobs,
                'captured_at': 100.0,
                'diagnostics': MapSourceDiagnostics(
                    appointment_rows=6,
                    grouped_jobs=4,
                    jobs_with_location=4,
                    jobs_missing_location=0,
                ),
            }

        def refresh_state(self):
            return {}

        def request_refresh(self, *args):
            requested.append(args)
            raise AssertionError('fresh matching filter snapshot must not refresh for phone movement')

    service = JobMapService(Repository(), object(), lambda records: b'pdf', clock=lambda: 120.0)
    first = service.view(47.0, -122.0, market='Seattle', product_type='Bath', rep='Rep One')
    second = service.view(47.09, -122.0, market='Seattle', product_type='Bath', rep='Rep One')

    assert [job.source_id for job in first.jobs] == ['confirmed', 'near']
    assert 'far' in [job.source_id for job in second.jobs]
    assert first.diagnostics.appointment_rows == 6
    assert first.diagnostics.grouped_jobs == 4
    assert first.diagnostics.snapshot_jobs == 4
    assert first.diagnostics.excluded_status == 1
    assert first.diagnostics.outside_radius == 1
    assert first.diagnostics.visible_jobs == 2
    assert [item.outcome for item in first.diagnostics.candidates] == [
        'excluded-status', 'visible', 'visible', 'outside-radius'
    ]
    assert requested == []


def test_map_service_filter_change_queues_new_background_refresh():
    requested = []
    old_query = MapQuery(market='Seattle', product_type='Bath', rep='Rep One')

    class Repository:
        def snapshot(self):
            return {'query': old_query, 'jobs': (), 'captured_at': 199.0}

        def refresh_state(self):
            return {}

        def request_refresh(self, ident, query, now):
            requested.append((ident, query, now))
            return {'id': ident, 'status': 'queued', 'query': query, 'updated': now}

    view = JobMapService(Repository(), object(), lambda records: b'pdf', clock=lambda: 200.0).view(
        47.0, -122.0, market='Seattle', product_type='Windows', rep='Rep One'
    )
    assert view.jobs == ()
    assert view.refreshing is True
    assert requested[0][1] == MapQuery(
        market='Seattle', product_type='Windows', rep='Rep One',
    )


def test_map_refresh_service_publishes_filters_then_filtered_job_snapshot(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    query = MapQuery(market='Seattle', product_type='Bath', rep='Rep One')
    repository.request_filter_refresh('filters-1', 90.0)
    repository.request_refresh('jobs-1', query, 100.0)
    filters = MapFilters(markets=('Seattle',), product_types=('Bath',), reps=('Rep One',))
    job = MapJob('inside', 'WO1', 'Inside', 'Working', 47.02, -122.0, '')

    class Source:
        def map_filters(self):
            return filters

        def map_jobs(self, requested):
            assert requested == query
            return MapSourceSnapshot(
                jobs=(job,),
                diagnostics=MapSourceDiagnostics(
                    appointment_rows=2,
                    grouped_jobs=1,
                    jobs_with_location=1,
                    jobs_missing_location=0,
                ),
            )

    refresh = JobMapRefreshService(repository, Source(), clock=lambda: 150.0)
    assert refresh.requested_due() is True
    state = refresh.run_requested()

    assert repository.filter_snapshot()['filters'] == filters
    assert repository.filter_refresh_state()['status'] == 'complete'
    assert state['status'] == 'complete'
    assert state['count'] == 1
    saved = repository.snapshot()
    assert saved['jobs'] == (job,)
    assert saved['diagnostics'].appointment_rows == 2
    assert saved['diagnostics'].jobs_with_location == 1


def test_map_refresh_failure_is_durable_and_web_can_return_without_waiting(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    query = MapQuery(market='Seattle', product_type='Bath', rep='Rep One')
    repository.request_refresh('refresh-1', query, 100.0)

    class Source:
        def map_jobs(self, requested):
            raise RuntimeError('source down')

    refresh = JobMapRefreshService(repository, Source(), clock=lambda: 150.0)
    state = refresh.run_requested()
    assert state['status'] == 'failed'
    assert state['error'] == 'source down'

    view = JobMapService(repository, object(), lambda records: b'pdf', clock=lambda: 151.0).view(
        47.0, -122.0, market='Seattle', product_type='Bath', rep='Rep One'
    )
    assert view.refreshing is False
    assert view.jobs == ()
    assert view.error == 'source down'


def test_map_service_rejects_invalid_location_before_repository_access():
    class Repository:
        def snapshot(self):
            raise AssertionError('repository must not run without a valid location')

    service = JobMapService(Repository(), object(), lambda records: b'pdf')
    with pytest.raises(ValueError, match='valid current location'):
        service.view(200, -122)


def test_map_service_opens_one_current_mod_sheet():
    record = SimpleNamespace(work_order_number='02257311')

    class Source:
        def work_orders(self, numbers):
            assert numbers == ('02257311',)
            return (record,)

    seen = []
    service = JobMapService(object(), Source(), lambda records: seen.append(tuple(records)) or b'%PDF-map')
    assert service.mod_sheet('02257311') == b'%PDF-map'
    assert seen == [(record,)]


def test_map_http_page_redirects_to_existing_secure_proxy_without_touching_map_service():
    flask = pytest.importorskip('flask')
    from printer_app.job_map.web import blueprint

    class Service:
        def view(self, *args, **kwargs):
            raise AssertionError('redirect must happen before reading map data')

    class HttpsAccess:
        def status(self):
            return {
                'configured': True,
                'addresses': ['100.87.89.92', '192.168.1.20'],
                'dns': ['stats-pi.local'],
            }

    app = flask.Flask(__name__)
    app.secret_key = 'test'
    app.register_blueprint(blueprint(Service(), https_access=HttpsAccess()))
    response = app.test_client().get('/map', base_url='http://100.87.89.92:5055')

    assert response.status_code == 302
    assert response.headers['Location'] == 'https://100.87.89.92/map'


def test_map_secure_page_does_not_redirect_again():
    flask = pytest.importorskip('flask')
    from printer_app.job_map.web import _secure_page_url

    class HttpsAccess:
        def status(self):
            raise AssertionError('secure requests must not re-check or redirect')

    app = flask.Flask(__name__)
    with app.test_request_context('/map', base_url='https://100.87.89.92'):
        assert _secure_page_url(HttpsAccess()) == ''


def test_map_web_returns_filters_first_then_filtered_local_snapshot_and_mod_pdf():
    flask = pytest.importorskip('flask')
    from printer_app.job_map.web import blueprint

    templates = Path(__file__).resolve().parents[1] / 'templates'
    static = Path(__file__).resolve().parents[1] / 'static'

    class Service:
        def filters(self, *, force_refresh=False):
            assert force_refresh is False
            return MapFilterView(
                filters=MapFilters(
                    markets=('Seattle', 'Tacoma'),
                    product_types=('Bath', 'Windows'),
                    reps=('Rep One', 'Rep Two'),
                ),
                captured_at=50.0,
            )

        def view(self, latitude, longitude, *, market='', product_type='', rep='', force_refresh=False):
            assert (latitude, longitude) == (47.25, -122.45)
            assert (market, rep, product_type) == ('Seattle', 'Rep One', 'Bath')
            assert force_refresh is False
            return MapView(
                jobs=(MapJob(
                    'wo', '02257311', 'Customer', 'Working', 47.25, -122.45,
                    'https://example.my.salesforce.com/lightning/r/Lead/00Q/view',
                    market='Seattle', product_type='Bath', assigned_reps=('Rep One',),
                ),),
                captured_at=123.0,
                diagnostics=MapDiagnostics(
                    appointment_rows=4,
                    grouped_jobs=3,
                    jobs_with_location=2,
                    jobs_missing_location=1,
                    snapshot_jobs=2,
                    excluded_status=0,
                    outside_radius=1,
                    visible_jobs=1,
                    candidates=(MapCandidateDiagnostic(
                        work_order_number='02257311',
                        lead_name='Customer',
                        lead_status='Working',
                        distance_miles=0.1254,
                        latitude=47.25,
                        longitude=-122.45,
                        outcome='visible',
                    ),),
                ),
            )

        def mod_sheet(self, number):
            assert number == '02257311'
            return b'%PDF-map'

    app = flask.Flask(__name__, template_folder=str(templates), static_folder=str(static))
    app.secret_key = 'test'
    app.register_blueprint(blueprint(Service()))
    client = app.test_client()

    filter_payload = client.get('/map/api/filters').get_json()
    assert filter_payload['ok'] is True
    assert filter_payload['filters']['markets'] == ['Seattle', 'Tacoma']
    assert filter_payload['filters']['reps'] == ['Rep One', 'Rep Two']
    assert filter_payload['filters']['product_types'] == ['Bath', 'Windows']

    missing = client.get('/map/api/jobs')
    assert missing.status_code == 400

    payload = client.get(
        '/map/api/jobs?lat=47.25&lon=-122.45&market=Seattle&rep=Rep%20One&product=Bath'
    ).get_json()
    assert payload['ok'] is True
    assert payload['radius_miles'] == 5.0
    assert payload['jobs'][0]['work_order_number'] == '02257311'
    assert payload['diagnostics']['appointment_rows'] == 4
    assert payload['diagnostics']['grouped_jobs'] == 3
    assert payload['diagnostics']['jobs_missing_location'] == 1
    assert payload['diagnostics']['outside_radius'] == 1
    assert payload['diagnostics']['visible_jobs'] == 1
    assert payload['diagnostics']['candidates'][0] == {
        'work_order_number': '02257311',
        'lead_name': 'Customer',
        'lead_status': 'Working',
        'distance_miles': 0.125,
        'latitude': 47.25,
        'longitude': -122.45,
        'outcome': 'visible',
    }

    pdf = client.get('/map/mod-sheet?work_order=02257311')
    assert pdf.status_code == 200 and pdf.mimetype == 'application/pdf'
    assert pdf.data == b'%PDF-map'


def test_job_map_architecture_has_one_authoritative_location_and_one_distance_check():
    root = Path(__file__).resolve().parents[1]
    for path in (root / 'job_map').glob('*.py'):
        assert 'salesforce' not in path.read_text().casefold()

    contract = (root / 'job_map/contract.py').read_text()
    query_block = contract.split('class MapQuery:', 1)[1].split('class MapJob:', 1)[0]
    assert 'latitude' not in query_block
    assert 'longitude' not in query_block
    assert 'radius_miles' not in query_block

    service = (root / 'job_map/service.py').read_text()
    local_service = service.split('class JobMapRefreshService', 1)[0]
    assert '.map_jobs(' not in local_service
    assert 'SNAPSHOT_CENTER_TOLERANCE_MILES' not in service
    assert service.count('_distance_miles(') == 2
    assert '_evaluate_jobs' in service
    assert 'MapCandidateDiagnostic' in service
    assert 'self.repository.snapshot()' in local_service

    repository = (root / 'job_map/repository.py').read_text()
    assert "SNAPSHOT_KEY = 'job_map_snapshot_v3'" in repository
    assert "REFRESH_KEY = 'job_map_refresh_v3'" in repository
    assert "'latitude':" not in repository.split('def _query_dict', 1)[1].split('def _query_from', 1)[0]

    worker = (root / 'worker.py').read_text()
    assert 'JobMapRefreshService' in worker
    assert 'background.submit(map_refresh.run_requested)' in worker

    adapter = (root / 'salesforce_sandbox/adapter.py').read_text()
    map_block = adapter.split('    def map_jobs(self, query: MapQuery):', 1)[1].split(
        '    def explorer_objects', 1
    )[0]
    assert "Market__c = " in map_block
    assert "Product_Interest__c INCLUDES" in map_block
    assert "Assigned_Service_Resource__r.Name = " in map_block
    assert "'Latitude', 'Longitude'," in map_block
    assert 'appointment_rows += 1' in map_block
    assert 'jobs_missing_location=missing_location' in map_block
    assert 'Latitude >=' not in map_block
    assert 'Longitude >=' not in map_block
    assert '_map_locations' not in adapter
    assert 'FSSK__FSK_Work_Order__r.Latitude' not in map_block
    assert 'FSSK__FSK_Work_Order__r.Longitude' not in map_block

    template = (root / 'templates/job_map.html').read_text()
    assert template.index('id="jobMapMarket"') < template.index('id="jobMapRep"')
    assert template.index('id="jobMapRep"') < template.index('id="jobMapProduct"')
    assert template.index('id="jobMapProduct"') < template.index('id="jobMapLocate"')

    runtime = (root / 'static/job_map/map.js').read_text()
    assert 'readFilters(Date.now() + 60000);' in runtime
    assert 'loadNearby(false)' not in runtime
    assert 'navigator.geolocation.getCurrentPosition' in runtime
    assert "url.searchParams.set('market'" in runtime
    assert "url.searchParams.set('rep'" in runtime
    assert "url.searchParams.set('product'" in runtime
    assert "url.searchParams.set('refresh', '1')" in runtime
    assert "document.getElementById('jobMapDiagnose')" in runtime
    assert 'Salesforce appointment rows:' in runtime
    assert 'Jobs missing ServiceAppointment location:' in runtime
    assert 'Nearest candidates (' in runtime
    assert "action('MOD Sheet'" in runtime
    assert "action('Open in Salesforce'" in runtime

    app = (root / 'app.py').read_text()
    assert 'JobMapRepository(db)' in app
    assert 'job_map_blueprint(job_map, https_access=gallery_https)' in app
