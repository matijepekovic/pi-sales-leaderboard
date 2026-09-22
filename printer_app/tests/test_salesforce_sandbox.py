"""Salesforce Sandbox regressions for the original MOD controller contract."""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter, SalesforceAdapterError
from printer_app.salesforce_sandbox.service import SalesforceSandboxService
from printer_app.mod_sheet_contract import ModSheetSourceError


def _result(value, returncode=0, stderr=''):
    return SimpleNamespace(stdout=json.dumps(value), stderr=stderr, returncode=returncode)


def _appointment(
    appointment_id,
    *,
    work_order_id='0WO000000000001AAA',
    work_order_number='00012345',
    created='2026-09-19T18:00:00.000+0000',
    scheduled='2026-09-19T17:30:00.000+0000',
    local_start='9/19/2026 10:30 AM',
    resource='Sales Rep One',
    lead_name='Jordan Example',
    lead_id='00Q000000000001AAA',
    lead_status='Open',
    appointment_status='Scheduled',
):
    return {
        'Id': appointment_id,
        'StatusCategory': appointment_status,
        'Local_Scheduled_Start_Time__c': local_start,
        'SchedStartTime': scheduled,
        'SchedEndTime': '2026-09-19T19:30:00.000+0000',
        'CreatedDate': created,
        'FSSK__FSK_Work_Order__c': work_order_id,
        'FSSK__FSK_Assigned_Service_Resource__r': {'Name': resource},
        'FSSK__FSK_Work_Order__r': {
            'WorkOrderNumber': work_order_number,
            'Address': '123 Main St, Lacey, WA 98503',
            'Street': '123 Main St',
            'City': 'Lacey',
            'State': 'WA',
            'PostalCode': '98503',
            'Product_Interest__c': 'Windows;Doors',
            'WorkType': {'Name': 'Sales Appointment'},
            'Lead__r': {
                'Id': lead_id,
                'Name': lead_name,
                'Phone': '360-555-1212',
                'Phone_3__c': '',
                'Market__c': 'Retail',
                'LeadSource': 'Canvass',
                'Sub_Source__c': 'Door',
                'Status': lead_status,
                'LastModifiedDate': '2026-09-19T16:00:00.000+0000',
                'Canvass_Set_By__r': {'Name': 'Canvasser'},
                'Set_By__r': {'Name': 'Setter'},
                'Description': 'Customer description',
            },
        },
    }


def _salesforce_runner(calls, *, appointment_records=None):
    if appointment_records is None:
        appointment_records = [_appointment('08p000000000001AAA')]

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

        query = command[command.index('--query') + 1]
        if 'FROM User' in query:
            return _result({'status': 0, 'result': {'records': [
                {'TimeZoneSidKey': 'America/Los_Angeles'},
            ]}})
        if 'FROM ServiceAppointment' in query:
            return _result({'status': 0, 'result': {'records': appointment_records}})
        raise AssertionError(query)

    return runner


def _query_calls(calls):
    return [
        call[call.index('--query') + 1]
        for call in calls
        if call[1:3] == ['data', 'query']
    ]


def _paged_salesforce_runner(calls, pages):
    remaining = iter(pages)
    other_queries = _salesforce_runner(calls)

    def runner(command, **kwargs):
        if '--query' in command:
            query = command[command.index('--query') + 1]
            if 'FROM ServiceAppointment' in query:
                calls.append(command)
                page = next(remaining)
                if isinstance(page, list):
                    return _result({'status': 0, 'result': {'records': page}})
                return page
        return other_queries(command, **kwargs)

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

    root = Path(__file__).resolve().parents[1]
    unit = (root / 'systemd/printer-app-web.service').read_text()
    app = (root / 'app.py').read_text()
    assert 'User=scoreboard' in unit
    assert "SalesforceCliAdapter(executable='/usr/bin/sf', target_org='work')" in app


