"""Direct work-order/Lead status lookups must never depend on appointments."""
from dataclasses import FrozenInstanceError
import json
from types import SimpleNamespace

import pytest

from printer_app.mod_sheet_contract import ModSheetSourceError, WorkOrderLeadStatus
from printer_app.salesforce_sandbox.adapter import SalesforceAdapterError, SalesforceCliAdapter
from printer_app.salesforce_sandbox.service import SalesforceSandboxService


WORK_ORDER_OBJECT = 'Field_Work_Order__c'
LEAD_FIELD = 'Linked_Lead__c'
LEAD_ONE = '00Q000000000001AAA'
LEAD_TWO = '00Q000000000002AAA'


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


def _work_order(number='00012345', lead=LEAD_ONE, ident=1):
    return {'Id': f'a01{ident:015d}', 'WorkOrderNumber': number, LEAD_FIELD: lead}


def _page(rows, **extra):
    return {'records': rows, 'done': True, 'totalSize': len(rows), **extra}


class Runner:
    def __init__(self, work_orders=(), leads=(), *, work_order_pages=None, lead_pages=None, metadata=_metadata):
        self.calls = []
        self.work_order_pages = iter(work_order_pages if work_order_pages is not None else [_page(list(work_orders))])
        self.lead_pages = iter(lead_pages if lead_pages is not None else [_page(list(leads))])
        self.metadata = metadata

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        assert command[-3:] == ['--target-org', 'work', '--json']
        if command[1:3] == ['sobject', 'describe']:
            result = self.metadata(command[command.index('--sobject') + 1])
        else:
            assert command[1:3] == ['data', 'query']
            query = command[command.index('--query') + 1]
            assert 'ServiceAppointment' not in query
            assert all(value not in query for value in ('SchedStartTime', 'WorkType', 'Canceled', 'CreatedDate', 'FROM User'))
            if f' FROM {WORK_ORDER_OBJECT} ' in query:
                result = next(self.work_order_pages)
            else:
                assert ' FROM Lead ' in query
                result = next(self.lead_pages)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 0, 'result': result}), stderr='')

    @property
    def queries(self):
        return [command[command.index('--query') + 1] for command in self.calls if '--query' in command]


def test_direct_source_discovers_work_order_and_lead_lookup_without_date_or_appointment_queries():
    runner = Runner(
        work_orders=[_work_order('00012345'), _work_order('00098765', ident=2)],
        leads=[{'Id': LEAD_ONE, 'Status': 'Sold'}],
    )
    actual = SalesforceSandboxService(SalesforceCliAdapter(runner=runner)).lead_statuses(['00012345', '00098765'])
    assert actual == (
        WorkOrderLeadStatus('00012345', LEAD_ONE, 'Sold'),
        WorkOrderLeadStatus('00098765', LEAD_ONE, 'Sold'),
    )
    assert len(runner.queries) == 2
    assert runner.queries[0] == (
        f"SELECT Id, WorkOrderNumber, {LEAD_FIELD} FROM {WORK_ORDER_OBJECT} "
        "WHERE WorkOrderNumber IN ('00012345', '00098765') ORDER BY Id ASC LIMIT 1000"
    )
    assert runner.queries[1] == f"SELECT Id, Status FROM Lead WHERE Id IN ('{LEAD_ONE}') ORDER BY Id ASC LIMIT 1000"
    with pytest.raises(FrozenInstanceError):
        actual[0].sales_lead_status = 'Open'


def test_null_missing_and_ambiguous_work_order_links_never_guess_a_lead():
    runner = Runner(work_orders=[
        _work_order('no-lead', None),
        _work_order('ambiguous', LEAD_ONE, 2),
        _work_order('ambiguous', LEAD_TWO, 3),
        _work_order('null-and-lead', None, 4),
        _work_order('null-and-lead', LEAD_ONE, 5),
    ])
    numbers = ['missing', 'no-lead', 'ambiguous', 'null-and-lead']
    assert SalesforceCliAdapter(runner=runner).lead_statuses(numbers) == tuple(WorkOrderLeadStatus(number) for number in numbers)
    assert len(runner.queries) == 1


@pytest.mark.parametrize('leads', [[], [{'Id': LEAD_ONE, 'Status': None}], [{'Id': LEAD_ONE, 'Status': ''}]])
def test_linked_lead_without_a_readable_status_is_not_given_another_leads_status(leads):
    runner = Runner(work_orders=[_work_order()], leads=leads)
    assert SalesforceCliAdapter(runner=runner).lead_statuses(['00012345']) == (
        WorkOrderLeadStatus('00012345', LEAD_ONE, ''),
    )


