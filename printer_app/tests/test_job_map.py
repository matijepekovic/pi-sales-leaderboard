"""Job map source, filters, workflow, web, and architecture regressions."""
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
WORK_TWO = 'a01000000000000002'
LEAD_ONE = '00Q000000000001AAA'
LEAD_TWO = '00Q000000000002AAA'


def _result(payload):
    return SimpleNamespace(stdout=json.dumps(payload), stderr='', returncode=0)


def _field(name, kind='string', **extra):
    return {'name': name, 'type': kind, 'filterable': True, 'sortable': True, **extra}


def _metadata(name):
    fields = [_field('Id', 'id')]
    if name == 'ServiceAppointment':
        fields.append(_field('FSSK__FSK_Work_Order__c', 'reference', referenceTo=[WORK_ORDER_OBJECT]))
    elif name == WORK_ORDER_OBJECT:
        fields.extend([
            _field('WorkOrderNumber'),
            _field(LEAD_FIELD, 'reference', referenceTo=['Lead'], relationshipName='Lead__r'),
        ])
    else:
        raise AssertionError(name)
    return {'name': name, 'queryable': True, 'fields': fields}


def _work_order(ident, number, lead_id, name, status, market, lat, lon):
    return {
        'Id': ident,
        'WorkOrderNumber': number,
        LEAD_FIELD: lead_id,
        'Lead__r': {
            'Id': lead_id,
            'Name': name,
            'Status': status,
            'Market__c': market,
            'Latitude': lat,
            'Longitude': lon,
        },
    }


def _assignment(ident, work_order, resource, status='Scheduled'):
    return {
        'Id': ident,
        'StatusCategory': status,
        'FSSK__FSK_Work_Order__c': work_order,
        'FSSK__FSK_Assigned_Service_Resource__r': {'Name': resource} if resource else None,
    }


class MapRunner:
    def __init__(self):
        self.calls = []
        self.work_orders = [
            _work_order(WORK_ONE, '02257311', LEAD_ONE, 'Customer One', 'Working',
                        'Olympia', '47.25', '-122.45'),
            _work_order(WORK_TWO, '02257312', LEAD_TWO, 'Customer Two', 'Scheduled Confirmed',
                        'Seattle', '47.60', '-122.33'),
        ]
        self.assignments = [
            _assignment('08p000000000001AAA', WORK_ONE, 'Alex'),
            _assignment('08p000000000002AAA', WORK_ONE, 'Sam'),
            _assignment('08p000000000003AAA', WORK_ONE, 'Former Rep', 'Canceled'),
            _assignment('08p000000000004AAA', WORK_TWO, 'Jordan'),
        ]

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[1:3] == ['org', 'display']:
            return _result({'status': 0, 'result': {
                'username': 'rep@example.test',
                'alias': 'work',
                'instanceUrl': 'https://example.my.salesforce.com',
                'id': '00D000000000123',
                'connectedStatus': 'Connected',
            }})
        if command[1:3] == ['sobject', 'describe']:
            return _result({'status': 0, 'result': _metadata(command[command.index('--sobject') + 1])})

        query = command[command.index('--query') + 1]
        if f' FROM {WORK_ORDER_OBJECT} ' in query:
            rows = [] if ' AND Id > ' in query else self.work_orders
        elif ' FROM ServiceAppointment ' in query:
            assert 'FSSK__FSK_Work_Order__c IN (' in query
            rows = [] if ' AND Id > ' in query else self.assignments
        else:
            raise AssertionError(query)
        return _result({'status': 0, 'result': {
            'records': rows,
            'done': True,
            'totalSize': len(rows),
        }})

    @property
    def queries(self):
        return [call[call.index('--query') + 1] for call in self.calls if '--query' in call]