def test_portal_fields_use_report_controller_fields_not_guessed_labels():
    calls = []
    adapter = SalesforceCliAdapter(runner=_salesforce_runner(calls), executable='/fake/sf')

    market = adapter.portal_field('market_segment')
    product = adapter.portal_field('product_category')
    source = adapter.portal_field('source_type')

    assert market.path == 'FSSK__FSK_Work_Order__r.Lead__r.Market__c'
    assert product.path == 'FSSK__FSK_Work_Order__r.Product_Interest__c'
    assert source.path == 'FSSK__FSK_Work_Order__r.Lead__r.LeadSource'
    assert market.values == ('Retail',)
    assert product.values == (
        'Roofing', 'Siding', 'Bath', 'Gutters', 'Windows',
        'Doors', 'Other', 'Walk-In Tubs', 'Solar',
    )
    assert source.values == (
        'Canvass', 'Flyer', 'Internet', 'Other', 'Previous Customer',
        'Referral', 'Self Generated Lead', 'Telemarketing', 'Shows',
    )
    assert not any(call[1:3] == ['sobject', 'describe'] for call in calls)


def test_mod_query_and_grouping_match_original_apex_controller():
    calls = []
    later_created = _appointment(
        '08p000000000001AAA',
        created='2026-09-19T18:00:00.000+0000',
        scheduled='2026-09-19T17:00:00.000+0000',
        local_start='FIRST ROW SHOULD NOT WIN',
        resource='Sales Rep Two',
    )
    earlier_created = _appointment(
        '08p000000000002AAA',
        created='2026-09-19T17:00:00.000+0000',
        scheduled='2026-09-19T17:30:00.000+0000',
        local_start='SELECTED EARLIER CREATED ROW',
        resource='Sales Rep One',
    )
    adapter = SalesforceCliAdapter(
        runner=_salesforce_runner(calls, appointment_records=[later_created, earlier_created]),
        executable='/fake/sf',
    )

    records = adapter.mod_sheets(
        start_date='9/19/2026',
        end_date='9/19/2026',
        market_segment='Retail',
        product_category='Windows',
        source_type='Canvass',
        remove_canceled=True,
        remove_unconfirmed=True,
        limit=1000,
    )

    report_query = next(query for query in _query_calls(calls) if 'FROM ServiceAppointment' in query
                        and 'Local_Scheduled_Start_Time__c' in query)
    assert "WHERE WorkType.Name LIKE '%Sales%'" in report_query
    assert "Product_Interest__c INCLUDES ('Windows')" in report_query
    assert "Lead__r.Market__c = 'Retail'" in report_query
    assert "Lead__r.LeadSource = 'Canvass'" in report_query
    assert "Lead__r.Status != 'Canceled'" in report_query
    assert 'Lead__r.LastModifiedDate != null' in report_query
    assert 'FSSK__FSK_Assigned_Service_Resource__r.Name' in report_query
    assert 'FSSK__FSK_Work_Order__c' in report_query
    assert 'FSSK__FSK_Work_Order__r.Lead__r.Status' in report_query.split(' FROM ')[0]
    assert 'FSSK__FSK_Work_Order__r.Lead__r.Id' in report_query.split(' FROM ')[0]
    assert 'StatusCategory' in report_query.split(' FROM ')[0]
    assert 'ORDER BY SchedStartTime, FSSK__FSK_Work_Order__r.Lead__r.Name ASC LIMIT 1000' in report_query
    assert not any('FROM AssignedResource' in query for query in _query_calls(calls))

    assert len(records) == 1
    record = records[0]
    assert record.source_id == '0WO000000000001AAA'
    assert record.local_scheduled_start_time == 'SELECTED EARLIER CREATED ROW'
    assert record.assigned_service_resources == ('Sales Rep Two', 'Sales Rep One')
    assert record.scheduled_start == '2026.09.19 ; 10:30:00 AM'
    assert record.work_order_number == '00012345'
    assert record.lead_name == 'Jordan Example'
    assert record.address == '123 Main St, Lacey, WA, 98503'
    assert record.phone == '360-555-1212'
    assert record.set_by == 'Setter'
    assert record.work_type == 'Sales Appointment'
    assert record.product_interest == 'Windows;Doors'
    assert record.source == 'Canvass'
    assert record.sub_source == 'Door'
    assert record.lead_description == 'Customer description'
    assert record.sales_lead_status == 'Open'
    assert record.lead_source_id == '00Q000000000001AAA'


