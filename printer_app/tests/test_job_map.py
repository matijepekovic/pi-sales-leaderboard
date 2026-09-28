"""Job map source, workflow, web, and architecture regressions."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from printer_app.job_map.contract import MapJob, MapQuery
from printer_app.job_map.service import JobMapService, MAX_RADIUS_MILES
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


def test_map_source_scopes_query_and_normalizes_filter_fields():
    calls = []
    rows = [
        _row('08p000000000001AAA', scheduled='2026-09-23T17:00:00.000+0000'),
        _row('08p000000000002AAA', name='Canceled duplicate', scheduled='2026-09-25T17:00:00.000+0000',
             appointment_status='Canceled'),
        _row('08p000000000003AAA', work='0WO000000000002AAA', number='02257312',
             lead='00Q000000000002AAA', name='No Coordinates', lat='', lon=''),
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
        assert 'FROM ServiceAppointment' in query
        page = [] if ' AND Id > ' in query else rows
        return _result({'status': 0, 'result': {'records': page}})

    adapter = SalesforceCliAdapter(runner=runner, executable='/fake/sf')
    jobs = adapter.map_jobs(MapQuery(47.25, -122.45, 5.0))

    assert len(jobs) == 1
    assert jobs[0] == MapJob(
        source_id='0WO000000000001AAA', work_order_number='02257311',
        lead_name='Customer One', lead_status='Working', latitude=47.25, longitude=-122.45,
        source_record_url='https://example.my.salesforce.com/lightning/r/Lead/00Q000000000001AAA/view',
        market='Seattle', product_type='Bath', assigned_reps=('Rep One',),
    )
    query = next(
        call[call.index('--query') + 1] for call in calls
        if call[1:3] == ['data', 'query'] and ' AND Id > ' not in call[call.index('--query') + 1]
    )
    assert 'Lead__r.Latitude >=' in query and 'Lead__r.Latitude <=' in query
    assert 'Lead__r.Longitude >=' in query and 'Lead__r.Longitude <=' in query
    assert 'Lead__r.Market__c' in query
    assert 'Product_Interest__c' in query
    assert 'Assigned_Service_Resource__r.Name' in query
    assert "WorkType.Name LIKE '%Sales%'" in query
    assert 'Do Not Call' not in query and 'Scheduled Confirmed' not in query


def test_map_service_enforces_five_mile_circle_and_lead_status_rules():
    requested = []
    jobs = (
        MapJob('inside', 'WO1', 'Inside', 'Working', 47.02, -122.0, ''),
        MapJob('far', 'WO2', 'Far', 'Working', 47.10, -122.0, ''),
        MapJob('new', 'WO3', 'New', 'New', 47.01, -122.0, ''),
        MapJob('scheduled', 'WO4', 'Scheduled', 'Scheduled', 47.01, -122.0, ''),
        MapJob('dnc', 'WO5', 'DNC', 'Do Not Call', 47.01, -122.0, ''),
        MapJob('confirmed', 'WO6', 'Confirmed', 'Scheduled Confirmed', 47.03, -122.0, ''),
    )

    class Source:
        def map_jobs(self, query):
            requested.append(query)
            return jobs

    visible = JobMapService(Source(), lambda records: b'pdf').jobs(47.0, -122.0)
    assert [job.source_id for job in visible] == ['confirmed', 'inside']
    assert requested == [MapQuery(47.0, -122.0, MAX_RADIUS_MILES)]


def test_map_service_rejects_invalid_location_before_querying_source():
    class Source:
        def map_jobs(self, query):
            raise AssertionError('source must not run without a valid bounded location')

    service = JobMapService(Source(), lambda records: b'pdf')
    with pytest.raises(ValueError, match='valid current location'):
        service.jobs(200, -122)


def test_map_service_opens_one_current_mod_sheet():
    record = SimpleNamespace(work_order_number='02257311')

    class Source:
        def work_orders(self, numbers):
            assert numbers == ('02257311',)
            return (record,)

    seen = []
    service = JobMapService(Source(), lambda records: seen.append(tuple(records)) or b'%PDF-map')
    assert service.mod_sheet('02257311') == b'%PDF-map'
    assert seen == [(record,)]


def test_map_web_requires_location_returns_filter_data_and_mod_pdf():
    flask = pytest.importorskip('flask')
    from printer_app.job_map.web import blueprint

    templates = Path(__file__).resolve().parents[1] / 'templates'
    static = Path(__file__).resolve().parents[1] / 'static'

    class Service:
        def jobs(self, latitude, longitude):
            assert (latitude, longitude) == (47.25, -122.45)
            return (MapJob(
                'wo', '02257311', 'Customer', 'Working', 47.25, -122.45,
                'https://example.my.salesforce.com/lightning/r/Lead/00Q/view',
                market='Seattle', product_type='Bath', assigned_reps=('Rep One',),
            ),)

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

    payload = client.get('/map/api/jobs?lat=47.25&lon=-122.45').get_json()
    assert payload['ok'] is True
    assert payload['radius_miles'] == 5.0
    assert payload['jobs'][0]['work_order_number'] == '02257311'
    assert payload['jobs'][0]['market'] == 'Seattle'
    assert payload['jobs'][0]['product_type'] == 'Bath'
    assert payload['jobs'][0]['assigned_reps'] == ['Rep One']

    pdf = client.get('/map/mod-sheet?work_order=02257311')
    assert pdf.status_code == 200 and pdf.mimetype == 'application/pdf'
    assert pdf.data == b'%PDF-map'


def test_job_map_python_stays_vendor_neutral_frontend_is_location_first_and_uses_free_osm_tiles():
    root = Path(__file__).resolve().parents[1]
    for path in (root / 'job_map').glob('*.py'):
        assert 'salesforce' not in path.read_text().casefold()

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
    assert 'configuredRadiusMiles' in runtime
    assert 'radiusMiles = 5' not in runtime
    assert 'setView([39.5, -98.35], 4)' not in runtime
    assert "action('MOD Sheet'" in runtime
    assert "action('Open in Salesforce'" in runtime

    app = (root / 'app.py').read_text()
    assert 'https://tile.openstreetmap.org' in app
    assert 'https://unpkg.com' in app
