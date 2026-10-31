"""Printing and digital MOD use the same final Work Order ordering.

No Salesforce connection, printer, or UI changes are needed for this contract.
"""
from zoneinfo import ZoneInfo

from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter
from printer_app.salesforce_sandbox.service import SalesforceSandboxService


A = '0WO000000000001AAA'
B = '0WO000000000002AAA'
C = '0WO000000000003AAA'


def _appointment(record_id, work_order_id, name, start, *,
                 canceled=False, resource='Rep One', created='2026-10-28T12:00:00Z',
                 local_display=''):
    return {
        'Id': record_id,
        'StatusCategory': 'Canceled' if canceled else 'Scheduled',
        'SchedStartTime': '2026-10-30T' + start + ':00Z',
        'CreatedDate': created,
        'Local_Scheduled_Start_Time__c': local_display,
        'FSSK__FSK_Work_Order__c': work_order_id,
        'FSSK__FSK_Assigned_Service_Resource__r': {'Name': resource},
        'FSSK__FSK_Work_Order__r': {
            'WorkOrderNumber': work_order_id,
            'Product_Interest__c': 'Roofing',
            'Lead__r': {'Name': name, 'Status': 'New', 'Id': '00Q000000000001AAA'},
        },
    }


def test_print_and_digital_use_same_order_after_grouping(monkeypatch):
    # A's canceled 8:00 appointment comes first in the printing query, but
    # its active appointment is at 9:30. It must move behind B and C.
    canceled_a = _appointment(
        '08p000000000001AAA', A, 'Zoe', '15:00', canceled=True)
    b = _appointment('08p000000000002AAA', B, 'Alex', '15:30',
                     local_display='11:30 AM')
    c = _appointment('08p000000000003AAA', C, 'Blair', '15:30')
    active_a = _appointment('08p000000000004AAA', A, 'Zoe', '16:30',
                            resource='Rep One', local_display='7:00 AM')
    split_a = _appointment('08p000000000005AAA', A, 'Zoe', '16:30',
                           resource='Rep Two', created='2026-10-29T12:00:00Z')

    # The actual print path reads a scheduled-start ordered, limited page.
    print_rows = [canceled_a, b, c, active_a, split_a]
    # The digital path pages by Salesforce Id and sorts the raw records
    # before grouping. It must still produce the identical final card order.
    digital_rows = [active_a, c, split_a, canceled_a, b]
    adapter = SalesforceCliAdapter(runner=lambda *a, **k: None)
    monkeypatch.setattr(
        adapter, '_salesforce_timezone',
        lambda: ZoneInfo('America/Los_Angeles'),
    )
    monkeypatch.setattr(
        adapter, '_appointment_rows',
        lambda fields, conditions, *, limit=None, **kwargs:
            print_rows if limit is not None else digital_rows,
    )
    source = SalesforceSandboxService(adapter)
    kwargs = {
        'start_date': '10/30/2026',
        'end_date': '10/30/2026',
        'market_segment': 'Olympia',
        'product_category': 'All',
        'remove_canceled': False,
        'remove_unconfirmed': False,
    }
    printed = source.records(**kwargs, limit=1000)
    digital = source.records(**kwargs, limit=None)
    expected = (B, C, A)
    assert tuple(item.source_id for item in printed) == expected
    assert tuple(item.source_id for item in digital) == expected
    assert tuple(item.scheduled_start for item in digital) == (
        '2026.10.30 ; 08:30:00 AM',
        '2026.10.30 ; 08:30:00 AM',
        '2026.10.30 ; 09:30:00 AM',
    )
    # Display-only local start values must not change the printer order.
    assert digital[0].local_scheduled_start_time == '11:30 AM'
    assert digital[2].local_scheduled_start_time == '7:00 AM'
    # All co-assigned resources and the active fallback survive regrouping.
    assert digital[2].assigned_service_resources == ('Rep One', 'Rep Two')


def test_canceled_only_appointment_is_flagged_but_active_one_is_not(monkeypatch):
    canceled = _appointment(
        '08p000000000006AAA', A, 'Canceled Customer', '15:00', canceled=True)
    active = _appointment(
        '08p000000000007AAA', B, 'Active Customer', '16:00')
    canceled_fallback = _appointment(
        '08p000000000008AAA', B, 'Active Customer', '15:30', canceled=True)
    adapter = SalesforceCliAdapter(runner=lambda *a, **k: None)
    monkeypatch.setattr(
        adapter, '_salesforce_timezone',
        lambda: ZoneInfo('America/Los_Angeles'),
    )
    monkeypatch.setattr(
        adapter, '_appointment_rows',
        lambda fields, conditions, *, limit=None, **kwargs:
            [canceled, canceled_fallback, active],
    )
    source = SalesforceSandboxService(adapter)
    for limit in (1000, None):
        records = source.records(
            start_date='10/30/2026', end_date='10/30/2026',
            market_segment='Olympia',
            product_category='All',
            remove_canceled=False, remove_unconfirmed=False, limit=limit)
        by_id = {record.source_id: record for record in records}
        assert by_id[A].appointment_canceled is True
        assert by_id[B].appointment_canceled is False
