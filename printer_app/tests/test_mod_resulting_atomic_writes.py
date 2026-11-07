"""Exercise real Composite transport without any Salesforce network or writes."""
import json
from types import SimpleNamespace

import pytest

from printer_app.mod_resulting.salesforce_adapter import (
    ResultingSalesforceAdapter, ResultingSalesforceError, ResultingSalesforceRejected,
)
from printer_app.mod_resulting.contract import ResultingWriteRejected


def _adapter(*, failing_step=None, malformed=False, http_status=200,
             body_as_text=False, rollback=False, mutate_response=None):
    sent = []

    def run(command, *, input=None, **kwargs):
        sent.append((command, input, kwargs))
        assert command[1:4] == ['api', 'request', 'rest']
        assert '--body' in command and command[command.index('--body') + 1] == '-'
        assert '--values' not in command
        assert '--target-org' in command and 'work' in command
        assert isinstance(input, str)
        request = json.loads(input)
        responses = []
        for index, step in enumerate(request['compositeRequest'], 1):
            rejected = index == failing_step
            rolled_back = rollback and failing_step is not None and not rejected
            responses.append({
                'referenceId': step['referenceId'],
                'httpStatusCode': 400 if rejected or rolled_back else (
                    201 if step['method'] == 'POST' else 204),
                'body': [
                    {'errorCode': ('FIELD_CUSTOM_VALIDATION_EXCEPTION'
                                   if rejected else 'ALL_OR_NONE_OPERATION_ROLLED_BACK'),
                     'message': ('Unsupported Work Order status.'
                                 if rejected else 'Other subrequest rejected.'),
                     'fields': ['Status'] if rejected else []}
                ] if rejected or rolled_back else (
                    {'id': 'a01000000000001AAA'}
                    if step['method'] == 'POST' else None),
            })
        # Match @salesforce/plugin-api's actual --json result schema. The
        # REST HTTP payload is under result.body, never result itself.
        if mutate_response is not None:
            mutate_response(responses)
        body = {} if malformed else {'compositeResponse': responses}
        http_result = {'statusCode': http_status, 'headers': {},
                       'body': json.dumps(body) if body_as_text else body}
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {'status': 0, 'result': http_result}), stderr='')

    adapter = ResultingSalesforceAdapter(runner=run)
    adapter._describes = {
        'ServiceAppointment': {
            'name': 'ServiceAppointment',
            'fields': [
                {'name': 'Status', 'type': 'picklist'},
            ],
        },
        'WorkOrder': {
            'name': 'WorkOrder',
            'fields': [
                {'name': 'Status', 'type': 'picklist'},
                {'name': 'Dispo__c', 'type': 'picklist'},
                {'name': 'MOD_Notes__c', 'type': 'textarea'},
                {'name': 'Price__c', 'type': 'currency'},
                {'name': 'Start_Price__c', 'type': 'currency'},
                {'name': 'X90_Min__c', 'type': 'string'},
                {'name': 'Deposit_Payment__c', 'type': 'string'},
            ],
        },
        'Lead': {'name': 'Lead', 'fields': [
            {'name': 'Status', 'type': 'picklist'},
        ]},
        'Product_Interest_Result__c': {'name': 'Product_Interest_Result__c', 'fields': [
            {'name': 'Product_Interest__c', 'type': 'picklist'},
            {'name': 'Result__c', 'type': 'picklist'},
            {'name': 'Price_Given__c', 'type': 'currency'},
            {'name': 'Lead__c', 'type': 'reference'},
            {'name': 'Work_Order__c', 'type': 'reference'},
        ]},
    }
    return adapter, sent


SA1 = '08p000000000001AAA'
SA2 = '08p000000000002AAA'
WO = '0WO000000000001AAA'
LEAD = '00Q000000000001AAA'
NOTES = 'Buyer said: "I can\'t pay in full."\nSecond line & punctuation.'
PLAN = [
    ('create', 'Product_Interest_Result__c', '', {
        'Product_Interest__c': 'Siding', 'Result__c': 'Sale',
        'Price_Given__c': '69745', 'Lead__c': LEAD, 'Work_Order__c': WO,
    }),
    ('update', 'ServiceAppointment', SA1, {'Status': 'Completed'}),
    ('update', 'ServiceAppointment', SA2, {'Status': 'Completed'}),
    ('update', 'WorkOrder', WO, {'Price__c': '69746'}),
    ('update', 'WorkOrder', WO, {
        'Dispo__c': 'Sale', 'Status': 'Completed',
        'MOD_Notes__c': NOTES, 'Price__c': '69746',
        'Start_Price__c': '77494.50',
        'X90_Min__c': 'Yes', 'Deposit_Payment__c': '23000',
    }),
    ('update', 'Lead', LEAD, {'Status': 'Sale Pending'}),
]