def test_map_source_queries_work_orders_directly_and_only_targeted_rep_assignments():
    runner = MapRunner()
    jobs = SalesforceCliAdapter(runner=runner, executable='/fake/sf').map_jobs()

    assert jobs == (
        MapJob(
            source_id=WORK_ONE,
            work_order_number='02257311',
            lead_name='Customer One',
            lead_status='Working',
            market_segment='Olympia',
            assigned_service_resources=('Alex', 'Sam'),
            latitude=47.25,
            longitude=-122.45,
            source_record_url='https://example.my.salesforce.com/lightning/r/Lead/'
                              + LEAD_ONE + '/view',
        ),
        MapJob(
            source_id=WORK_TWO,
            work_order_number='02257312',
            lead_name='Customer Two',
            lead_status='Scheduled Confirmed',
            market_segment='Seattle',
            assigned_service_resources=('Jordan',),
            latitude=47.60,
            longitude=-122.33,
            source_record_url='https://example.my.salesforce.com/lightning/r/Lead/'
                              + LEAD_TWO + '/view',
        ),
    )

    work_query = next(query for query in runner.queries if f' FROM {WORK_ORDER_OBJECT} ' in query)
    assert 'Lead__r.Latitude' in work_query and 'Lead__r.Longitude' in work_query
    assert 'Lead__r.Market__c' in work_query
    assert "WorkType.Name LIKE '%Sales%'" in work_query
    assert "Lead__r.Status NOT IN ('New', 'Scheduled', 'Do Not Call')" in work_query

    assignment_query = next(query for query in runner.queries if ' FROM ServiceAppointment ' in query)
    assert 'FSSK__FSK_Work_Order__c IN (' in assignment_query
    assert 'Lead__r.Latitude' not in assignment_query
    assert 'WorkOrderNumber' not in assignment_query
    assert 'Former Rep' not in jobs[0].assigned_service_resources


def test_map_source_skips_work_orders_without_coordinates():
    runner = MapRunner()
    runner.work_orders.append(
        _work_order('a01000000000000003', '02257313', '00Q000000000003AAA',
                    'No Coordinates', 'Working', 'Olympia', '', '')
    )
    jobs = SalesforceCliAdapter(runner=runner, executable='/fake/sf').map_jobs()
    assert [job.work_order_number for job in jobs] == ['02257311', '02257312']


def test_map_service_excludes_only_requested_lead_statuses():
    jobs = tuple(
        MapJob(
            source_id=str(i), work_order_number=f'WO{i}', lead_name=f'Lead {i}',
            lead_status=status, market_segment='Olympia',
            assigned_service_resources=('Alex',), latitude=47 + i / 100, longitude=-122,
            source_record_url=f'https://example/{i}',
        )
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


def test_map_web_returns_filter_tags_and_mod_pdf():
    flask = pytest.importorskip('flask')
    from printer_app.job_map.web import blueprint

    templates = Path(__file__).resolve().parents[1] / 'templates'
    static = Path(__file__).resolve().parents[1] / 'static'

    class Service:
        def jobs(self):
            return (MapJob(
                source_id='wo', work_order_number='02257311', lead_name='Customer',
                lead_status='Working', market_segment='Olympia',
                assigned_service_resources=('Alex', 'Sam'), latitude=47.25, longitude=-122.45,
                source_record_url='https://example.my.salesforce.com/lightning/r/Lead/00Q/view',
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
    assert payload['jobs'][0]['market_segment'] == 'Olympia'
    assert payload['jobs'][0]['assigned_service_resources'] == ['Alex', 'Sam']
    pdf = client.get('/map/mod-sheet?work_order=02257311')
    assert pdf.status_code == 200 and pdf.mimetype == 'application/pdf'
    assert pdf.data == b'%PDF-map'


def test_job_map_stays_vendor_neutral_and_uses_openfreemap_with_client_filters():
    root = Path(__file__).resolve().parents[1]
    for path in (root / 'job_map').glob('*.py'):
        assert 'salesforce' not in path.read_text().casefold()

    template = (root / 'templates/job_map.html').read_text()
    assert 'maplibre-gl@5' in template
    assert 'id="jobMapMarket"' in template
    assert 'id="jobMapRep"' in template

    runtime = (root / 'static/job_map/map.js').read_text()
    assert "style: 'https://tiles.openfreemap.org/styles/liberty'" in runtime
    assert 'tile.openstreetmap.org' not in runtime
    assert 'market_segment' in runtime
    assert 'assigned_service_resources' in runtime
    assert "action('MOD Sheet'" in runtime
    assert "action('Open in Salesforce'" in runtime

    app = (root / 'app.py').read_text()
    assert 'https://tiles.openfreemap.org' in app
    assert 'https://tile.openstreetmap.org' not in app