def test_work_order_batches_share_one_current_status_for_each_lead():
    numbers = [f'{index:08d}' for index in range(250)]
    pages = [_page([_work_order(number, ident=index + 1) for index, number in enumerate(numbers[offset:offset + 100], offset)])
             for offset in range(0, len(numbers), 100)]
    runner = Runner(work_order_pages=pages, leads=[{'Id': LEAD_ONE, 'Status': 'Sold'}])
    actual = SalesforceCliAdapter(runner=runner).lead_statuses(numbers)
    assert actual == tuple(WorkOrderLeadStatus(number, LEAD_ONE, 'Sold') for number in numbers)
    work_queries = [query for query in runner.queries if f'FROM {WORK_ORDER_OBJECT}' in query]
    assert len(work_queries) == 3
    assert all(query.count("'") <= 200 for query in work_queries)
    assert len([query for query in runner.queries if 'FROM Lead ' in query]) == 1


def test_lead_queries_are_also_bounded_and_distinct():
    numbers = [f'{index:08d}' for index in range(101)]
    ids = [f'00Q{index:015d}' for index in range(101)]
    runner = Runner(
        work_order_pages=[_page([_work_order(numbers[i], ids[i], i + 1) for i in range(100)]),
                          _page([_work_order(numbers[100], ids[100], 101)])],
        lead_pages=[_page([{'Id': lead, 'Status': 'Sold'} for lead in ids[:100]]),
                    _page([{'Id': ids[100], 'Status': 'Open'}])],
    )
    actual = SalesforceCliAdapter(runner=runner).lead_statuses(numbers)
    assert len(actual) == 101
    assert actual[-1] == WorkOrderLeadStatus(numbers[-1], ids[-1], 'Open')
    lead_queries = [query for query in runner.queries if 'FROM Lead ' in query]
    assert len(lead_queries) == 2
    assert all(query.count("'") <= 200 for query in lead_queries)


def test_short_incomplete_pages_are_followed_for_work_orders_and_leads():
    runner = Runner(
        work_order_pages=[_page([_work_order()], done=False, totalSize=2),
                          _page([_work_order('00054321', LEAD_TWO, 2)])],
        lead_pages=[_page([{'Id': LEAD_ONE, 'Status': 'Sold'}], done=False, totalSize=2),
                    _page([{'Id': LEAD_TWO, 'Status': 'Open'}])],
    )
    assert SalesforceCliAdapter(runner=runner).lead_statuses(['00012345', '00054321']) == (
        WorkOrderLeadStatus('00012345', LEAD_ONE, 'Sold'),
        WorkOrderLeadStatus('00054321', LEAD_TWO, 'Open'),
    )
    assert "AND Id > 'a01000000000000001'" in runner.queries[1]
    assert f"AND Id > '{LEAD_ONE}'" in runner.queries[3]


def test_full_limit_page_is_followed_even_when_that_query_is_done():
    first = [_work_order(ident=index + 1) for index in range(1000)]
    runner = Runner(work_order_pages=[_page(first), _page([_work_order(ident=1001)])],
                    leads=[{'Id': LEAD_ONE, 'Status': 'Sold'}])
    assert SalesforceCliAdapter(runner=runner).lead_statuses(['00012345'])[0].sales_lead_status == 'Sold'
    assert "AND Id > 'a01000000000001000'" in runner.queries[1]


@pytest.mark.parametrize('page', [
    {}, {'records': 'bad'}, _page([], done=False), _page([], totalSize=1),
    _page([{'Id': 'invalid', 'WorkOrderNumber': '00012345', LEAD_FIELD: LEAD_ONE}]),
    _page([_work_order(), _work_order()]),
    _page([_work_order('unexpected')]),
    _page([{'Id': 'a01000000000000001', 'WorkOrderNumber': '00012345'}]),
    _page([_work_order(lead='bad-lead-id')]),
])
def test_invalid_work_order_response_is_failure_not_successful_missing_data(page):
    runner = Runner(work_order_pages=[page])
    with pytest.raises(ModSheetSourceError):
        SalesforceSandboxService(SalesforceCliAdapter(runner=runner)).lead_statuses(['00012345'])


def test_repeated_page_is_rejected_instead_of_returning_partial_results():
    runner = Runner(work_order_pages=[_page([_work_order()], done=False), _page([_work_order()])])
    with pytest.raises(SalesforceAdapterError, match='pagination did not advance'):
        SalesforceCliAdapter(runner=runner).lead_statuses(['00012345'])