@pytest.mark.parametrize('second_lead_id', ['00Q000000000001AAA', '00Q000000000002AAA'])
def test_direct_work_order_lookup_needs_no_date_and_returns_current_normalized_appointment():
    calls = []
    rows = [
        _appointment(
            '08p000000000001AAA',
            scheduled='2026-09-19T17:30:00.000+0000',
            resource='Old Rep', appointment_status='Canceled',
        ),
        _appointment(
            '08p000000000002AAA',
            scheduled='2026-09-21T18:00:00.000+0000',
            local_start='9/21/2026 11:00 AM',
            resource='Current Rep',
        ),
        _appointment(
            '08p000000000003AAA',
            scheduled='2026-09-21T18:00:00.000+0000',
            local_start='9/21/2026 11:00 AM',
            resource='Second Rep',
        ),
    ]
    adapter = SalesforceCliAdapter(
        runner=_salesforce_runner(calls, appointment_records=rows),
        executable='/fake/sf',
    )

    records = adapter.work_orders(['00012345'])

    query = next(query for query in _query_calls(calls)
                 if 'FROM ServiceAppointment' in query and 'WorkOrderNumber IN' in query)
    assert "WorkOrderNumber IN ('00012345')" in query
    assert 'SchedStartTime >=' not in query
    assert 'SchedStartTime <' not in query
    assert len(records) == 1
    record = records[0]
    assert record.work_order_number == '00012345'
    assert record.appointment_date == '2026-09-21'
    assert record.lead_name == 'Jordan Example'
    assert record.address == '123 Main St, Lacey, WA, 98503'
    assert record.assigned_service_resources == ('Current Rep', 'Second Rep')


def test_work_orders_preserve_exact_lead_identity_even_when_names_match(second_lead_id):
    adapter = SalesforceCliAdapter(runner=_salesforce_runner([], appointment_records=[
        _appointment('08p000000000001AAA', lead_status='Sold'),
        _appointment(
            '08p000000000002AAA', work_order_id='0WO000000000002AAA',
            work_order_number='00012346', lead_id=second_lead_id, lead_status='Sold',
        ),
    ]))
    records = adapter.mod_sheets(start_date='2026-09-19', end_date='2026-09-19')
    assert len(records) == 2
    assert records[0].work_order_number == '00012345'
    assert records[1].work_order_number == '00012346'
    assert records[0].lead_name == records[1].lead_name == 'Jordan Example'
    assert records[0].lead_source_id == '00Q000000000001AAA'
    assert records[1].lead_source_id == second_lead_id


def test_missing_lead_id_is_not_replaced_with_name_or_work_order_id():
    adapter = SalesforceCliAdapter(runner=_salesforce_runner([], appointment_records=[
        _appointment('08p000000000001AAA', lead_id=None, lead_status='Sold'),
    ]))
    records = adapter.mod_sheets(start_date='2026-09-19', end_date='2026-09-19')
    assert records[0].lead_source_id == ''
    assert records[0].sales_lead_status == 'Sold'


@pytest.mark.parametrize('reverse', [False, True])
def test_active_appointment_wins_over_canceled_for_same_work_order_day(reverse):
    rows = [
        _appointment(
            '08p000000000001AAA',
            created='2026-09-19T15:00:00.000+0000',
            resource='Former Rep', appointment_status='Canceled',
            local_start='Canceled appointment', lead_status='Former status',
        ),
        _appointment(
            '08p000000000002AAA',
            created='2026-09-19T18:00:00.000+0000',
            resource='Current Rep', local_start='Active appointment',
            lead_status='Sold',
        ),
        _appointment(
            '08p000000000003AAA',
            created='2026-09-19T19:00:00.000+0000',
            resource='Second Current Rep', lead_status='Sold',
        ),
    ]
    if reverse:
        rows.reverse()
    adapter = SalesforceCliAdapter(runner=_salesforce_runner([], appointment_records=rows))
    records = adapter.mod_sheets(
        start_date='2026-09-19', end_date='2026-09-19', remove_canceled=False,
    )
    assert len(records) == 1
    assert records[0].work_order_number == '00012345'
    assert records[0].local_scheduled_start_time == 'Active appointment'
    assert records[0].sales_lead_status == 'Sold'
    assert set(records[0].assigned_service_resources) == {'Current Rep', 'Second Current Rep'}


