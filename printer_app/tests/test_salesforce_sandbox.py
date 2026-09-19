"""Salesforce Sandbox reproduces the MOD portal without coupling Gallery/printing."""
import json
from pathlib import Path
from types import SimpleNamespace

from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter, SalesforceAdapterError
from printer_app.salesforce_sandbox.service import SalesforceSandboxService


def _result(value, returncode=0):
    return SimpleNamespace(stdout=json.dumps(value), stderr='', returncode=returncode)


def _describe_fields(sobject):
    if sobject == 'WorkOrder':
        return [
            {'label': 'Market Segment', 'name': 'Market_Segment__c',
             'picklistValues': [{'active': True, 'value': 'Retail'}]},
            {'label': 'Product Category', 'name': 'Product_Category__c',
             'picklistValues': [{'active': True, 'value': 'Windows'}]},
        ]
    if sobject == 'Lead':
        return [
            {'label': 'Source Type', 'name': 'Source_Type__c',
             'picklistValues': [{'active': True, 'value': 'Canvass'}]},
        ]
    return []


def _salesforce_runner(calls):
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
        if command[1:3] == ['sobject', 'describe']:
            sobject = command[command.index('--sobject') + 1]
            return _result({'status': 0, 'result': {'fields': _describe_fields(sobject)}})

        query = command[command.index('--query') + 1]
        if 'FROM AssignedResource' in query:
            return _result({'status': 0, 'result': {'records': [
                {'ServiceAppointmentId': '08p000000000001AAA',
                 'ServiceResource': {'Name': 'Sales Rep One'}},
                {'ServiceAppointmentId': '08p000000000001AAA',
                 'ServiceResource': {'Name': 'Sales Rep Two'}},
            ]}})
        if 'FROM ServiceAppointment' in query:
            return _result({'status': 0, 'result': {'records': [
                {
                    'Id': '08p000000000001AAA',
                    'Status': 'Scheduled',
                    'Local_Scheduled_Start_Time__c': '9/19/2026 10:30 AM',
                    'SchedStartTime': '2026-09-19T17:30:00.000+0000',
                    'FSSK__FSK_Work_Order__r': {
                        'WorkOrderNumber': '00012345',
                        'Street': '123 Main St',
                        'City': 'Lacey',
                        'State': 'WA',
                        'PostalCode': '98503',
                        'Market_Segment__c': 'Retail',
                        'Product_Category__c': 'Windows',
                        'WorkType': {'Name': 'Sales Appointment'},
                        'Product_Interest__c': 'Windows',
                        'Lead__r': {
                            'Name': 'Jordan Example',
                            'Phone': '360-555-1212',
                            'Canvass_Set_By__r': {'Name': 'Canvasser'},
                            'Set_By__r': {'Name': 'Setter'},
                            'LeadSource': 'Canvass',
                            'Source_Type__c': 'Canvass',
                            'Sub_Source__c': 'Door',
                            'Description': 'Customer description',
                        },
                    },
                },
                {
                    'Id': '08p000000000002AAA',
                    'Status': 'Canceled',
                    'Local_Scheduled_Start_Time__c': '9/19/2026 12:00 PM',
                    'SchedStartTime': '2026-09-19T19:00:00.000+0000',
                    'FSSK__FSK_Work_Order__r': {
                        'WorkOrderNumber': '00099999',
                        'Market_Segment__c': 'Retail',
                        'Product_Category__c': 'Windows',
                        'Lead__r': {'Name': 'Canceled Example', 'Source_Type__c': 'Canvass'},
                    },
                },
            ]}})
        raise AssertionError(query)
    return runner


