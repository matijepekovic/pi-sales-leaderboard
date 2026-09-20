"""Salesforce Sandbox stays isolated, read-only, and observable."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter, SalesforceAdapterError
from printer_app.salesforce_sandbox.service import SalesforceSandboxService


def _result(value, returncode=0, stderr=''):
    return SimpleNamespace(stdout=json.dumps(value), stderr=stderr, returncode=returncode)


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
        if command[1:3] == ['org', 'display']:
            return _result({'status': 0, 'result': {
                'username': 'rep@example.test',
                'alias': 'work',
                'instanceUrl': 'https://example.my.salesforce.com',
                'id': '00D000000000123',
                'connectedStatus': 'Connected',
            }})
        if command[1:3] == ['sobject', 'describe']:
            sobject = command[command.index('--sobject') + 1]
            return _result({'status': 0, 'result': {'fields': _describe_fields(sobject)}})

        query = command[command.index('--query') + 1]
        if 'FROM AssignedResource' in query:
            return _result({'status': 0, 'result': {'records': [
                {'ServiceAppointmentId': '08p000000000001AAA',
                 'ServiceResource': {'Name': 'Sales Rep One'}},
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
            ]}})
        raise AssertionError(query)
    return runner


def test_cli_error_surfaces_useful_node_cause():
    def runner(command, **kwargs):
        return SimpleNamespace(
            stdout='',
            stderr="node:events:505\nError: spawn secret-tool ENOENT\ncode: 'ENOENT'\n",
            returncode=1,
        )

    adapter = SalesforceCliAdapter(runner=runner, executable='/usr/bin/sf')
    with pytest.raises(SalesforceAdapterError) as exc:
        adapter.status()
    assert 'node:events:505' not in str(exc.value)
    assert 'spawn secret-tool ENOENT' in str(exc.value)


def test_connection_uses_explicit_work_alias_and_safe_trace():
    calls = []
    trace = []
    adapter = SalesforceCliAdapter(runner=_salesforce_runner(calls))
    status = adapter.status(trace=trace)

    assert status.connected
    assert calls == [[
        '/usr/bin/sf', 'org', 'display',
        '--target-org', 'work', '--json',
    ]]
    assert trace[0]['input'].endswith('--target-org work --json')
    assert '"alias":"work"' in trace[0]['result']

    root = Path(__file__).resolve().parents[1]
    unit = (root / 'systemd/printer-app-web.service').read_text()
    app = (root / 'app.py').read_text()
    assert 'User=scoreboard' in unit
    assert "SalesforceCliAdapter(executable='/usr/bin/sf', target_org='work')" in app


def test_adapter_resolves_fields_and_normalizes_mod_records_read_only():
    calls = []
    adapter = SalesforceCliAdapter(runner=_salesforce_runner(calls), executable='/fake/sf')

    market = adapter.portal_field('market_segment')
    product = adapter.portal_field('product_category')
    source = adapter.portal_field('source_type')
    records = adapter.mod_sheets(
        start_date='9/19/2026',
        end_date='9/19/2026',
        market_segment='Retail',
        product_category='Windows',
        source_type='Canvass',
        remove_canceled=True,
        remove_unconfirmed=True,
    )

    assert market.path == 'FSSK__FSK_Work_Order__r.Lead__r.Market__c'
    assert product.path == 'FSSK__FSK_Work_Order__r.Product_Interest__c'
    assert source.path == 'FSSK__FSK_Work_Order__r.Lead__r.LeadSource'
    assert market.values == ('Retail',)
    assert product.values == ('Windows',)
    assert source.values == (
        'Canvass', 'Flyer', 'Internet', 'Other', 'Previous Customer',
        'Referral', 'Self Generated Lead', 'Telemarketing', 'Shows',
    )
    option_queries = [
        call for call in calls
        if call[1:3] == ['data', 'query']
        and call[call.index('--query') + 1].startswith('SELECT FSSK__FSK_Work_Order__r')
        and 'LIMIT 1000' in call[call.index('--query') + 1]
    ]
    assert len(option_queries) == 2
    assert len(records) == 1
    assert records[0].work_order_number == '00012345'
    assert records[0].lead_name == 'Jordan Example'
    assert records[0].address == '123 Main St, Lacey, WA, 98503'
    assert records[0].assigned_service_resources == ('Sales Rep One',)
    assert records[0].product_interest == 'Windows'
    assert records[0].lead_description == 'Customer description'
    assert all('--target-org' in call and call[call.index('--target-org') + 1] == 'work'
               for call in calls)
    assert not any(word in ('create', 'update', 'delete', 'upsert')
                   for call in calls for word in call)


def test_connection_check_is_separate_from_slow_field_loading():
    calls = []
    service = SalesforceSandboxService(
        SalesforceCliAdapter(runner=_salesforce_runner(calls), executable='/fake/sf')
    )

    portal = service.portal()
    assert calls == []
    assert not portal.status.connected

    connection = service.connection()
    assert connection.status.connected
    assert len(calls) == 1
    assert calls[0][1:3] == ['org', 'display']

    market = service.field('market_segment')
    product = service.field('product_category')
    source = service.field('source_type')
    assert market.field.values == ('Retail',)
    assert product.field.values == ('Windows',)
    assert source.field.values[0] == 'Canvass'
    assert market.trace and product.trace and source.trace
    assert not any(call[1:3] == ['sobject', 'describe'] for call in calls)


def test_parallel_field_requests_use_exact_controller_contracts():
    calls = []
    adapter = SalesforceCliAdapter(runner=_salesforce_runner(calls), executable='/fake/sf')

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(adapter.portal_field, key)
            for key in ('market_segment', 'product_category', 'source_type')
        ]
        resolved = [future.result() for future in futures]

    assert [field.label for field in resolved] == [
        'Market Segment', 'Product Category', 'Source Type',
    ]
    assert [field.path for field in resolved] == [
        'FSSK__FSK_Work_Order__r.Lead__r.Market__c',
        'FSSK__FSK_Work_Order__r.Product_Interest__c',
        'FSSK__FSK_Work_Order__r.Lead__r.LeadSource',
    ]
    assert not any(call[1:3] == ['sobject', 'describe'] for call in calls)


def test_connection_failure_preserves_trace_for_side_panel():
    class BrokenAdapter:
        def status(self, trace=None):
            if trace is not None:
                trace.append({'input': '/usr/bin/sf org display', 'result': 'failed', 'ok': False})
            raise SalesforceAdapterError('CLI session unavailable')

    snapshot = SalesforceSandboxService(BrokenAdapter()).connection()
    assert not snapshot.status.connected
    assert snapshot.error == 'CLI session unavailable'
    assert snapshot.trace[0]['ok'] is False


def test_portal_ui_loads_connection_then_fields_and_has_cli_panel():
    root = Path(__file__).resolve().parents[1]
    portal = (root / 'templates/salesforce_sandbox.html').read_text()
    js = (root / 'static/salesforce_sandbox.js').read_text()
    css = (root / 'static/salesforce_sandbox.css').read_text()
    web = (root / 'salesforce_sandbox/web.py').read_text()

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

    assert 'data-connection-url' in portal
    assert 'data-field-url' in portal
    assert 'sfShellLog' in portal
    assert 'Salesforce CLI' in portal
    assert 'state.dataset.connectionUrl' in js
    assert 'state.dataset.fieldUrl' in js
    assert '25000' in js and '100000' in js
    assert 'Promise.all(fields.map(loadField))' in js
    assert '/salesforce-sandbox/api/connection' in web
    assert '/salesforce-sandbox/api/field/<key>' in web
    assert 'sf-workspace' in css and 'sf-shell' in css
    assert 'background:#000' in css and 'color:#fff' in css
    assert 'name="org"' not in portal
    for name in (
        'startdate', 'enddate', 'marketsegment', 'productCategory',
        'sourceType', 'removeCanceled', 'removeUnconfirmed', 'colorCode',
    ):
        assert f'name="{name}"' in portal
    assert 'target="_blank"' in portal
    assert '<style>' not in portal and 'onchange=' not in portal


def test_pdf_renderer_accepts_normalized_records():
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


def test_salesforce_stays_isolated_from_gallery_printing_and_ocr():
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

    base = (root / 'templates/base.html').read_text()
    control = (root / 'templates/control.html').read_text()
    assert "url_for('salesforce_sandbox.page')" in base
    assert "url_for('salesforce_sandbox.page')" in control
    assert 'Salesforce Sandbox' in control
