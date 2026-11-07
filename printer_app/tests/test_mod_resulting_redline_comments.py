"""Only explicitly selected manual comments reach their existing PIR boundary."""
import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from types import SimpleNamespace

import pytest

from printer_app.mod_resulting.salesforce_adapter import (
    PRODUCT_RESULT, PR_ISSUED_COUNT, ResultingSalesforceError, ResultingSalesforceRejected,
)
from printer_app.tests.test_mod_resulting_salesforce_mapping import (
    LEAD, WORK, PR1, _adapter, _payload, _schemas, _single,
)

VERSION = '2026-10-27T10:00:00.000+0000'


def _comment_payload(comment, *, interest='Roofing', product='Roofing'):
    payload = _payload(
        interest=interest, notes='Black MOD notes', result_detail='Not Home',
        dnr=True, dnr_reason='Roofing',
    )
    for entry in payload['product_results']:
        entry.pop('comment', None)
        if entry['product'] == product:
            entry['comment'] = comment
    return payload


def _existing(comment, **values):
    row = dict(Id=PR1, Product_Interest__c='Roofing', Comment__c=comment,
               LastModifiedDate=VERSION)
    row.update(values)
    return row


def _queries(calls, object_name):
    return [command[command.index('--query') + 1] for command in calls
            if command[1:3] == ['data', 'query']
            and ' FROM ' + object_name + ' ' in command[command.index('--query') + 1]]


def _comment_field(schemas):
    return next(field for field in schemas[PRODUCT_RESULT]['fields']
                if field['name'] == 'Comment__c')


def test_new_result_receives_only_explicit_manual_text_on_selected_product():
    adapter, calls = _adapter()
    payload = _comment_payload('Manager called customer', interest='Roofing;Siding')
    plan = adapter.prepare([payload])[0]
    products = {values['Product_Interest__c']: values
                for action, obj, ident, values in plan if obj == PRODUCT_RESULT}
    assert products['Roofing']['Comment__c'] == 'Manager called customer'
    assert products['Siding']['Comment__c'] is None
    assert _single(plan, 'WorkOrder')[3]['MOD_Notes__c'] == 'Black MOD notes'
    assert all(text not in products['Roofing']['Comment__c']
               for text in ('Black MOD notes', 'Not Home', 'DNR - Roofing'))
    assert len(_queries(calls, PRODUCT_RESULT)) == 1


def test_existing_result_appends_manual_text_without_replacing_history_or_identity():
    records = [_existing('Historical Salesforce comment')]
    adapter, calls = _adapter(existing_results=records)
    payload = _comment_payload('Manager called customer')
    first = adapter.prepare([payload])[0]
    product = _single(first, PRODUCT_RESULT)
    assert product[:3] == ('update', PRODUCT_RESULT, PR1)
    assert product[4] == {'if_unmodified_since': VERSION}
    combined = 'Historical Salesforce comment\n\nManager called customer'
    assert product[3]['Comment__c'] == combined
    assert len(_queries(calls, PRODUCT_RESULT)) == 1
    assert 'Comment__c' in _queries(calls, PRODUCT_RESULT)[0]
    assert 'LastModifiedDate' in _queries(calls, PRODUCT_RESULT)[0]

    # The previous attempt committed remotely; a new explicit Override reads
    # that same identity and must not append the same manual block again.
    records[0]['Comment__c'] = combined
    second = adapter.prepare([payload])[0]
    again = _single(second, PRODUCT_RESULT)
    assert again[:3] == ('update', PRODUCT_RESULT, PR1)
    assert again[3]['Comment__c'] == combined


@pytest.mark.parametrize('previous', [
    'Manual block',
    'Older history\nManual block\nLater history',
    'Older history\r\nManual block\r\nLater history',
])
def test_complete_existing_line_block_is_already_present(previous):
    adapter, _ = _adapter(existing_results=[_existing(previous)])
    plan = adapter.prepare([_comment_payload('Manual block')])[0]
    assert _single(plan, PRODUCT_RESULT)[3]['Comment__c'] == previous


@pytest.mark.parametrize('previous', [
    'Prefix Manual block suffix', 'Manual block extended', 'MANUAL BLOCK',
])
def test_substrings_and_case_differences_do_not_hide_new_manual_text(previous):
    adapter, _ = _adapter(existing_results=[_existing(previous)])
    plan = adapter.prepare([_comment_payload('Manual block')])[0]
    assert _single(plan, PRODUCT_RESULT)[3]['Comment__c'] == (
        previous + '\n\nManual block')