def test_canceled_appointment_fallback_keeps_actual_lead_status_and_all_canceled_reps():
    calls = []
    rows = [
        _appointment(
            '08p000000000001AAA', appointment_status='Canceled',
            lead_status='Sold', resource='Rep One',
        ),
        _appointment(
            '08p000000000002AAA', appointment_status='Canceled',
            lead_status='Sold', resource='Rep Two',
        ),
    ]
    adapter = SalesforceCliAdapter(runner=_salesforce_runner(calls, appointment_records=rows))
    records = adapter.mod_sheets(
        start_date='2026-09-19', end_date='2026-09-19', remove_canceled=False,
    )
    assert len(records) == 1
    assert records[0].sales_lead_status == 'Sold'
    assert records[0].assigned_service_resources == ('Rep One', 'Rep Two')
    queries = [q for q in _query_calls(calls) if 'FROM ServiceAppointment' in q]
    assert len(queries) == 1
    assert 'SchedStartTime >= 2026-09-19T07:00:00Z' in queries[0]
    assert 'SchedStartTime < 2026-09-20T07:00:00Z' in queries[0]
    assert "Status != 'Canceled'" not in queries[0]


@pytest.mark.parametrize('lead_status', ['', None])
def test_canceled_appointment_without_lead_status_does_not_invent_a_status(lead_status):
    adapter = SalesforceCliAdapter(runner=_salesforce_runner([], appointment_records=[
        _appointment(
            '08p000000000001AAA', appointment_status='Canceled', lead_status=lead_status,
        ),
    ]))
    records = adapter.mod_sheets(
        start_date='2026-09-19', end_date='2026-09-19', remove_canceled=False,
    )
    assert records[0].sales_lead_status == ''


def test_canceled_fallback_cannot_borrow_active_appointment_from_another_date():
    adapter = SalesforceCliAdapter(runner=_salesforce_runner([], appointment_records=[
        _appointment(
            '08p000000000001AAA', appointment_status='Canceled',
            resource='Canceled Day Rep', lead_status='Canceled',
        ),
        _appointment(
            '08p000000000002AAA', scheduled='2026-09-20T17:30:00.000+0000',
            resource='Next Day Rep', lead_status='Open',
        ),
    ]))
    records = adapter.mod_sheets(
        start_date='2026-09-19', end_date='2026-09-19', remove_canceled=False,
    )
    assert len(records) == 1
    assert records[0].sales_lead_status == 'Canceled'
    assert records[0].assigned_service_resources == ('Canceled Day Rep',)


def test_multi_day_query_keeps_same_work_order_on_each_date():
    adapter = SalesforceCliAdapter(runner=_salesforce_runner([], appointment_records=[
        _appointment(
            '08p000000000001AAA', appointment_status='Canceled',
            resource='First Day Rep', lead_status='Canceled',
        ),
        _appointment(
            '08p000000000002AAA', scheduled='2026-09-20T17:30:00.000+0000',
            local_start='9/20/2026 10:30 AM', resource='Second Day Rep', lead_status='Sold',
        ),
    ]))
    records = adapter.mod_sheets(
        start_date='2026-09-19', end_date='2026-09-20', remove_canceled=False,
    )
    assert len(records) == 2
    assert [record.work_order_number for record in records] == ['00012345', '00012345']
    assert records[0].scheduled_start.startswith('2026.09.19')
    assert records[0].sales_lead_status == 'Canceled'
    assert records[0].assigned_service_resources == ('First Day Rep',)
    assert records[1].scheduled_start.startswith('2026.09.20')
    assert records[1].sales_lead_status == 'Sold'
    assert records[1].assigned_service_resources == ('Second Day Rep',)


def test_source_type_all_uses_original_controller_allowlist():
    calls = []
    adapter = SalesforceCliAdapter(runner=_salesforce_runner(calls), executable='/fake/sf')
    adapter.mod_sheets(
        start_date='9/19/2026',
        end_date='9/19/2026',
        source_type='All',
        product_category='All',
        remove_canceled=False,
        remove_unconfirmed=False,
    )

    report_query = next(query for query in _query_calls(calls) if 'FROM ServiceAppointment' in query
                        and 'Local_Scheduled_Start_Time__c' in query)
    assert 'Lead__r.LeadSource IN (' in report_query
    for value in ('Canvass', 'Previous Customer', 'Self Generated Lead', 'Shows'):
        assert value in report_query
    assert 'Product_Interest__c INCLUDES' not in report_query
    assert "Lead__r.Status != 'Canceled'" not in report_query
    assert 'Lead__r.LastModifiedDate != null' not in report_query