def test_all_or_none_rest_transport_preserves_notes_and_record_order():
    adapter, sent = _adapter()
    assert adapter.apply(PLAN) is None
    assert len(sent) == 1  # One atomic Composite request per Work Order.
    request = json.loads(sent[0][1])
    assert request['allOrNone'] is True
    assert request['collateSubrequests'] is False
    operations = request['compositeRequest']
    assert [entry['method'] for entry in operations] == [
        'POST', 'PATCH', 'PATCH', 'PATCH', 'PATCH', 'PATCH']
    assert [entry['referenceId'] for entry in operations] == [
        'step_1', 'step_2', 'step_3', 'step_4', 'step_5', 'step_6']
    assert operations[0]['body']['Price_Given__c'] == 69745
    assert operations[0]['url'].endswith('/Product_Interest_Result__c')
    assert operations[3]['body'] == {'Price__c': 69746}
    assert operations[4]['body']['MOD_Notes__c'] == NOTES
    assert operations[4]['body']['Price__c'] == 69746
    assert operations[4]['body']['Start_Price__c'] == 77494.5
    assert operations[4]['body']['X90_Min__c'] == 'Yes'
    assert operations[4]['body']['Deposit_Payment__c'] == '23000'
    assert 'input' not in sent[0][2]  # Actual body was stdin only.


def test_rejected_work_order_returns_actual_salesforce_error_and_never_claims_success():
    adapter, sent = _adapter(failing_step=5)
    with pytest.raises(ResultingSalesforceError, match=(
            'WorkOrder update rejected: FIELD_CUSTOM_VALIDATION_EXCEPTION: '
            'Unsupported Work Order status. \\(Status\\)')):
        adapter.apply(PLAN)
    assert len(sent) == 1
    assert json.loads(sent[0][1])['allOrNone'] is True


def test_incomplete_response_never_marks_result_successful():
    adapter, sent = _adapter(malformed=True)
    with pytest.raises(ResultingSalesforceError, match='incomplete response'):
        adapter.apply(PLAN)
    assert len(sent) == 1


def test_preflight_rejects_oversized_or_unknown_operations_without_sending():
    adapter, sent = _adapter()
    with pytest.raises(ResultingSalesforceError, match='between 1 and 25'):
        adapter.apply(PLAN * 6)
    with pytest.raises(ResultingSalesforceError, match='Unknown resulting object'):
        adapter.apply([('update', 'Other', WO, {'Status': 'Completed'})])
    with pytest.raises(ResultingSalesforceError, match='Unknown Salesforce write field'):
        adapter.apply([('update', 'WorkOrder', WO, {'Bad__c': 'x'})])
    assert sent == []


def test_salesforce_error_message_redacts_access_tokens():
    text = ResultingSalesforceAdapter._rest_error([{
        'errorCode': 'INVALID_FIELD',
        'message': 'Bearer secret123 accessToken=secret456',
    }])
    assert 'secret123' not in text and 'secret456' not in text
    assert 'INVALID_FIELD' in text


def test_cli_rest_http_body_can_be_returned_as_json_text():
    adapter, sent = _adapter(body_as_text=True)
    assert adapter.apply(PLAN) is None
    assert len(sent) == 1


def test_cli_http_status_does_not_count_as_success_without_composite_result():
    adapter, sent = _adapter(http_status=503)
    with pytest.raises(ResultingSalesforceError, match='Composite HTTP 503'):
        adapter.apply(PLAN)
    assert len(sent) == 1


def test_all_or_none_reports_root_rejection_not_earlier_rollback():
    adapter, sent = _adapter(failing_step=5, rollback=True)
    with pytest.raises(ResultingSalesforceError, match=(
            'WorkOrder update rejected: FIELD_CUSTOM_VALIDATION_EXCEPTION: '
            'Unsupported Work Order status')):
        adapter.apply(PLAN)
    assert len(sent) == 1


def test_complete_atomic_rejection_is_distinct_from_unknown_write_outcome():
    adapter, sent = _adapter(failing_step=5, rollback=True)
    with pytest.raises(ResultingSalesforceRejected) as caught:
        adapter.apply(PLAN)
    assert isinstance(caught.value, ResultingWriteRejected)
    assert 'WorkOrder update rejected' in str(caught.value)
    assert len(sent) == 1


@pytest.mark.parametrize('mutate', [
    lambda results: results[0].update(httpStatusCode='400'),
    lambda results: results[0].update(httpStatusCode=True),
    lambda results: results[0].update(httpStatusCode=999),
    lambda results: results[0].update(httpStatusCode=302),
    lambda results: results[0].update(referenceId='step_5'),
    lambda results: results[0].update(referenceId=['step_1']),
    lambda results: results.pop(),
])
def test_malformed_or_incomplete_rejection_response_remains_uncertain(mutate):
    adapter, _ = _adapter(failing_step=5, rollback=True, mutate_response=mutate)
    with pytest.raises(ResultingSalesforceError) as caught:
        adapter.apply(PLAN)
    assert not isinstance(caught.value, ResultingWriteRejected)