def test_multiline_comment_is_deduplicated_as_one_contiguous_block():
    manual = 'First line\nSecond line'
    records = [_existing('Older history\n' + manual + '\nLater history')]
    adapter, _ = _adapter(existing_results=records)
    assert _single(adapter.prepare([_comment_payload(manual)])[0],
                   PRODUCT_RESULT)[3]['Comment__c'] == records[0]['Comment__c']
    records[0]['Comment__c'] = 'First line\nDifferent line\nSecond line'
    assert _single(adapter.prepare([_comment_payload(manual)])[0],
                   PRODUCT_RESULT)[3]['Comment__c'] == records[0]['Comment__c'] + '\n\n' + manual


@pytest.mark.parametrize('manual', ['', ' \n\t ', None])
def test_blank_manual_text_neither_reads_nor_changes_existing_comment(manual):
    schemas = _schemas()
    _comment_field(schemas)['updateable'] = False
    adapter, calls = _adapter(existing_results=[{
        'Id': PR1, 'Product_Interest__c': 'Roofing',
    }], schemas=schemas)
    plan = adapter.prepare([_comment_payload(manual)])[0]
    assert 'Comment__c' not in _single(plan, PRODUCT_RESULT)[3]
    assert 'Comment__c' not in _queries(calls, PRODUCT_RESULT)[0]


def test_missing_requested_existing_comment_fails_closed_before_writes():
    adapter, calls = _adapter(existing_results=[{
        'Id': PR1, 'Product_Interest__c': 'Roofing',
    }])
    with pytest.raises(ResultingSalesforceError, match='comment lookup is incomplete'):
        adapter.prepare([_comment_payload('Keep existing history')])
    assert all(command[1:4] != ['api', 'request', 'rest'] for command in calls)


@pytest.mark.parametrize('version', [None, '', '2026-10-27',
                                     '2026-10-27T10:00:00',
                                     '2026-13-27T10:00:00Z', 123])
def test_missing_or_invalid_comment_version_fails_before_writes(version):
    adapter, calls = _adapter(existing_results=[_existing('History', LastModifiedDate=version)])
    with pytest.raises(ResultingSalesforceError, match='comment version'):
        adapter.prepare([_comment_payload('Manual block')])
    assert all(command[1:4] != ['api', 'request', 'rest'] for command in calls)


@pytest.mark.parametrize('metadata,expected', [
    ({'updateable': False}, 'not writable'),
    ({'type': 'boolean'}, 'unexpected type'),
])
def test_existing_comment_write_checks_live_permissions_and_type(metadata, expected):
    schemas = _schemas()
    _comment_field(schemas).update(metadata)
    adapter, calls = _adapter(existing_results=[_existing('Historical')], schemas=schemas)
    with pytest.raises(ResultingSalesforceError, match=expected):
        adapter.prepare([_comment_payload('Manual block')])
    assert all(command[1:4] != ['api', 'request', 'rest'] for command in calls)


def test_new_comment_checks_create_permission():
    schemas = _schemas()
    _comment_field(schemas)['createable'] = False
    adapter, calls = _adapter(schemas=schemas)
    with pytest.raises(ResultingSalesforceError, match='not createable'):
        adapter.prepare([_comment_payload('Manual block')])
    assert all(command[1:4] != ['api', 'request', 'rest'] for command in calls)


def test_already_present_requested_comment_still_requires_write_permission():
    schemas = _schemas()
    _comment_field(schemas)['updateable'] = False
    adapter, calls = _adapter(existing_results=[_existing('Manual block')], schemas=schemas)
    with pytest.raises(ResultingSalesforceError, match='not writable'):
        adapter.prepare([_comment_payload('Manual block')])
    assert all(command[1:4] != ['api', 'request', 'rest'] for command in calls)


def test_merged_comment_uses_actual_utf16_limit_without_truncation():
    schemas = _schemas()
    _comment_field(schemas)['length'] = 9
    records = [_existing('12345')]
    adapter, _ = _adapter(existing_results=records, schemas=schemas)
    payload = _comment_payload('\U0001f600')
    assert _single(adapter.prepare([payload])[0], PRODUCT_RESULT)[3]['Comment__c'] == (
        '12345\n\n\U0001f600')

    schemas = _schemas()
    _comment_field(schemas)['length'] = 8
    adapter, calls = _adapter(existing_results=records, schemas=schemas)
    with pytest.raises(ResultingSalesforceError,
                       match=r'Comment__c.*9 characters; Salesforce allows 8'):
        adapter.prepare([payload])
    assert records[0]['Comment__c'] == '12345'
    assert all(command[1:4] != ['api', 'request', 'rest'] for command in calls)