def test_empty_controller_result_returns_original_error():
    calls = []
    adapter = SalesforceCliAdapter(
        runner=_salesforce_runner(calls, appointment_records=[]),
        executable='/fake/sf',
    )
    with pytest.raises(SalesforceAdapterError, match='No Records Found for Selected Criteria'):
        adapter.mod_sheets(start_date='9/19/2026', end_date='9/19/2026')


def test_unlimited_records_collect_all_pages_and_resources_without_portal_filters():
    calls = []
    first_page = [_appointment(f'08p{index:012d}AAA') for index in range(1, 1001)]
    second_page = [
        _appointment('08p000000001001AAA', resource='Second Sales Rep'),
        _appointment('08p000000001002AAA', work_order_id='0WO000000000002AAA'),
    ]
    service = SalesforceSandboxService(SalesforceCliAdapter(
        runner=_paged_salesforce_runner(calls, [first_page, second_page, []]),
    ))

    records = service.records(
        start_date='2026-09-19', end_date='2026-09-19',
        market_segment='', product_category='', source_type='',
        remove_canceled=False, remove_unconfirmed=False, limit=None,
    )

    assert isinstance(records, tuple)
    assert len(records) == 2
    assert records[0].assigned_service_resources == ('Sales Rep One', 'Second Sales Rep')
    assert records[1].source_id == '0WO000000000002AAA'
    queries = [query for query in _query_calls(calls) if 'FROM ServiceAppointment' in query]
    assert len(queries) == 3
    assert ' AND Id > ' not in queries[0]
    assert " AND Id > '08p000000001000AAA'" in queries[1]
    assert " AND Id > '08p000000001002AAA'" in queries[2]
    for query in queries:
        assert query.endswith('ORDER BY Id ASC LIMIT 1000')
        assert 'FSSK__FSK_Assigned_Service_Resource__r.Name' in query
        assert 'Market__c =' not in query
        assert 'Product_Interest__c INCLUDES' not in query
        assert 'LeadSource IN (' not in query
        assert 'LeadSource =' not in query
        assert "Status != 'Canceled'" not in query
        assert 'LastModifiedDate != null' not in query


def test_unlimited_records_continue_after_short_pages():
    calls = []
    service = SalesforceSandboxService(SalesforceCliAdapter(
        runner=_paged_salesforce_runner(calls, [
            [_appointment('08p000000000001AAA')],
            [_appointment('08p000000000002AAA', resource='Second Sales Rep')],
            [],
        ]),
    ))
    records = service.records(start_date='2026-09-19', end_date='2026-09-19', limit=None)
    assert records[0].assigned_service_resources == ('Sales Rep One', 'Second Sales Rep')


@pytest.mark.parametrize(('day', 'start_utc', 'end_utc'), [
    ('2026-09-19', '2026-09-19T07:00:00Z', '2026-09-20T07:00:00Z'),
    ('2026-03-08', '2026-03-08T08:00:00Z', '2026-03-09T07:00:00Z'),
    ('2026-11-01', '2026-11-01T07:00:00Z', '2026-11-02T08:00:00Z'),
])
def test_records_use_exact_local_day_including_last_second(day, start_utc, end_utc):
    calls = []
    start = datetime.fromisoformat(start_utc)
    end = datetime.fromisoformat(end_utc)
    rows = [
        _appointment(f'08p{index:012d}AAA', scheduled=stamp.isoformat(), resource=resource)
        for index, (stamp, resource) in enumerate([
            (start - timedelta(microseconds=1), 'Previous Day'),
            (start, 'First Appointment'),
            (end - timedelta(microseconds=1), 'Last Appointment'),
            (end, 'Next Day'),
        ], start=1)
    ]
    service = SalesforceSandboxService(SalesforceCliAdapter(
        runner=_paged_salesforce_runner(calls, [rows, []]),
    ))
    records = service.records(start_date=day, end_date=day, limit=None)
    assert records[0].assigned_service_resources == ('First Appointment', 'Last Appointment')
    query = next(query for query in _query_calls(calls) if 'FROM ServiceAppointment' in query)
    assert f'SchedStartTime >= {start_utc}' in query
    assert f'SchedStartTime < {end_utc}' in query


def test_empty_unlimited_records_are_a_valid_empty_source_result():
    service = SalesforceSandboxService(SalesforceCliAdapter(
        runner=_paged_salesforce_runner([], [[]]),
    ))
    assert service.records(start_date='2026-09-19', end_date='2026-09-19', limit=None) == ()


