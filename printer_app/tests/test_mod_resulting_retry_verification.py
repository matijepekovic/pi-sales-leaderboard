"""Uncertain attempts require complete reads before another write is allowed."""
from copy import deepcopy

import pytest

from printer_app.mod_resulting.salesforce_adapter import ResultingSalesforceError
from printer_app.tests.test_mod_resulting_salesforce_mapping import (
    WORK, LEAD, PR1, PRODUCT_RESULT, _adapter, _payload,
)


def _verification(*, created=False, changed=False, missing=False, original_create=False,
                  canceled=False, changed_attribution=False, moved_appointment=False,
                  changed_product=False):
    adapter, _ = _adapter(existing_results=[] if original_create else [{
        'Id': PR1, 'Product_Interest__c': 'Roofing',
    }])
    payload = _payload('pns', interest='Roofing', notes='Call back', numbers='100')
    plan = adapter.prepare([payload])[0]
    rows = {}
    for action, object_name, ident, values in plan:
        if action == 'create':
            ident = PR1
        rows.setdefault(object_name, {}).setdefault(ident, {'Id': ident}).update(values)
    rows[PRODUCT_RESULT][PR1].update({
        'Product_Interest__c': 'Roofing', 'Lead__c': LEAD, 'Work_Order__c': WORK,
    })
    for item in rows['ServiceAppointment'].values():
        item['ParentRecordId'] = '0WO000000000099AAA' if moved_appointment else WORK
    rows['WorkOrder'][WORK]['Lead__c'] = LEAD
    rows['WorkOrder'][WORK]['Start_Price__c'] = 100.0
    if changed:
        rows['WorkOrder'][WORK]['MOD_Notes__c'] = 'Changed on Salesforce'
    if created:
        plan.insert(0, ('create', PRODUCT_RESULT, '', {
            'Comment__c': None, 'Lead__c': LEAD, 'Work_Order__c': WORK,
            'Product_Interest__c': 'Bath',
        }))
    if changed_product:
        rows[PRODUCT_RESULT][PR1]['Product_Interest__c'] = 'Windows'
    if canceled:
        for item in rows['ServiceAppointment'].values():
            item['Status'] = 'Canceled'
    if changed_attribution:
        rows[PRODUCT_RESULT][PR1]['Original_Disposition__c'] = 'No Pitch'
    if missing:
        del rows['WorkOrder'][WORK]['MOD_Notes__c']
    reads = []
    adapter.prepare = lambda batch: [deepcopy(plan)]

    def query(statement):
        reads.append(statement)
        object_name = statement.split(' FROM ', 1)[1].split(' ', 1)[0]
        return list(deepcopy(rows[object_name]).values())

    adapter._query = query
    return adapter, payload, reads, plan


def test_already_committed_attempt_is_recognized_by_fresh_complete_reads():
    adapter, payload, reads, plan = _verification()
    assert adapter.reconcile_submission(payload, verification=plan) == 'submitted'
    assert reads and any(' FROM Product_Interest_Result__c ' in query for query in reads)


@pytest.mark.parametrize('changes', [{'changed': True}, {'created': True}])
def test_changed_or_missing_result_is_ready_for_corrective_update_after_verification(changes):
    adapter, payload, reads, plan = _verification(**changes)
    assert adapter.reconcile_submission(payload, verification=plan) == 'ready'
    assert reads


def test_incomplete_verification_never_permits_a_blind_retry():
    adapter, payload, _, plan = _verification(missing=True)
    with pytest.raises(ResultingSalesforceError, match='incomplete'):
        adapter.reconcile_submission(payload, verification=plan)


def test_changed_lead_cannot_be_silently_overwritten_on_retry():
    adapter, payload, _, plan = _verification()
    payload = dict(payload, lead_id='00Q000000000099AAA')
    with pytest.raises(ResultingSalesforceError, match='Lead changed|identity'):
        adapter.reconcile_submission(payload, verification=plan)


def test_legacy_attempt_without_frozen_plan_cannot_be_declared_completed():
    adapter, payload, reads, _ = _verification()
    assert adapter.reconcile_submission(payload) == 'ready'
    assert reads


def test_original_appointment_ids_are_verified_even_after_they_leave_eligibility():
    adapter, payload, reads, plan = _verification(canceled=True)
    assert adapter.reconcile_submission(payload, verification=plan) == 'ready'
    assert any(' FROM ServiceAppointment ' in query for query in reads)


def test_prior_created_product_is_found_and_verified_without_recreating_it():
    adapter, payload, _, plan = _verification(original_create=True)
    assert adapter.reconcile_submission(payload, verification=plan) == 'submitted'


def test_creation_only_fields_cannot_disappear_from_receipt_verification():
    adapter, payload, _, plan = _verification(original_create=True, changed_attribution=True)
    assert adapter.reconcile_submission(payload, verification=plan) == 'ready'


def test_reparented_appointment_cannot_recover_an_unrelated_work_order_receipt():
    adapter, payload, _, plan = _verification(moved_appointment=True)
    with pytest.raises(ResultingSalesforceError, match='identity changed'):
        adapter.reconcile_submission(payload, verification=plan)


def test_changed_product_cannot_recover_the_requested_products_receipt():
    adapter, payload, _, plan = _verification(changed_product=True)
    assert adapter.reconcile_submission(payload, verification=plan) == 'ready'