def test_cli_adapter_recreates_portal_controls_and_mod_fields_read_only():
    calls = []
    adapter = SalesforceCliAdapter(runner=_salesforce_runner(calls), executable='/fake/sf')

    orgs = adapter.orgs()
    status = adapter.status('office')
    fields = adapter.portal_fields('office')
    records = adapter.mod_sheets(
        'office',
        start_date='9/19/2026',
        end_date='9/19/2026',
        market_segment='Retail',
        product_category='Windows',
        source_type='Canvass',
        remove_canceled=True,
        remove_unconfirmed=True,
    )

    assert orgs[0]['value'] == 'office'
    assert status.connected and status.username == 'rep@example.test'
    assert 'MUST_NOT_ESCAPE' not in repr(status)
    assert fields['market_segment'].values == ('Retail',)
    assert fields['product_category'].values == ('Windows',)
    assert fields['source_type'].values == ('Canvass',)

    assert len(records) == 1
    record = records[0]
    assert record.work_order_number == '00012345'
    assert record.lead_name == 'Jordan Example'
    assert record.address == '123 Main St, Lacey, WA, 98503'
    assert record.assigned_service_resources == ('Sales Rep One', 'Sales Rep Two')
    assert record.product_interest == 'Windows'
    assert record.lead_description == 'Customer description'

    # The sandbox never mutates Salesforce.
    assert all(command[1] in ('org', 'sobject', 'data') for command in calls)
    assert not any(word in ('create', 'update', 'delete', 'upsert')
                   for command in calls for word in command)


def test_portal_and_generate_are_separate_and_fail_locally():
    calls = []
    service = SalesforceSandboxService(
        SalesforceCliAdapter(runner=_salesforce_runner(calls), executable='/fake/sf')
    )
    portal = service.portal('office')
    assert portal.status.connected
    assert portal.fields['market_segment'].values == ('Retail',)

    generated = service.generate(
        'office',
        start_date='9/19/2026',
        end_date='9/19/2026',
        market_segment='Retail',
        product_category='Windows',
        source_type='Canvass',
        remove_canceled=True,
        remove_unconfirmed=True,
        color_code=True,
        limit=1000,
    )
    assert len(generated.records) == 1
    assert generated.color_code is True

    class BrokenAdapter:
        def orgs(self):
            return []
        def status(self, target_org=''):
            raise SalesforceAdapterError('CLI session unavailable')

    broken = SalesforceSandboxService(BrokenAdapter()).portal()
    assert not broken.status.connected
    assert broken.error == 'CLI session unavailable'


def test_templates_recreate_original_portal_generate_contract():
    root = Path(__file__).resolve().parents[1]
    portal = (root / 'templates/salesforce_sandbox.html').read_text()
    renderer = (root / 'salesforce_sandbox/pdf_renderer.py').read_text()

    for text in (
        'Manager On Duty Sheet',
        'Start Date:',
        'End Date:',
        'Market Segment:',
        'Product Category:',
        'Source Type:',
        'Remove Canceled Appointments:',
        'Remove Unconfirmed Appointments:',
        'Color Code Products:',
        'Generate',
        '*A maximum of 1000 appointments will be displayed',
    ):
        assert text in portal
    for name in (
        'startdate', 'enddate', 'marketsegment', 'productCategory',
        'sourceType', 'removeCanceled', 'removeUnconfirmed', 'colorCode',
    ):
        assert f'name="{name}"' in portal
    assert 'target="_blank"' in portal
    assert 'Assigned Service Resource:' in renderer
    assert 'color_code' in renderer
    assert 'MOD Notes:' in renderer


def test_pdf_renderer_accepts_only_normalized_records():
    from printer_app.mod_sheet_contract import ModSheetRecord
    from printer_app.salesforce_sandbox.pdf_renderer import render_mod_pdf

    pdf = render_mod_pdf([
        ModSheetRecord(
            source_id='08p1',
            work_order_number='00012345',
            lead_name='Jordan Example',
            assigned_service_resources=('Sales Rep One',),
            product_interest='Windows',
        )
    ], color_code=True)
    assert pdf.startswith(b'%PDF')
    assert len(pdf) > 1000


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
    app = (root / 'app.py').read_text()
    assert 'FSSK__FSK_Work_Order__r' in adapter
    assert 'FSSK__FSK_Work_Order__r' not in app
    assert 'ocr' not in adapter.lower()
