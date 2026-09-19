"""Salesforce Sandbox is read-only, isolated, and produces normalized MOD records."""
import json
from pathlib import Path
from types import SimpleNamespace

from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter, SalesforceAdapterError
from printer_app.salesforce_sandbox.service import SalesforceSandboxService


def _result(value, returncode=0):
    return SimpleNamespace(stdout=json.dumps(value), stderr='', returncode=returncode)


def test_cli_adapter_recreates_mod_fields_and_assigned_resources_without_exposing_token():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[1:3] == ['org', 'list']:
            return _result({'status': 0, 'result': {'nonScratchOrgs': [{
                'username': 'rep@example.test',
                'alias': 'office',
                'connectedStatus': 'Connected',
                'isDefaultUsername': True,
            }]}})
        if command[1:3] == ['org', 'display']:
            return _result({'status': 0, 'result': {
                'username': 'rep@example.test',
                'alias': 'office',
                'instanceUrl': 'https://example.my.salesforce.com',
                'id': '00D000000000123',
                'accessToken': 'MUST_NOT_ESCAPE',
            }})
        query = command[command.index('--query') + 1]
        if 'FROM ServiceAppointment' in query:
            return _result({'status': 0, 'result': {'records': [{
                'Id': '08p000000000001AAA',
                'Local_Scheduled_Start_Time__c': '9/19/2026 10:30 AM',
                'SchedStartTime': '2026-09-19T17:30:00.000+0000',
                'FSSK__FSK_Work_Order__r': {
                    'WorkOrderNumber': '00012345',
                    'Street': '123 Main St',
                    'City': 'Lacey',
                    'State': 'WA',
                    'PostalCode': '98503',
                    'WorkType': {'Name': 'Sales Appointment'},
                    'Product_Interest__c': 'Windows',
                    'Lead__r': {
                        'Name': 'Jordan Example',
                        'Phone': '360-555-1212',
                        'Canvass_Set_By__r': {'Name': 'Canvasser'},
                        'Set_By__r': {'Name': 'Setter'},
                        'LeadSource': 'Canvass',
                        'Sub_Source__c': 'Door',
                        'Description': 'Customer description',
                    },
                },
            }]}})
        assert 'FROM AssignedResource' in query
        return _result({'status': 0, 'result': {'records': [
            {'ServiceAppointmentId': '08p000000000001AAA',
             'ServiceResource': {'Name': 'Sales Rep One'}},
            {'ServiceAppointmentId': '08p000000000001AAA',
             'ServiceResource': {'Name': 'Sales Rep Two'}},
        ]}})

    adapter = SalesforceCliAdapter(runner=runner, executable='/fake/sf')
    orgs = adapter.orgs()
    status = adapter.status('office')
    records = adapter.mod_sheets_today('office')

    assert orgs[0]['value'] == 'office'
    assert status.connected and status.username == 'rep@example.test'
    assert 'MUST_NOT_ESCAPE' not in repr(status)

    assert len(records) == 1
    record = records[0]
    assert record.work_order_number == '00012345'
    assert record.lead_name == 'Jordan Example'
    assert record.address == '123 Main St, Lacey, WA, 98503'
    assert record.assigned_service_resources == ('Sales Rep One', 'Sales Rep Two')
    assert record.product_interest == 'Windows'
    assert record.lead_description == 'Customer description'

    # The sandbox is read-only: every Salesforce invocation is org metadata or data query.
    assert all(command[1] in ('org', 'data') for command in calls)
    assert not any(word in ('create', 'update', 'delete', 'upsert') for command in calls for word in command)


def test_sandbox_failure_is_local_and_does_not_need_gallery_fallback():
    class BrokenAdapter:
        def orgs(self):
            return []
        def status(self, target_org=''):
            raise SalesforceAdapterError('CLI session unavailable')

    snapshot = SalesforceSandboxService(BrokenAdapter()).snapshot()
    assert not snapshot.status.connected
    assert snapshot.records == ()
    assert snapshot.error == 'CLI session unavailable'


def test_salesforce_sandbox_isolated_from_gallery_printing_and_ocr():
    root = Path(__file__).resolve().parents[1]
    for path in list((root / 'gallery').glob('*.py')) + [
        root / 'printer.py',
        root / 'worker.py',
        root / 'print_dispatch.py',
        root / 'print_queue_repository.py',
    ]:
        assert 'salesforce' not in path.read_text().lower(), str(path)

    adapter = (root / 'salesforce_sandbox/adapter.py').read_text()
    template = (root / 'templates/salesforce_sandbox.html').read_text()
    app = (root / 'app.py').read_text()
    assert 'FSSK__FSK_Work_Order__r' in adapter
    assert 'FSSK__FSK_Work_Order__r' not in app
    assert 'Assigned Service Resource' in template
    assert 'sf-owned' in template
    assert 'ocr' not in adapter.lower()