@pytest.mark.parametrize('second_page', [
    _result({'status': 1, 'message': 'Query unavailable'}, returncode=1),
    _result({'status': 0, 'result': {}}),
    _result({'status': 0, 'result': {'records': [], 'done': False, 'totalSize': 1}}),
    [_appointment('08p000000000001AAA')],
    [_appointment('invalid-id')],
])
def test_later_page_failure_never_returns_partial_records(second_page):
    calls = []
    service = SalesforceSandboxService(SalesforceCliAdapter(
        runner=_paged_salesforce_runner(calls, [
            [_appointment('08p000000000001AAA')], second_page,
        ]),
    ))
    with pytest.raises(ModSheetSourceError):
        service.records(start_date='2026-09-19', end_date='2026-09-19', limit=None)


@pytest.mark.parametrize(('limit', 'expected'), [(-1, 1), (3, 3), (5000, 1000)])
def test_finite_limit_keeps_one_query_and_original_ordering(limit, expected):
    calls = []
    adapter = SalesforceCliAdapter(runner=_salesforce_runner(calls))
    adapter.mod_sheets(start_date='2026-09-19', end_date='2026-09-19', limit=limit)
    queries = [query for query in _query_calls(calls) if 'FROM ServiceAppointment' in query]
    assert len(queries) == 1
    assert queries[0].endswith(
        f'ORDER BY SchedStartTime, FSSK__FSK_Work_Order__r.Lead__r.Name ASC LIMIT {expected}'
    )


def test_connection_check_is_separate_from_filter_loading():
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
    assert product.field.values == (
        'Roofing', 'Siding', 'Bath', 'Gutters', 'Windows',
        'Doors', 'Other', 'Walk-In Tubs', 'Solar',
    )
    assert source.field.values[0] == 'Canvass'


def test_portal_ui_preserves_controller_all_semantics_and_black_shell():
    root = Path(__file__).resolve().parents[1]
    portal = (root / 'templates/salesforce_sandbox.html').read_text()
    js = (root / 'static/mod_sheets/runtime.js').read_text()
    css = (root / 'static/mod_sheets/shared.css').read_text()

    assert "product_category', label: 'Product Category', allValue: 'All'" in js
    assert "source_type', label: 'Source Type', allValue: 'All'" in js
    assert "market_segment', label: 'Market Segment', allValue: ''" in js
    assert 'modSourceLog' in portal
    assert 'background:#000' in css
    assert 'color:#fff' in css


def test_pdf_renderer_keeps_original_mod_labels_and_normalized_contract():
    from printer_app.mod_sheet_contract import ModSheetRecord
    from printer_app.mod_sheets.pdf_renderer import render_mod_pdf

    root = Path(__file__).resolve().parents[1]
    renderer = (root / 'mod_sheets/pdf_renderer.py').read_text()
    for label in (
        'Work Order Number:', 'Local Scheduled Start Time:', 'Canvass Set By:',
        'Lead Name:', 'Address:', 'Phone:',
        'Scheduled Start:', 'Assigned Service Resource:', 'Set By:', 'T Close:',
        'Work Type:', 'Product Interest:', 'Source:', 'Sub Source:', 'Hover / Flir:',
        'Lead Description:', 'Start Price:', 'Final Price:', 'Deposit/Payment:',
        'MOD Notes:', 'Fin Checklist', 'Bid Sheets', 'Pictures', 'Dispo:',
        'Call 1:', 'Call 2:', '90 Min:', 'Need:', 'Want:',
    ):
        assert label in renderer
    assert "'Power'" in renderer
    assert "'Questions'" in renderer

    pdf = render_mod_pdf([
        ModSheetRecord(
            source_id='0WO1',
            work_order_number='00012345',
            lead_name='Jordan Example',
            assigned_service_resources=('Sales Rep One',),
            product_interest='Windows',
        )
    ])
    assert pdf.startswith(b'%PDF')
    assert len(pdf) > 1000