def test_generic_rollback_without_concrete_rejection_remains_uncertain():
    def generic_errors(results):
        for result in results:
            result['body'] = [{
                'errorCode': 'ALL_OR_NONE_OPERATION_ROLLED_BACK',
                'message': 'Other subrequest rejected.',
            }]

    adapter, _ = _adapter(failing_step=5, rollback=True, mutate_response=generic_errors)
    with pytest.raises(ResultingSalesforceError) as caught:
        adapter.apply(PLAN)
    assert not isinstance(caught.value, ResultingWriteRejected)


@pytest.mark.parametrize('options', [dict(malformed=True), dict(http_status=503)])
def test_transport_or_envelope_failure_is_not_confirmed_rollback(options):
    adapter, _ = _adapter(**options)
    with pytest.raises(ResultingSalesforceError) as caught:
        adapter.apply(PLAN)
    assert not isinstance(caught.value, ResultingWriteRejected)


def test_direct_atomic_write_checks_notes_limit_before_network():
    adapter, sent = _adapter()
    metadata = next(field for field in adapter._describes['WorkOrder']['fields']
                    if field['name'] == 'MOD_Notes__c')
    metadata['length'] = 255
    with pytest.raises(ResultingSalesforceError,
                       match=r'256 characters; Salesforce allows 255'):
        adapter.apply([('update', 'WorkOrder', WO, {'MOD_Notes__c': 'x' * 256})])
    assert sent == []


def _comment_operation(version='2026-10-27T10:00:00.000+0000'):
    return ('update', 'Product_Interest_Result__c', 'a12000000000001AAA',
            {'Comment__c': 'Historical comment\n\nManual block'},
            {'if_unmodified_since': version})


def _comment_transport(**kwargs):
    adapter, sent = _adapter(**kwargs)
    adapter._describes['Product_Interest_Result__c']['fields'].append({
        'name': 'Comment__c', 'type': 'textarea', 'length': 32768,
    })
    return adapter, sent


def test_guarded_comment_transport_adds_conditional_subrequest_header():
    adapter, sent = _comment_transport()
    adapter.apply([_comment_operation()])
    request = json.loads(sent[0][1])['compositeRequest'][0]
    assert request['httpHeaders'] == {
        'If-Unmodified-Since': 'Tue, 27 Oct 2026 10:00:00 GMT',
    }
    assert request['body'] == {'Comment__c': 'Historical comment\n\nManual block'}


def test_fractional_source_version_is_never_rounded_forward():
    adapter, sent = _comment_transport()
    adapter.apply([_comment_operation('2026-10-27T12:00:00.987+0200')])
    request = json.loads(sent[0][1])['compositeRequest'][0]
    assert request['httpHeaders']['If-Unmodified-Since'] == 'Tue, 27 Oct 2026 10:00:00 GMT'


def test_412_condition_failure_is_confirmed_atomic_rejection():
    def condition_failure(results):
        results[0].update(httpStatusCode=412, body=[{
            'errorCode': 'PRECONDITION_FAILED', 'message': 'Record changed since preflight.',
        }])

    adapter, sent = _comment_transport(
        failing_step=1, rollback=True, mutate_response=condition_failure)
    with pytest.raises(ResultingSalesforceRejected, match='PRECONDITION_FAILED'):
        adapter.apply([_comment_operation(), ('update', 'WorkOrder', WO, {'Status': 'Completed'})])
    assert len(sent) == 1
    assert json.loads(sent[0][1])['allOrNone'] is True


@pytest.mark.parametrize('guard', [
    None, {}, {'if_unmodified_since': '2026-10-27T10:00:00'},
    {'if_unmodified_since': '2026-10-27T10:00:00Z', 'extra': 'unsupported'},
])
def test_invalid_comment_condition_cannot_reach_transport(guard):
    adapter, sent = _comment_transport()
    operation = _comment_operation()[:4] + (guard,)
    with pytest.raises(ResultingSalesforceError, match='condition|version'):
        adapter.apply([operation])
    assert sent == []


def test_conditional_metadata_is_restricted_to_existing_product_comment_updates():
    adapter, sent = _comment_transport()
    operation = ('update', 'WorkOrder', WO, {'Status': 'Completed'},
                 {'if_unmodified_since': '2026-10-27T10:00:00Z'})
    with pytest.raises(ResultingSalesforceError, match='condition'):
        adapter.apply([operation])
    assert sent == []


def test_existing_product_comment_cannot_bypass_the_conditional_write_boundary():
    adapter, sent = _comment_transport()
    with pytest.raises(ResultingSalesforceError, match='require a conditional write'):
        adapter.apply([_comment_operation()[:4]])
    assert sent == []