def test_direct_existing_result_lookup_reads_comments_in_same_query():
    adapter, calls = _adapter(existing_results=[_existing('Historical')])
    found = adapter._existing_product_results(LEAD, WORK, include_comments=True)
    assert found['roofing']['comment'] == 'Historical'
    assert len(_queries(calls, PRODUCT_RESULT)) == 1
    assert 'Comment__c' in _queries(calls, PRODUCT_RESULT)[0]


def test_batch_comment_read_adds_a_field_without_per_work_order_queries():
    other_work = '0WO000000000002AAA'
    other_product = 'a12000000000002AAA'
    adapter, calls = _adapter(existing_results=[
        _existing('First history'),
        {'Id': other_product, 'Product_Interest__c': 'Roofing',
         'Comment__c': 'Other history', 'Work_Order__c': other_work},
    ])
    first = _comment_payload('Manual block')
    second = _comment_payload(None)
    second['work_order_id'] = other_work
    plans = adapter.prepare([first, second])
    assert _single(plans[0], PRODUCT_RESULT)[3]['Comment__c'] == 'First history\n\nManual block'
    assert 'Comment__c' not in _single(plans[1], PRODUCT_RESULT)[3]
    assert len(_queries(calls, PRODUCT_RESULT)) == 1
    assert len([command for command in calls if command[1:3] == ['data', 'query']]) == 3


def test_unselected_old_primary_cleanup_keeps_its_historical_comment_untouched():
    other_product = 'a12000000000002AAA'
    adapter, _ = _adapter(existing_results=[
        _existing('Roofing history'),
        {'Id': other_product, 'Product_Interest__c': 'Windows',
         'Comment__c': 'Unrelated old history', PR_ISSUED_COUNT: True},
    ])
    plan = adapter.prepare([_comment_payload('Manual block')])[0]
    old_primary = next(operation for operation in plan
                       if operation[1] == PRODUCT_RESULT and operation[2] == other_product)
    assert old_primary == ('update', PRODUCT_RESULT, other_product, {PR_ISSUED_COUNT: False})


def test_unselected_cleanup_does_not_require_an_unused_comment_value():
    other_product = 'a12000000000002AAA'
    adapter, calls = _adapter(existing_results=[
        _existing('Roofing history'),
        {'Id': other_product, 'Product_Interest__c': 'Windows', PR_ISSUED_COUNT: True},
    ])
    plan = adapter.prepare([_comment_payload('Manual block')])[0]
    selected = next(operation for operation in plan
                    if operation[1] == PRODUCT_RESULT and operation[2] == PR1)
    assert selected[3]['Comment__c'] == 'Roofing history\n\nManual block'
    old_primary = next(operation for operation in plan
                       if operation[1] == PRODUCT_RESULT and operation[2] == other_product)
    assert old_primary[3] == {PR_ISSUED_COUNT: False}
    assert len(_queries(calls, PRODUCT_RESULT)) == 1


def test_concurrent_comment_change_rejects_atomic_batch_without_overwriting_history():
    adapter, calls = _adapter(existing_results=[_existing('History')])
    payload = _comment_payload('Manual block')
    plan = adapter.prepare([payload])[0]
    query_count = len([command for command in calls if command[1:3] == ['data', 'query']])
    remote = {'comment': 'Another manager added a comment',
              'modified': '2026-10-27T10:00:01+00:00'}
    sent = []

    def conditional_salesforce(command, *, input, **kwargs):
        assert command[1:4] == ['api', 'request', 'rest']
        request = json.loads(input)
        sent.append(request)
        assert request['allOrNone'] is True
        guarded = request['compositeRequest'][0]
        condition = parsedate_to_datetime(guarded['httpHeaders']['If-Unmodified-Since'])
        assert datetime.fromisoformat(remote['modified']) > condition
        result = {'compositeResponse': [{
            'referenceId': step['referenceId'],
            'httpStatusCode': 412 if index == 0 else 400,
            'body': [{'errorCode': 'PRECONDITION_FAILED' if index == 0
                      else 'ALL_OR_NONE_OPERATION_ROLLED_BACK',
                      'message': 'Comment changed after preflight.' if index == 0
                      else 'Atomic request rolled back.'}],
        } for index, step in enumerate(request['compositeRequest'])]}
        return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({
            'status': 0, 'result': {'statusCode': 200, 'body': result},
        }))

    adapter.runner = conditional_salesforce
    with pytest.raises(ResultingSalesforceRejected, match='PRECONDITION_FAILED'):
        adapter.apply(plan)
    assert remote['comment'] == 'Another manager added a comment'
    assert len(sent) == 1
    assert len([command for command in calls if command[1:3] == ['data', 'query']]) == query_count