@pytest.mark.parametrize('lead', [
    {'Id': LEAD_TWO, 'Status': 'Sold'}, {'Id': LEAD_ONE}, {'Id': LEAD_ONE, 'Status': {'bad': True}},
])
def test_unexpected_lead_data_fails_the_entire_lookup(lead):
    runner = Runner(work_orders=[_work_order()], leads=[lead])
    with pytest.raises(ModSheetSourceError):
        SalesforceSandboxService(SalesforceCliAdapter(runner=runner)).lead_statuses(['00012345'])


def test_service_normalizes_cli_failure_without_returning_a_partial_lookup():
    runner = Runner(work_orders=[_work_order()], lead_pages=[OSError('connection refused')])
    with pytest.raises(ModSheetSourceError, match='connection refused'):
        SalesforceSandboxService(SalesforceCliAdapter(runner=runner)).lead_statuses(['00012345'])


def test_number_escaping_and_deduplication_preserve_leading_zeros():
    number = "00012'\\45"
    runner = Runner(work_orders=[_work_order(number)], leads=[{'Id': LEAD_ONE, 'Status': 'Sold'}])
    assert SalesforceCliAdapter(runner=runner).lead_statuses([None, '', '   ', number, f' {number} ']) == (
        WorkOrderLeadStatus(number, LEAD_ONE, 'Sold'),
    )
    assert "WorkOrderNumber IN ('00012\\'\\\\45')" in runner.queries[0]


@pytest.mark.parametrize('numbers', ['12345', [12345], ['1\n2345'], ['x' * 256]])
def test_invalid_number_inputs_cannot_become_queries(numbers):
    runner = Runner()
    with pytest.raises(SalesforceAdapterError):
        SalesforceCliAdapter(runner=runner).lead_statuses(numbers)
    assert runner.calls == []


def test_empty_numbers_do_not_fetch_metadata_or_data():
    runner = Runner()
    assert SalesforceCliAdapter(runner=runner).lead_statuses([]) == ()
    assert runner.calls == []


@pytest.mark.parametrize('change', [
    lambda value: value.update(name='WrongObject'),
    lambda value: value.update(queryable=False),
    lambda value: value['fields'][-1].update(referenceTo=['Lead', 'Contact']),
    lambda value: value['fields'][-1].update(relationshipName='OtherLead__r'),
    lambda value: value['fields'][-1].update(name='bad name'),
    lambda value: value['fields'][1].update(filterable=False),
    lambda value: value['fields'].append(_field('OtherLead__c', 'reference', referenceTo=['Lead'], relationshipName='Lead__r')),
])
def test_missing_or_ambiguous_metadata_does_not_guess_a_work_order_or_lead_link(change):
    def metadata(name):
        value = _metadata(name)
        if name == WORK_ORDER_OBJECT:
            change(value)
        return value
    runner = Runner(metadata=metadata)
    with pytest.raises(SalesforceAdapterError):
        SalesforceCliAdapter(runner=runner).lead_statuses(['00012345'])
    assert runner.queries == []


def test_polymorphic_appointment_link_is_not_guessed():
    def metadata(name):
        value = _metadata(name)
        value['fields'][-1]['referenceTo'].append('OtherWorkOrder__c')
        return value
    runner = Runner(metadata=metadata)
    with pytest.raises(SalesforceAdapterError, match='work-order link is unavailable or ambiguous'):
        SalesforceCliAdapter(runner=runner).lead_statuses(['00012345'])
    assert len(runner.calls) == 1


def test_describe_cache_expires_but_statuses_are_never_cached(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('printer_app.salesforce_sandbox.adapter.monotonic', lambda: clock[0])
    runner = Runner(work_order_pages=[_page([_work_order()])] * 3,
                    lead_pages=[_page([{'Id': LEAD_ONE, 'Status': status}]) for status in ('Open', 'Sold', 'Sold')])
    adapter = SalesforceCliAdapter(runner=runner)
    assert adapter.lead_statuses(['00012345'])[0].sales_lead_status == 'Open'
    assert adapter.lead_statuses(['00012345'])[0].sales_lead_status == 'Sold'
    assert len([call for call in runner.calls if 'describe' in call]) == 2
    clock[0] += 601
    assert adapter.lead_statuses(['00012345'])[0].sales_lead_status == 'Sold'
    assert len([call for call in runner.calls if 'describe' in call]) == 4