def test_pdf_renderer_matches_reference_mod_grid():
    from printer_app.mod_sheet_contract import ModSheetRecord
    from printer_app.mod_sheets.pdf_renderer import (
        MOD_COLUMNS,
        MOD_ROW_HEIGHTS,
        MOD_TABLE_WIDTH,
        _mod_table,
    )

    table = _mod_table(ModSheetRecord(source_id='0WO1'), color_code=False)

    assert MOD_COLUMNS == 10
    assert MOD_TABLE_WIDTH == pytest.approx(571.65)
    assert tuple(table._argH) == MOD_ROW_HEIGHTS
    assert len(table._argW) == 10
    assert sum(table._argW) == pytest.approx(MOD_TABLE_WIDTH)
    assert table._cellvalues[0][0].label == 'Work Order Number: '
    assert ('SPAN', (0, 0), (2, 0)) in table._spanCmds
    assert ('SPAN', (3, 0), (6, 0)) in table._spanCmds
    assert ('SPAN', (7, 0), (9, 0)) in table._spanCmds
    assert ('SPAN', (4, 5), (9, 10)) in table._spanCmds



def test_mod_pdf_fits_three_cards_per_page_deterministically():
    from io import BytesIO

    from pypdf import PdfReader

    from printer_app.mod_sheet_contract import ModSheetRecord
    from printer_app.mod_sheets.pdf_renderer import render_mod_pdf

    def records(count):
        return [
            ModSheetRecord(
                source_id=f'0WO{index}',
                work_order_number=f'{index:08d}',
                lead_name='Example Customer',
                address='123 Example Street, Lacey, WA, 98503',
                assigned_service_resources=('Sales Rep One',),
                lead_description='Short description.',
            )
            for index in range(count)
        ]

    assert len(PdfReader(BytesIO(render_mod_pdf(records(3)))).pages) == 1
    assert len(PdfReader(BytesIO(render_mod_pdf(records(6)))).pages) == 2
    assert len(PdfReader(BytesIO(render_mod_pdf(records(7)))).pages) == 3


def test_variable_mod_text_shrinks_then_clips_at_seven_points():
    from printer_app.mod_sheets.pdf_renderer import _FitClipParagraph

    moderate = _FitClipParagraph(
        'Address: ',
        '12345 A Very Long Street Name That Needs A Smaller Value Font, Lacey, Washington',
        max_height=20,
    )
    moderate.wrap(150, 100)
    assert 7 <= moderate.value_font_size <= 9

    extreme = _FitClipParagraph(
        'Lead Description: ',
        'very long description ' * 80,
        max_height=20,
    )
    width, height = extreme.wrap(150, 100)
    assert width == 150
    assert height <= 20
    assert extreme.value_font_size == 7
    assert extreme.clipped is True



def test_mod_pdf_draws_plain_page_number_in_bottom_right_corner():
    from printer_app.mod_sheets.pdf_renderer import (
        PAGE_NUMBER_FONT_SIZE,
        PAGE_NUMBER_X,
        PAGE_NUMBER_Y,
        _draw_page_number,
    )

    class FakeCanvas:
        def __init__(self):
            self.calls = []

        def saveState(self):
            self.calls.append(('save',))

        def setFillColor(self, color):
            self.calls.append(('fill', color))

        def setFont(self, font, size):
            self.calls.append(('font', font, size))

        def drawRightString(self, x, y, text):
            self.calls.append(('draw', x, y, text))

        def getPageNumber(self):
            return 4

        def restoreState(self):
            self.calls.append(('restore',))

    canvas = FakeCanvas()
    _draw_page_number(canvas, None)

    assert ('font', 'Times-Roman', PAGE_NUMBER_FONT_SIZE) in canvas.calls
    assert ('draw', PAGE_NUMBER_X, PAGE_NUMBER_Y, '4') in canvas.calls


def test_salesforce_stays_isolated_from_gallery_printing_and_ocr():
    root = Path(__file__).resolve().parents[1]
    for path in list((root / 'gallery').glob('*.py')) + [
        root / 'printer.py',
        root / 'print_dispatch.py',
        root / 'print_queue_repository.py',
    ]:
        assert 'salesforce' not in path.read_text().lower(), str(path)

    adapter = (root / 'salesforce_sandbox/adapter.py').read_text()
    app = (root / 'app.py').read_text()
    worker = (root / 'worker.py').read_text()
    assert 'FSSK__FSK_Work_Order__r' in adapter
    assert 'FSSK__FSK_Work_Order__r' not in app
    assert 'FSSK__FSK_Work_Order__r' not in worker
    assert 'Lead__r' not in worker
    assert 'ocr' not in adapter.lower()
