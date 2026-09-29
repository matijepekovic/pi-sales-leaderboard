"""Job map source, local snapshot, workflow, web, and architecture regressions."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from printer_app.db import Database
from printer_app.job_map.contract import MapJob, MapQuery, MapView
from printer_app.job_map.repository import JobMapRepository
from printer_app.job_map.service import JobMapRefreshService, JobMapService, MAX_RADIUS_MILES
from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter


def _result(payload):
    return SimpleNamespace(stdout=json.dumps(payload), stderr='', returncode=0)


def _row(ident, *, work='0WO000000000001AAA', number='02257311', lead='00Q000000000001AAA',
         name='Customer One', status='Working', lat='47.25', lon='-122.45',
         market='Seattle', product='Bath', rep='Rep One',
         scheduled='2026-09-24T17:00:00.000+0000', created='2026-09-24T16:00:00.000+0000',
         appointment_status='Scheduled'):
    return {
        'Id': ident,
        'StatusCategory': appointment_status,
        'SchedStartTime': scheduled,
        'CreatedDate': created,
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
                'Latitude': lat,
                'Longitude': lon,
            },
        },
    }


def test_map_source_resolves_nearby_leads_before_querying_appointments():
    calls = []
    appointment_rows = [
        _row('08p000000000001AAA', scheduled='2026-09-23T17:00:00.000+0000'),
        _row('08p000000000002AAA', name='Canceled duplicate', scheduled='2026-09-25T17:00:00.000+0000',
             appointment_status='Canceled'),
    ]
    nearby_lead = {
        'Id': '00Q000000000001AAA',
        'Name': 'Customer One',
        'Status': 'Working',
        'Market__c': 'Seattle',
        'Latitude': '47.25',
        'Longitude': '-122.45',
    }

    def runner(command, **kwargs):
        calls.append(command)
        if command[1:3] == ['org', 'display']:
            return _result({'status': 0, 'result': {
                'username': 'rep@example.test', 'alias': 'work',
                'instanceUrl': 'https://example.my.salesforce.com',
                'id': '00D000000000123', 'connectedStatus': 'Connected',
            }})
        query = command[command.index('--query') + 1]
        if ' FROM Lead WHERE ' in query:
            page = [] if ' AND Id > ' in query else [nearby_lead]
        else:
            assert ' FROM ServiceAppointment WHERE ' in query
            page = [] if ' AND Id > ' in query else appointment_rows
        return _result({'status': 0, 'result': {'records': page}})

    adapter = SalesforceCliAdapter(runner=runner, executable='/fake/sf')
    jobs = adapter.map_jobs(MapQuery(47.25, -122.45, 5.0))

    assert jobs == (MapJob(
        source_id='0WO000000000001AAA', work_order_number='02257311',
        lead_name='Customer One', lead_status='Working', latitude=47.25, longitude=-122.45,
        source_record_url='https://example.my.salesforce.com/lightning/r/Lead/00Q000000000001AAA/view',
        market='Seattle', product_type='Bath', assigned_reps=('Rep One',),
    ),)

    queries = [
        call[call.index('--query') + 1]
        for call in calls if call[1:3] == ['data', 'query']
    ]
    lead_query = next(query for query in queries if ' FROM Lead WHERE ' in query and ' AND Id > ' not in query)
    appointment_query = next(
        query for query in queries
        if ' FROM ServiceAppointment WHERE ' in query and ' AND Id > ' not in query
    )
    assert 'Latitude >=' in lead_query and 'Latitude <=' in lead_query
    assert 'Longitude >=' in lead_query and 'Longitude <=' in lead_query
    assert 'Market__c' in lead_query
    assert "FSSK__FSK_Work_Order__r.Lead__r.Id IN ('00Q000000000001AAA')" in appointment_query
    assert 'Lead__r.Latitude' not in appointment_query
    assert 'Lead__r.Longitude' not in appointment_query
    assert 'Product_Interest__c' in appointment_query
    assert 'Assigned_Service_Resource__r.Name' in appointment_query
    assert "WorkType.Name LIKE '%Sales%'" in appointment_query


def test_map_source_does_not_query_appointments_when_no_nearby_leads_exist():
    queries = []

    def runner(command, **kwargs):
        query = command[command.index('--query') + 1]
        queries.append(query)
        assert ' FROM Lead WHERE ' in query
        return _result({'status': 0, 'result': {'records': []}})

    adapter = SalesforceCliAdapter(runner=runner, executable='/fake/sf')
    assert adapter.map_jobs(MapQuery(47.25, -122.45, 5.0)) == ()
    assert len(queries) == 1


def test_map_repository_round_trips_normalized_snapshot_and_refresh_state(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    query = MapQuery(47.25, -122.45, 5.0)
    job = MapJob(
        'wo', '02257311', 'Customer', 'Working', 47.25, -122.45,
        'https://example.test/lead', market='Seattle', product_type='Bath',
        assigned_reps=('Rep One', 'Rep Two'),
    )

    repository.replace_snapshot(query, (job,), 100.0)
    snapshot = repository.snapshot()
    assert snapshot == {'query': query, 'jobs': (job,), 'captured_at': 100.0}

    state = repository.request_refresh('refresh-1', query, 101.0)
    assert state['status'] == 'queued'
    assert state['query'] == query
    repository.save_refresh_state(dict(state, status='running', updated=102.0))
    assert repository.refresh_state()['status'] == 'running'


def test_map_service_returns_fresh_local_snapshot_without_calling_external_source():
    query = MapQuery(47.0, -122.0, MAX_RADIUS_MILES)
    jobs = (
        MapJob('inside', 'WO1', 'Inside', 'Working', 47.02, -122.0, ''),
        MapJob('far', 'WO2', 'Far', 'Working', 47.10, -122.0, ''),
        MapJob('new', 'WO3', 'New', 'New', 47.01, -122.0, ''),
        MapJob('confirmed', 'WO4', 'Confirmed', 'Scheduled Confirmed', 47.03, -122.0, ''),
    )

    class Repository:
        def snapshot(self):
            return {'query': query, 'jobs': jobs, 'captured_at': 100.0}

        def refresh_state(self):
            return {}

        def request_refresh(self, *args):
            raise AssertionError('fresh local snapshot must not queue a source refresh')

    class ModSource:
        def work_orders(self, numbers):
            raise AssertionError('map view must not call MOD source')

    view = JobMapService(Repository(), ModSource(), lambda records: b'pdf', clock=lambda: 120.0).view(
        47.0, -122.0
    )
    assert [job.source_id for job in view.jobs] == ['confirmed', 'inside']
    assert view.refreshing is False
    assert view.stale is False


def test_map_service_queues_background_refresh_instead_of_calling_source():
    requested = []

    class Repository:
        def snapshot(self):
            return None

        def refresh_state(self):
            return {}

        def request_refresh(self, ident, query, now):
            requested.append((ident, query, now))
            return {'id': ident, 'status': 'queued', 'query': query, 'updated': now}

    class ModSource:
        def work_orders(self, numbers):
            raise AssertionError('map view must not call source')

    view = JobMapService(Repository(), ModSource(), lambda records: b'pdf', clock=lambda: 200.0).view(
        47.0, -122.0
    )
    assert view.jobs == ()
    assert view.refreshing is True
    assert len(requested) == 1
    assert requested[0][1] == MapQuery(47.0, -122.0, MAX_RADIUS_MILES)


def test_map_refresh_service_publishes_complete_snapshot(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    query = MapQuery(47.0, -122.0, MAX_RADIUS_MILES)
    repository.request_refresh('refresh-1', query, 100.0)
    job = MapJob('inside', 'WO1', 'Inside', 'Working', 47.02, -122.0, '')

    class Source:
        def map_jobs(self, requested):
            assert requested == query
            return (job,)

    refresh = JobMapRefreshService(repository, Source(), clock=lambda: 150.0)
    assert refresh.requested_due() is True
    state = refresh.run_requested()
    assert state['status'] == 'complete'
    assert state['count'] == 1
    assert repository.snapshot()['jobs'] == (job,)
    assert repository.snapshot()['captured_at'] == 150.0


def test_map_refresh_failure_is_durable_and_web_can_return_without_waiting(tmp_path):
    repository = JobMapRepository(Database(tmp_path / 'printer.db'))
    query = MapQuery(47.0, -122.0, MAX_RADIUS_MILES)
    repository.request_refresh('refresh-1', query, 100.0)

    class Source:
        def map_jobs(self, requested):
            raise RuntimeError('source down')

    refresh = JobMapRefreshService(repository, Source(), clock=lambda: 150.0)
    state = refresh.run_requested()
    assert state['status'] == 'failed'
    assert state['error'] == 'source down'

    class ModSource:
        pass

    view = JobMapService(repository, ModSource(), lambda records: b'pdf', clock=lambda: 151.0).view(
        47.0, -122.0
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

    class Repository:
        pass

    class Source:
        def work_orders(self, numbers):
            assert numbers == ('02257311',)
            return (record,)

    seen = []
    service = JobMapService(Repository(), Source(), lambda records: seen.append(tuple(records)) or b'%PDF-map')
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


def test_map_web_returns_local_snapshot_state_and_mod_pdf():
    flask = pytest.importorskip('flask')
    from printer_app.job_map.web import blueprint

    templates = Path(__file__).resolve().parents[1] / 'templates'
    static = Path(__file__).resolve().parents[1] / 'static'

    class Service:
        def view(self, latitude, longitude, *, force_refresh=False):
            assert (latitude, longitude) == (47.25, -122.45)
            assert force_refresh is True
            return MapView(
                jobs=(MapJob(
                    'wo', '02257311', 'Customer', 'Working', 47.25, -122.45,
                    'https://example.my.salesforce.com/lightning/r/Lead/00Q/view',
                    market='Seattle', product_type='Bath', assigned_reps=('Rep One',),
                ),),
                refreshing=True,
                stale=True,
                captured_at=123.0,
            )

        def mod_sheet(self, number):
            assert number == '02257311'
            return b'%PDF-map'

    app = flask.Flask(__name__, template_folder=str(templates), static_folder=str(static))
    app.secret_key = 'test'
    app.register_blueprint(blueprint(Service()))
    client = app.test_client()

    missing = client.get('/map/api/jobs')
    assert missing.status_code == 400
    assert missing.get_json()['ok'] is False

    payload = client.get('/map/api/jobs?lat=47.25&lon=-122.45&refresh=1').get_json()
    assert payload['ok'] is True
    assert payload['radius_miles'] == 5.0
    assert payload['refreshing'] is True
    assert payload['stale'] is True
    assert payload['captured_at'] == 123.0
    assert payload['jobs'][0]['work_order_number'] == '02257311'
    assert payload['jobs'][0]['market'] == 'Seattle'
    assert payload['jobs'][0]['product_type'] == 'Bath'
    assert payload['jobs'][0]['assigned_reps'] == ['Rep One']

    pdf = client.get('/map/mod-sheet?work_order=02257311')
    assert pdf.status_code == 200 and pdf.mimetype == 'application/pdf'
    assert pdf.data == b'%PDF-map'


def test_job_map_architecture_keeps_web_reads_local_and_worker_owns_source_refresh():
    root = Path(__file__).resolve().parents[1]
    for path in (root / 'job_map').glob('*.py'):
        assert 'salesforce' not in path.read_text().casefold()

    service = (root / 'job_map/service.py').read_text()
    local_service = service.split('class JobMapRefreshService', 1)[0]
    assert '.map_jobs(' not in local_service
    assert 'self.repository.snapshot()' in local_service

    worker = (root / 'worker.py').read_text()
    assert 'JobMapRefreshService' in worker
    assert 'map_refresh.requested_due()' in worker
    assert 'background.submit(map_refresh.run_requested)' in worker

    template = (root / 'templates/job_map.html').read_text()
    assert 'leaflet@1.9.4' in template
    assert 'jobMapMarket' in template
    assert 'jobMapProduct' in template
    assert 'jobMapRep' in template
    assert 'data-radius-miles="{{ max_radius_miles }}"' in template

    runtime = (root / 'static/job_map/map.js').read_text()
    assert 'https://tile.openstreetmap.org/{z}/{x}/{y}.png' in runtime
    assert 'navigator.geolocation.getCurrentPosition' in runtime
    assert "url.searchParams.set('lat'" in runtime
    assert "url.searchParams.set('lon'" in runtime
    assert "url.searchParams.set('refresh', '1')" in runtime
    assert 'Preparing nearby map data' in runtime
    assert 'refreshing map data' in runtime
    assert 'controller.abort(), 10000' in runtime
    assert 'locationWatchdog' in runtime
    assert 'setView([39.5, -98.35], 4)' not in runtime
    assert "action('MOD Sheet'" in runtime
    assert "action('Open in Salesforce'" in runtime

    app = (root / 'app.py').read_text()
    assert 'JobMapRepository(db)' in app
    assert 'job_map_blueprint(job_map, https_access=gallery_https)' in app
