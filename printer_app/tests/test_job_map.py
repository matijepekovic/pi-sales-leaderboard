"""Job map source, workflow, web, and architecture regressions."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from printer_app.job_map.contract import MapJob
from printer_app.job_map.service import JobMapService
from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter


WORK_ORDER_OBJECT = 'Field_Work_Order__c'
LEAD_FIELD = 'Linked_Lead__c'
WORK_ONE = 'a01000000000000001'
LEAD_ONE = '00Q000000000001AAA'


def _result(payload):
    return SimpleNamespace(stdout=json.dumps(payload), stderr='', returncode=0)


def _field(name, kind='string', **extra):
    return {'name': name, 'type': kind, 'filterable': True, 'sortable': True, **extra}


def _metadata(name):
    fields = [_field('Id', 'id')]
    if name == 'ServiceAppointment':
        fields.append(_field(
            'FSSK__FSK_Work_Order__c', 'reference', referenceTo=[WORK_ORDER_OBJECT]
        ))
    elif name == WORK_ORDER_OBJECT:
        fields.extend([
            _field('WorkOrderNumber'),
            _field(
                LEAD_FIELD, 'reference', referenceTo=['Lead'], relationshipName='Lead__r'
            ),
        ])
    else:
        raise AssertionError(name)
    return {'name': name, 'queryable': True, 'fields': fields}


def _work_order(*, ident=WORK_ONE, number='02257311', lead=LEAD_ONE,
                name='Customer One', status='Working', lat='47.25', lon='-122.45'):
    return {
        'Id': ident,
        'WorkOrderNumber': number,
        'Lead__r': {
            'Id': lead,
            'Name': name,
            'Status': status,
            'Latitude': lat,
            'Longitude': lon,
        },
    }


def test_map_source_queries_work_orders_directly_not_appointment_history():
    calls = []
    rows = [
        _work_order(),
        _work_order(
            ident='a01000000000000002', number='02257312',
            lead='00Q000000000002AAA', name='No Coordinates', lat='', lon='',
        ),
    ]

    def runner(command, **kwargs):
        calls.append(command)
        if command[1:3] == ['org', 'display']:
            return _result({'status': 0, 'result': {
                'username': 'rep@example.test',
                'alias': 'work',
                'instanceUrl': 'https://example.my.salesforce.com',
                'id': '00D000000000123',
                'connectedStatus': 'Connected',
            }})
        if command[1:3] == ['sobject', 'describe']:
            name = command[command.index('--sobject') + 1]
            return _result({'status': 0, 'result': _metadata(name)})
        query = command[command.index('--query') + 1]
        assert f' FROM {WORK_ORDER_OBJECT} ' in query
        return _result({'status': 0, 'result': {
            'records': rows,
            'done': True,
            'totalSize': len(rows),
        }})

    jobs = SalesforceCliAdapter(runner=runner, executable='/fake/sf').map_jobs()

    assert jobs == (
        MapJob(
            source_id=WORK_ONE,
            work_order_number='02257311',
            lead_name='Customer One',
            lead_status='Working',
            latitude=47.25,
            longitude=-122.45,
            source_record_url='https://example.my.salesforce.com/lightning/r/Lead/'
                              + LEAD_ONE + '/view',
        ),
    )
    data_queries = [
        call[call.index('--query') + 1]
        for call in calls if call[1:3] == ['data', 'query']
    ]
    assert len(data_queries) == 1
    query = data_queries[0]
    assert 'FROM ServiceAppointment' not in query
    assert 'SchedStartTime' not in query
    assert 'CreatedDate' not in query
    assert 'Lead__r.Latitude' in query and 'Lead__r.Longitude' in query
    assert "WorkType.Name LIKE '%Sales%'" in query
    assert f'{LEAD_FIELD} != null' in query


def test_map_service_excludes_only_requested_lead_statuses():
    jobs = tuple(
        MapJob(str(i), f'WO{i}', f'Lead {i}', status, 47 + i / 100, -122, f'https://example/{i}')
        for i, status in enumerate(
            ('New', 'Scheduled', 'Do Not Call', 'Scheduled Confirmed', 'Working')
        )
    )

    class Source:
        def map_jobs(self):
            return jobs

    visible = JobMapService(Source(), lambda records: b'pdf').jobs()
    assert [job.lead_status for job in visible] == ['Scheduled Confirmed', 'Working']


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


def test_map_web_returns_jobs_and_mod_pdf():
    flask = pytest.importorskip('flask')
    from printer_app.job_map.web import blueprint

    templates = Path(__file__).resolve().parents[1] / 'templates'
    static = Path(__file__).resolve().parents[1] / 'static'

    class Service:
        def jobs(self):
            return (MapJob(
                'wo', '02257311', 'Customer', 'Working', 47.25, -122.45,
                'https://example.my.salesforce.com/lightning/r/Lead/00Q/view',
            ),)

        def mod_sheet(self, number):
            assert number == '02257311'
            return b'%PDF-map'

    app = flask.Flask(__name__, template_folder=str(templates), static_folder=str(static))
    app.secret_key = 'test'
    app.register_blueprint(blueprint(Service()))
    client = app.test_client()

    payload = client.get('/map/api/jobs').get_json()
    assert payload['ok'] is True
    assert payload['jobs'][0]['work_order_number'] == '02257311'
    pdf = client.get('/map/mod-sheet?work_order=02257311')
    assert pdf.status_code == 200 and pdf.mimetype == 'application/pdf'
    assert pdf.data == b'%PDF-map'


def test_job_map_stays_vendor_neutral_and_uses_openfreemap():
    root = Path(__file__).resolve().parents[1]
    for path in (root / 'job_map').glob('*.py'):
        assert 'salesforce' not in path.read_text().casefold()

    template = (root / 'templates/job_map.html').read_text()
    assert 'maplibre-gl@5.22.0' in template
    assert 'jobMapMarket' not in template
    assert 'jobMapRep' not in template

    runtime = (root / 'static/job_map/map.js').read_text()
    assert "style: 'https://tiles.openfreemap.org/styles/liberty'" in runtime
    assert 'tile.openstreetmap.org' not in runtime
    assert "action('MOD Sheet'" in runtime
    assert "action('Open in Salesforce'" in runtime

    app = (root / 'app.py').read_text()
    assert 'https://tiles.openfreemap.org' in app
    assert 'https://tile.openstreetmap.org' not in app
    assert "worker-src 'self' blob:" in app
