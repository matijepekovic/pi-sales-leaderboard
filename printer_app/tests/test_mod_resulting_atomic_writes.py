"""Exercise real Composite transport without any Salesforce network or writes."""
import json
from types import SimpleNamespace

import pytest

from printer_app.mod_resulting.salesforce_adapter import (
    ResultingSalesforceAdapter, ResultingSalesforceError,
)


def _adapter(*, failing_step=None, malformed=False):
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
            responses.append({
                'referenceId': step['referenceId'],
                'httpStatusCode': 400 if rejected else 201 if step['method'] == 'POST' else 204,
                'body': [
                    {'errorCode': 'FIELD_CUSTOM_VALIDATION_EXCEPTION',
                     'message': 'Unsupported Work Order status.',
                     'fields': ['Status']}
                ] if rejected else {'id': 'a01000000000001AAA'} if step['method'] == 'POST' else None,
            })
        body = {} if malformed else {'compositeResponse': responses}
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {'status': 0, 'result': body}), stderr='')

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
    ('update', 'ServiceAppointment', SA1, {'Status': 'Completed'}),
    ('update', 'ServiceAppointment', SA2, {'Status': 'Completed'}),
    ('update', 'WorkOrder', WO, {
        'Dispo__c': 'Sale', 'Status': 'Completed',
        'MOD_Notes__c': NOTES, 'Price__c': '69746',
        'Start_Price__c': '77494.50',
        'X90_Min__c': 'Yes', 'Deposit_Payment__c': '23000',
    }),
    ('update', 'Lead', LEAD, {'Status': 'Sale Pending'}),
    ('create', 'Product_Interest_Result__c', '', {
        'Product_Interest__c': 'Siding', 'Result__c': 'Sale',
        'Price_Given__c': '69745',
        'Lead__c': LEAD, 'Work_Order__c': WO,
    }),
]


def test_all_or_none_rest_transport_preserves_notes_and_record_order():
    adapter, sent = _adapter()
    assert adapter.apply(PLAN) is None
    assert len(sent) == 1  # Not five separate CLI processes.
    request = json.loads(sent[0][1])
    assert request['allOrNone'] is True
    assert request['collateSubrequests'] is False
    operations = request['compositeRequest']
    assert [entry['method'] for entry in operations] == [
        'PATCH', 'PATCH', 'PATCH', 'PATCH', 'POST']
    assert [entry['referenceId'] for entry in operations] == [
        'step_1', 'step_2', 'step_3', 'step_4', 'step_5']
    assert operations[2]['body']['MOD_Notes__c'] == NOTES
    assert operations[2]['body']['Price__c'] == 69746
    assert operations[2]['body']['Start_Price__c'] == 77494.5
    assert operations[2]['body']['X90_Min__c'] == 'Yes'
    assert operations[2]['body']['Deposit_Payment__c'] == '23000'
    assert operations[4]['body']['Price_Given__c'] == 69745
    assert operations[4]['url'].endswith('/Product_Interest_Result__c')
    assert 'input' not in sent[0][2]  # Actual body was stdin only.


def test_rejected_work_order_returns_actual_salesforce_error_and_never_claims_success():
    adapter, sent = _adapter(failing_step=3)
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
