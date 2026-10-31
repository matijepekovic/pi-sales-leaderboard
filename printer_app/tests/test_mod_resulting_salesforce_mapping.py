"""The user-supplied MOD -> Salesforce contract, exercised without live writes."""
from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
import json
import re

import pytest

from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft, outcome_fields
from printer_app.mod_resulting.service import ResultingService
from printer_app.mod_resulting.salesforce_adapter import (
    ResultingSalesforceAdapter, ResultingSalesforceError, WO, SA, LEAD_FIELDS, PR,
    PRODUCT_RESULT, REVIEW_FIELD, PR_ISSUED_COUNT, PR_APPOINTMENT_DATE,
)

DAY = '2026-10-27'
WORK = '0WO000000000001AAA'
LEAD = '00Q000000000001AAA'
MOD = '005000000000001AAA'
SA1 = '08p000000000001AAA'
SA2 = '08p000000000002AAA'
PR1 = 'a12000000000001AAA'


def _field(name, kind='string', values=(), *, refs=(), update=True, create=True):
    result = {
        'name': name, 'label': name, 'type': kind,
        'updateable': update, 'createable': create,
    }
    if values:
        result['picklistValues'] = [{'value':v,'label':v,'active':True} for v in values]
    if refs:
        result['referenceTo'] = list(refs)
    return result


def _schemas():
    wo = [
        _field('Dispo__c','picklist',['Sale','PNS','No Pitch','CXL','NRA','OOS']),
        _field('Status','picklist',['Completed','Canceled']),
        _field('Lead__c','reference',refs=['Lead']),
        _field('Appointment_Date_Time__c','datetime'),
        _field('Appointment_Date__c','date'),
        _field('MOD__c','reference',refs=['User']),
        _field('MOD_Notes__c','textarea'),
        _field('Call_1__c','time'), _field('Call_2__c','time'),
        _field('Docs__c','boolean'), _field('X90_Min__c','boolean'),
        _field('Promotion__c','boolean'),
        _field('Start_Price__c','currency'), _field('Price__c','currency'),
        _field('Deposit_Payment__c','string'),
        _field('Need__c','textarea'), _field('Want__c','textarea'),
        # Review is now an opt-in checked-only write; the other ghost fields
        # remain excluded even when their UI checkboxes are selected.
        *[_field(name,'boolean') for name in (
            'Review__c','Pictures__c','Power_Questions__c',
            'T_Close__c','Bid_Sheet_Submitted__c',
        )],
    ]
    lead = [
        _field('Status','picklist',[
            'Sale Pending','Nurturing','Canceled','Out of Scope','Do Not Call',
        ]),
        _field('Previous_Result__c','picklist',[
            'Pitch No Sale','No Pitch','No Rep Available',
        ]),
        _field('DNR_Do_Not_Reset__c','boolean'),
        _field('DNR_Reason__c','multipicklist',['Roofing','Bath','Windows']),
        _field('X1_Leg_Appointment__c','boolean'),
        _field('Product_Interest_lead__c','multipicklist',[
            'Roofing','Siding','Windows','Bath','Doors',
        ]),
        _field('Appointment_Time__c','time'),
        _field('Approved_By_Supervisor__c','reference',refs=['User']),
        _field('Canvass_Set_By__c','reference',refs=['User']),
        _field('Confirmed_By__c','reference',refs=['User']),
        _field('LeadSource','picklist',['Salesforce Import']),
        _field('Reset_By__c','reference',refs=['User']),
        _field('Set_By__c','reference',refs=['User']),
        _field('Sub_Source__c','string'),
    ]
    sa = [
        _field('Status','picklist',[
            'Completed','Canceled','No Rep Available',
        ]),
        _field('FSSK__FSK_Work_Order__c','reference',refs=['WorkOrder']),
        _field('ParentRecordId','reference',refs=['WorkOrder']),
    ]
    product = [
        _field('Lead__c','reference',refs=['Lead']),
        _field('Work_Order__c','reference',refs=['WorkOrder']),
        _field('Product_Interest__c','picklist',[
            'Roofing','Siding','Windows','Bath','Doors',
        ]),
        _field('Result__c','picklist',[
            'Sale','Pitch No Sale','No Pitch','Canceled','No Rep Available',
        ]),
        _field('Result_Detail__c','picklist',['Price Objection','Not Home']),
        _field('Price_Given__c','currency'),
        _field('PR_1_Leg_Appointment__c','boolean'),
        _field('Free_Product_Lead__c','boolean'),
        _field('CXL_Per_Redline__c','boolean'),
        _field('Include_in_Issued_Lead_Count__c','boolean'),
        _field('PR_Appointment_Date__c','date'),
        _field('Comment__c','textarea'),
        _field('Original_Disposition__c','string'),
        _field('PR_Set_By__c','reference',refs=['User']),
        _field('PR_Appointment_Time__c','time'),
        _field('PR_Approved_By_Supervisor__c','reference',refs=['User']),
        _field('PR_Canvass_Set_By__c','reference',refs=['User']),
        _field('PR_Confirmed_By__c','reference',refs=['User']),
        _field('PR_Lead_Source__c','picklist',['Salesforce Import']),
        _field('PR_Reset_By__c','reference',refs=['User']),
        _field('PR_Sub_Source__c','string'),
    ]
    return {
        'WorkOrder':{'name':'WorkOrder','fields':wo},
        'Lead':{'name':'Lead','fields':lead},
        'ServiceAppointment':{'name':'ServiceAppointment','fields':sa},
        'Product_Interest_Result__c':{'name':'Product_Interest_Result__c','fields':product},
    }


def _adapter(*, existing_results=(), lead_interest='Roofing;Siding', schemas=None,
             history=None):
    schemas = schemas or _schemas()
    calls = []
    # The current Work Order is unresulted on Salesforce at preflight.
    # Historical candidates are separate records with the same Lead__c.
    historical_works = list(history) if history is not None else [
        {'Id':WORK, 'Lead__c':LEAD,
         'Appointment_Date_Time__c':'2026-10-27T19:00:00Z',
         'Appointment_Date__c':'2026-10-27', 'Dispo__c':None},
        # The second same-lead Work Order is available to batch tests, but
        # cannot be a previous result unless its disposition is actually set.
        {'Id':'0WO000000000002AAA', 'Lead__c':LEAD,
         'Appointment_Date_Time__c':'2026-10-27T20:00:00Z',
         'Appointment_Date__c':'2026-10-27', 'Dispo__c':None},
    ]

    def runner(command, **kwargs):
        calls.append(command)
        if command[1:3] == ['sobject','describe']:
            result = schemas[command[command.index('--sobject')+1]]
        elif command[1:3] == ['data','query']:
            query = command[command.index('--query')+1]
            if ' FROM trac_killswitch__c ' in query:
                result = {'records': [
                    {'SetupOwnerId': '00D000000000001AAA', 'trac_flows__c': False},
                ], 'done': True}
            elif ' FROM ServiceAppointment ' in query:
                assert 'ParentRecordId IN (' in query
                assert "Status IN ('Scheduled','Dispatched')" in query
                work_ids = re.findall(r"'(0WO[A-Za-z0-9]{15})'", query)
                records = []
                for offset, work_order in enumerate(work_ids):
                    for n in (1, 2):
                        records.append({
                            'Id': '08p' + str(offset * 2 + n).zfill(12) + 'AAA',
                            'ParentRecordId': work_order,
                        })
                result = {'records':records, 'done':True}
            elif ' FROM WorkOrder ' in query:
                assert 'WHERE Lead__c IN (' in query
                assert 'Appointment_Date_Time__c' in query
                result = {'records':historical_works, 'done':True}
            elif ' FROM Product_Interest_Result__c ' in query:
                result = {'records':[dict(item,
                    Work_Order__c=item.get('Work_Order__c', WORK),
                    Lead__c=item.get('Lead__c', LEAD))
                    for item in existing_results], 'done':True}
            elif ' FROM Lead ' in query:
                result = {'records':[{
                    'Id': LEAD, 'Product_Interest_lead__c': lead_interest,
                    'Appointment_Date__c': '2026-10-27',
                    'Appointment_Time__c': '11:00:00.000Z',
                    'Approved_By_Supervisor__c': MOD,
                    'Canvass_Set_By__c': MOD,
                    'Confirmed_By__c': MOD,
                    'LeadSource': 'Salesforce Import',
                    'Reset_By__c': MOD,
                    'Set_By__c': MOD,
                    'Sub_Source__c': 'Direct',
                }], 'done':True}
            else:
                raise AssertionError('Unexpected query: '+query)
        else:
            raise AssertionError('No live writes are permitted during adapter preflight.')
        return SimpleNamespace(
            stdout=json.dumps({'status':0,'result':result}),
            stderr='',returncode=0,
        )

    adapter=ResultingSalesforceAdapter(runner=runner)
    return adapter,calls


def _payload(dispo='pns', interest='Roofing;Siding', **draft):
    source=ModSheetRecord(
        source_id=WORK,lead_source_id=LEAD,
        work_order_number='00012345',product_interest=interest,
        work_type='Sales - Roofing',
    )
    values=clean_draft(dict(draft,dispo=dispo))
    return ResultingService.submission_payload({
        'day':DAY,'work_order_id':WORK,
        'snapshot':asdict(source),'draft':values,
    },MOD,lead_appointment_date=DAY)


def _operations(adapter,payload):
    return adapter.prepare([payload])[0]


def _single(plan,name):
    matches=[row for row in plan if row[1]==name]
    if name == 'WorkOrder' and len(matches) == 2:
        # Flow v30 writes Price__c first, and the other WO fields second.
        assert matches[0][3].keys() == {'Price__c'}
        matches = [matches[1]]
    assert len(matches)==1, (name,matches)
    return matches[0]


def _work_order_price(plan):
    matches = [row for row in plan if row[1] == 'WorkOrder'
               and set(row[3]) == {'Price__c'}]
    assert len(matches) == 1, matches
    return matches[0][3]['Price__c']


def _assert_no_protected_fields(plan):
    forbidden={
        'Pictures__c','Power_Questions__c','T_Close__c',
        'Bid_Sheet_Submitted__c',
    }
    for op,obj,ident,values in plan:
        assert not set(values).intersection(forbidden), (obj,values)
    # Every updated field is in the declared API mapping for that object.
    allowed={
        'WorkOrder':set(WO.values()) | {REVIEW_FIELD},
        'Lead':set(LEAD_FIELDS.values()),
        'ServiceAppointment':{SA['status']},
        'Product_Interest_Result__c':set(PR.values()) |
            {PR_ISSUED_COUNT, PR_APPOINTMENT_DATE,
             'Comment__c', 'Original_Disposition__c',
             'PR_Appointment_Time__c', 'PR_Approved_By_Supervisor__c',
             'PR_Canvass_Set_By__c', 'PR_Confirmed_By__c',
             'PR_Lead_Source__c', 'PR_Reset_By__c',
             'PR_Set_By__c', 'PR_Sub_Source__c'},
    }
    for op,obj,ident,values in plan:
        assert set(values).issubset(allowed[obj]), (obj,values)


@pytest.mark.parametrize('review,redlines',[
    (False,''),(True,''),(False,'REDLINE: scope changed'),(True,'REDLINE: scope changed'),
])
def test_ghost_fields_and_comment_are_never_written(review,redlines):
    adapter,calls=_adapter()
    payload=_payload(
        'pns',review=review,redlines=redlines,notes='Black note',
        pictures=True,power_questions=True,t_close=True,
        bid_sheets=True,docs=True,promotion=True,ninety_min=True,
        one_leg=True,free_lead=True,
        dnr=True,dnr_reason='Roofing;Windows',
        need='Need',want='Want',call_1='10:15 AM',call_2='1:27 PM',
    )
    plan=_operations(adapter,payload)
    _assert_no_protected_fields(plan)
    wo=_single(plan,'WorkOrder')[3]
    assert wo['Dispo__c']=='PNS' and wo['Status']=='Completed'
    assert wo['MOD__c']==MOD
    assert wo['MOD_Notes__c']=='Black note' + (
        '\n'+redlines if redlines else ''
    )+'\nDNR - Roofing; Windows'
    assert wo['Call_1__c']=='10:15:00.000Z'
    assert wo['Call_2__c']=='13:27:00.000Z'
    assert wo['Docs__c'] is True and wo['Promotion__c'] is True
    assert wo['X90_Min__c'] is True
    if review:
        assert wo['Review__c'] is True
    else:
        assert 'Review__c' not in wo
    assert wo['Need__c']=='Need' and wo['Want__c']=='Want'
    lead=_single(plan,'Lead')[3]
    assert lead['Status']=='Do Not Call'  # Checked DNR forces Do Not Call.
    assert lead['Previous_Result__c'] is None
    assert lead['DNR_Do_Not_Reset__c'] is True
    assert lead['DNR_Reason__c']=='Roofing;Windows'
    assert lead['X1_Leg_Appointment__c'] is True
    results=[row for row in plan if row[1]==PRODUCT_RESULT]
    assert len(results)==2
    for action,obj,ident,fields in results:
        assert fields['Result__c']=='Pitch No Sale'
        assert fields['PR_1_Leg_Appointment__c'] is True
        assert fields['Free_Product_Lead__c'] is True
        assert fields['CXL_Per_Redline__c'] is False
        assert 'Price_Given__c' not in fields
    assert all(fields.get('PR_Appointment_Time__c') == '11:00:00.000Z'
               for action, obj, ident, fields in results if action == 'create')
    expected_creation = {
        'PR_Appointment_Time__c': '11:00:00.000Z',
        'PR_Approved_By_Supervisor__c': MOD,
        'PR_Canvass_Set_By__c': MOD,
        'PR_Confirmed_By__c': MOD,
        'PR_Lead_Source__c': 'Salesforce Import',
        'PR_Reset_By__c': MOD,
        'PR_Set_By__c': MOD,
        'PR_Sub_Source__c': 'Direct',
        'Original_Disposition__c': 'Pitch No Sale',
        'Comment__c': None,
    }
    for action, obj, ident, fields in results:
        if action == 'create':
            assert {key: fields[key] for key in expected_creation} == expected_creation
    appointments=[row for row in plan if row[1]=='ServiceAppointment']
    assert {row[2] for row in appointments}=={SA1,SA2}
    assert all(row[3]=={'Status':'Completed'} for row in appointments)


def test_checked_training_flags_send_yes_and_unchecked_flags_do_not_overwrite():
    adapter,_ = _adapter()
    off = _single(_operations(adapter, _payload('pns')), 'WorkOrder')[3]
    assert all(field not in off for field in ('Docs__c','X90_Min__c','Review__c'))

    yes = _single(_operations(adapter, _payload(
        'pns',docs=True,ninety_min=True,review=True
    )), 'WorkOrder')[3]
    assert yes['Docs__c'] is True
    assert yes['X90_Min__c'] is True
    assert yes['Review__c'] is True

    # Salesforce metadata determines whether a checked Yes is stored as a
    # boolean or a literal/picklist value, never an invented value.
    schemas = _schemas()
    for row in schemas['WorkOrder']['fields']:
        if row['name'] in ('Docs__c','X90_Min__c','Review__c'):
            row['type'] = 'string'
    adapter,_ = _adapter(schemas=schemas)
    text_yes = _single(_operations(adapter, _payload(
        'pns',docs=True,ninety_min=True,review=True
    )), 'WorkOrder')[3]
    assert {key:text_yes[key] for key in ('Docs__c','X90_Min__c','Review__c')} == {
        'Docs__c':'Yes','X90_Min__c':'Yes','Review__c':'Yes',
    }


def test_checkbox_metadata_is_normalized_and_uses_salesforce_field_types():
    schemas = _schemas()
    for field in schemas['WorkOrder']['fields']:
        if field['name'] == 'Docs__c':
            field['type'] = 'string'
            field['length'] = 120
        elif field['name'] == 'X90_Min__c':
            field['type'] = 'picklist'
            field['picklistValues'] = [
                {'value': 'No', 'label': 'No', 'active': True},
                {'value': 'Completed', 'label': 'Completed', 'active': True},
            ]
    adapter, _ = _adapter(schemas=schemas)
    info = adapter.checkbox_fields()
    assert info['docs']['kind'] == 'string'
    assert info['docs']['length'] == 120
    assert info['ninety_min']['kind'] == 'picklist'
    assert [option['value'] for option in info['ninety_min']['choices']] == ['No', 'Completed']
    assert info['promotion']['kind'] == 'boolean'
    assert info['dnr']['kind'] == 'boolean'
    assert 'Docs__c' not in str(info)
    assert 'WorkOrder' not in str(info)


def test_override_preserves_raw_checkbox_values_until_explicit_edit():
    schemas = _schemas()
    for field in schemas['WorkOrder']['fields']:
        if field['name'] == 'Docs__c':
            field['type'] = 'string'
            field['length'] = 100
        elif field['name'] == 'X90_Min__c':
            field['type'] = 'picklist'
            field['picklistValues'] = [
                {'value': 'No', 'label': 'No', 'active': True},
                {'value': 'Scheduled', 'label': 'Scheduled', 'active': True},
            ]
    adapter, _ = _adapter(schemas=schemas)
    original = {
        'docs': {'value': 'Already Completed', 'edited': False},
        'ninety_min': {'value': 'No', 'edited': False},
        'promotion': {'value': True, 'edited': False},
        'dnr': {'value': False, 'edited': False},
        'one_leg': {'value': True, 'edited': False},
    }
    # End of Day still writes the resulting workflow; only an intentionally
    # edited checkbox is included in the Work Order/Lead patch.
    untouched = _operations(adapter, _payload('pns',
        checkbox_values=original,
        docs=True, ninety_min=False, promotion=True, dnr=False, one_leg=True
    ))
    work = _single(untouched, 'WorkOrder')[3]
    lead = _single(untouched, 'Lead')[3]
    assert 'Docs__c' not in work
    assert 'X90_Min__c' not in work
    assert 'Promotion__c' not in work
    assert 'DNR_Do_Not_Reset__c' not in lead
    assert 'X1_Leg_Appointment__c' not in lead
    assert 'Dispo__c' in work

    edited = {
        **original,
        'docs': {'value': 'Supervisor Signed', 'edited': True},
        'ninety_min': {'value': 'Scheduled', 'edited': True},
        'promotion': {'value': False, 'edited': True},
        'one_leg': {'value': False, 'edited': True},
    }
    operations = _operations(adapter, _payload('pns', checkbox_values=edited))
    work = _single(operations, 'WorkOrder')[3]
    lead = _single(operations, 'Lead')[3]
    assert work['Docs__c'] == 'Supervisor Signed'
    assert work['X90_Min__c'] == 'Scheduled'
    assert work['Promotion__c'] is False
    assert lead['X1_Leg_Appointment__c'] is False

    # An explicit checkbox uncheck can clear a nullable text field.
    cleared = {
        **original,
        'docs': {'value': False, 'edited': True},
    }
    work = _single(_operations(adapter, _payload('pns', checkbox_values=cleared)),
                   'WorkOrder')[3]
    assert work['Docs__c'] is None

    invalid = {**original, 'ninety_min': {'value': 'Not a choice', 'edited': True}}
    with pytest.raises(ResultingSalesforceError, match='does not allow'):
        _operations(adapter, _payload('pns', checkbox_values=invalid))
    invalid = {**original, 'promotion': {'value': 'Yes', 'edited': True}}
    with pytest.raises(ResultingSalesforceError, match='True or False'):
        _operations(adapter, _payload('pns', checkbox_values=invalid))
    invalid = {**original, 'docs': {'value': 'x' * 101, 'edited': True}}
    with pytest.raises(ResultingSalesforceError, match='limit'):
        _operations(adapter, _payload('pns', checkbox_values=invalid))


def test_promotion_text_or_picklist_uses_the_actual_value_when_edited():
    schemas = _schemas()
    for field in schemas['WorkOrder']['fields']:
        if field['name'] == 'Promotion__c':
            field['type'] = 'picklist'
            field['picklistValues'] = [
                {'value': 'Not Started', 'label': 'Not Started', 'active': True},
                {'value': 'Approved', 'label': 'Approved', 'active': True},
            ]
    adapter, _ = _adapter(schemas=schemas)

    saved = {'promotion': {'value':'Not Started', 'edited':False}}
    unedited = _single(_operations(adapter, _payload(
        'pns', checkbox_values=saved, promotion=True)), 'WorkOrder')[3]
    assert 'Promotion__c' not in unedited

    changed = {'promotion': {'value':'Approved', 'edited':True}}
    result = _single(_operations(adapter, _payload(
        'pns', checkbox_values=changed, promotion=True)), 'WorkOrder')[3]
    assert result['Promotion__c'] == 'Approved'
    with pytest.raises(ResultingSalesforceError, match='does not allow'):
        _operations(adapter, _payload('pns', checkbox_values={
            'promotion': {'value': 'Yes', 'edited': True},
        }))

    # Legacy drafts can still check Promotion if the picklist actually has
    # "Yes". A blank checkbox must never be guessed into the text "False".
    unchecked = _single(_operations(adapter, _payload(
        'pns', promotion=False)), 'WorkOrder')[3]
    assert 'Promotion__c' not in unchecked


def test_review_raw_value_is_viewable_and_untouched_override_does_not_replace_it():
    schemas = _schemas()
    for field in schemas['WorkOrder']['fields']:
        if field['name'] == REVIEW_FIELD:
            field['type'] = 'string'
            field['length'] = 140
    adapter, _ = _adapter(schemas=schemas)
    assert adapter.checkbox_fields()['review']['kind'] == 'string'
    original = {'review': {'value': 'Supervisor Approved', 'edited': False}}
    work = _single(_operations(adapter, _payload('pns',
        checkbox_values=original, review=True)), 'WorkOrder')[3]
    assert REVIEW_FIELD not in work

    changed = {'review': {'value': 'Complete', 'edited': True}}
    work = _single(_operations(adapter, _payload('pns',
        checkbox_values=changed, review=True)), 'WorkOrder')[3]
    assert work[REVIEW_FIELD] == 'Complete'

    cleared = {'review': {'value': None, 'edited': True}}
    work = _single(_operations(adapter, _payload('pns',
        checkbox_values=cleared, review=False)), 'WorkOrder')[3]
    assert work[REVIEW_FIELD] is None


def test_override_retains_individual_product_checkbox_values_until_user_changes_them():
    adapter, _ = _adapter(existing_results=[{
        'Id': PR1, 'Product_Interest__c': 'Roofing',
    }])
    flags = {
        'one_leg': {'value': True, 'edited': False},
        'free_lead': {'value': 'True / False', 'edited': False},
        'cxl_at_lead': {'value': False, 'edited': False},
    }
    plan = _operations(adapter, _payload(
        'pns', checkbox_values=flags, one_leg=True, free_lead=True,
        cxl_at_lead=False
    ))
    existing = next(row[3] for row in plan if row[1] == PRODUCT_RESULT
                    and row[0] == 'update')
    added = next(row[3] for row in plan if row[1] == PRODUCT_RESULT
                 and row[0] == 'create')
    assert all(key not in existing for key in (
        PR['one_leg'], PR['free_lead'], PR['cxl_at_lead']
    ))
    assert added[PR['one_leg']] is True
    assert added[PR['free_lead']] is True
    assert added[PR['cxl_at_lead']] is False

    changed = {**flags, 'free_lead': {'value': False, 'edited': True}}
    plan = _operations(adapter, _payload(
        'pns', checkbox_values=changed, one_leg=True, free_lead=False
    ))
    existing = next(row[3] for row in plan if row[1] == PRODUCT_RESULT
                    and row[0] == 'update')
    assert existing[PR['free_lead']] is False
    assert PR['one_leg'] not in existing
    assert PR['cxl_at_lead'] not in existing


def test_legacy_manual_choices_cannot_override_automatic_status_or_history():
    draft = clean_draft({
        'dispo':'pns','numbers':'25000\n17000',
        'start_price_override':'27000',
        'final_price_override':'16000',
        'deposit_override':'2500',
        'lead_status':'Do Not Call',
        'previous_result':'No Pitch',
        'dnr':True,'dnr_reason':'Roofing',
    })
    fields=outcome_fields(draft)
    assert fields['lead_status']=='Do Not Call'
    assert fields['price']=={'highest':'27000','lowest':'16000'}
    adapter,_=_adapter()
    plan=_operations(adapter,_payload('pns',**{
        key:value for key,value in draft.items() if key!='dispo'
    }))
    lead=_single(plan,'Lead')[3]
    wo=_single(plan,'WorkOrder')[3]
    assert lead['Status']=='Do Not Call' and lead['Previous_Result__c'] is None
    assert wo['Start_Price__c']=='27000'
    assert _work_order_price(plan)=='16000'
    assert wo['Price__c']=='16000'
    assert wo['Deposit_Payment__c']=='2500'
    # Old local manual fields remain backward-compatible draft inputs, but
    # cannot replace a lookup of the previous Salesforce Work Order.
    overridden=_operations(adapter,_payload(
        'pns', lead_status='Sale Pending', previous_result='No Pitch'))
    assert _single(overridden,'Lead')[3]['Status']=='Nurturing'
    assert _single(overridden,'Lead')[3]['Previous_Result__c'] is None


@pytest.mark.parametrize('previous_dispo,expected', [
    ('PNS','Pitch No Sale'), ('No Pitch','No Pitch'),
    ('NRA','No Rep Available'), ('Sale',None),
    ('CXL',None), ('OOS',None),
])
def test_previous_result_comes_only_from_latest_older_work_order(previous_dispo,expected):
    history = [
        {'Id':WORK, 'Lead__c':LEAD,
         'Appointment_Date_Time__c':'2026-10-27T19:00:00Z',
         'Appointment_Date__c':'2026-10-27', 'Dispo__c':None},
        {'Id':'0WO000000000002AAA', 'Lead__c':LEAD,
         'Appointment_Date_Time__c':'2026-10-26T19:00:00Z',
         'Appointment_Date__c':'2026-10-26', 'Dispo__c':previous_dispo},
        {'Id':'0WO000000000003AAA', 'Lead__c':LEAD,
         'Appointment_Date_Time__c':'2026-10-20T19:00:00Z',
         'Appointment_Date__c':'2026-10-20', 'Dispo__c':'PNS'},
    ]
    adapter,_=_adapter(history=history)
    lead=_single(_operations(adapter,_payload(
        'nra',previous_result='Pitch No Sale',lead_status='Sale Pending'
    )), 'Lead')[3]
    assert lead['Previous_Result__c']==expected
    assert lead['Status']=='Nurturing'


def test_previous_result_preflight_rejects_required_field_if_blank():
    schemas=_schemas()
    for field in schemas['Lead']['fields']:
        if field['name']=='Previous_Result__c':
            field['nillable']=False
    adapter,_=_adapter(schemas=schemas)
    with pytest.raises(ResultingSalesforceError,match='required and cannot be blank'):
        _operations(adapter,_payload('pns'))


def test_independent_final_price_override_writes_without_start_price():
    adapter,_=_adapter()
    plan=_operations(adapter,_payload('pns',final_price_override='15500'))
    wo=_single(plan,'WorkOrder')[3]
    assert 'Start_Price__c' not in wo
    assert wo['Price__c']=='15500'
    assert _work_order_price(plan)=='15500'


@pytest.mark.parametrize('dispo', ['sale','pns','np','cxl','nra','oos'])
def test_dnr_forces_do_not_call_regardless_of_dispo_or_manual_override(dispo):
    kwargs = {
        'dnr':True, 'dnr_reason':'Roofing',
        'lead_status':'Nurturing',
    }
    if dispo == 'sale':
        kwargs['sale_products'] = {'Roofing':{'price':'17000','deposit':'0'}}
    payload = _payload(dispo, **kwargs)
    assert payload['fields']['lead_status'] == 'Do Not Call'
    adapter,_ = _adapter()
    lead = _single(_operations(adapter, payload), 'Lead')[3]
    assert lead['Status'] == 'Do Not Call'
    assert lead['DNR_Do_Not_Reset__c'] is True
    assert lead['DNR_Reason__c'] == 'Roofing'
    assert payload['draft']['lead_status'] == 'Nurturing'


def test_review_write_refuses_missing_sf_api_field_and_off_does_not_require_it():
    schemas=_schemas()
    schemas['WorkOrder']['fields']=[
        row for row in schemas['WorkOrder']['fields'] if row['name']!='Review__c'
    ]
    adapter,_=_adapter(schemas=schemas)
    assert 'Review__c' not in _single(
        _operations(adapter,_payload('pns',review=False)), 'WorkOrder'
    )[3]
    with pytest.raises(ResultingSalesforceError,match='Review__c'):
        _operations(adapter,_payload('pns',review=True))


@pytest.mark.parametrize('dispo,lead_status,wo_status,sa_status,pr_result,previous',[
    ('sale','Sale Pending','Completed','Completed','Sale',None),
    ('pns','Nurturing','Completed','Completed','Pitch No Sale',None),
    ('np','Nurturing','Completed','Completed','No Pitch',None),
    ('cxl','Canceled','Canceled','Canceled','Canceled',None),
    ('nra','Nurturing','Completed','No Rep Available','No Rep Available',None),
    ('oos','Out of Scope','Canceled','Canceled','Canceled',None),
])
def test_main_disposition_governs_all_three_statuses(
    dispo,lead_status,wo_status,sa_status,pr_result,previous
):
    kwargs={'sale_products':{'Roofing':{'price':'20000','deposit':'0'}}} if dispo=='sale' else {}
    payload=_payload(dispo,**kwargs)
    adapter,_=_adapter()
    plan=_operations(adapter,payload)
    assert _single(plan,'WorkOrder')[3]['Status']==wo_status
    assert _single(plan,'Lead')[3]['Status']==lead_status
    lead=_single(plan,'Lead')[3]
    assert lead.get('Previous_Result__c')==previous
    assert all(row[3]=={'Status':sa_status}
               for row in plan if row[1]=='ServiceAppointment')
    assert all(row[3]['Result__c']==pr_result
               for row in plan if row[1]==PRODUCT_RESULT)
    _assert_no_protected_fields(plan)


def test_main_sale_uses_separate_product_prices_deposits_and_preserves_lead_interests():
    payload=_payload('sale',numbers='25000\n17000',notes='Black note',
        redlines='Extra scope',
        sale_products={
            'Roofing':{'price':'17000','deposit':'0'},
            'Windows':{'price':'22000','deposit':'5000'},
            'Bath':{'price':'0','deposit':'500'},
        })
    adapter,_=_adapter()
    plan=_operations(adapter,payload)
    wo=_single(plan,'WorkOrder')[3]
    assert wo['Dispo__c']=='Sale'
    assert wo['Start_Price__c']=='25000'
    assert _work_order_price(plan)=='17000'
    assert wo['Price__c']=='17000'
    assert wo['Deposit_Payment__c']=='5000/'
    assert 'SALE Roofing: $17,000 | Deposit: $0' in wo['MOD_Notes__c']
    assert 'SALE Windows: $22,000 | Deposit: $5,000' in wo['MOD_Notes__c']
    assert 'SALE Bath:' not in wo['MOD_Notes__c']
    lead=_single(plan,'Lead')[3]
    assert lead['Status']=='Sale Pending'
    assert lead['Product_Interest_lead__c']=='Roofing;Siding;Windows'
    pr=[row[3] for row in plan if row[1]==PRODUCT_RESULT]
    assert {item['Product_Interest__c']:item['Price_Given__c'] for item in pr}=={
        'Roofing':'17000','Windows':'22000',
    }
    assert {item['Product_Interest__c'] for item in pr}=={'Roofing','Windows'}
    assert all(item['Result__c']=='Sale' for item in pr)
    _assert_no_protected_fields(plan)


def test_individual_product_results_do_not_change_main_work_order_dispo():
    payload=_payload('pns',additional_products=True,
        product_results={
            'Roofing':{'result':'np','detail':'Not Home'},
        })
    adapter,_=_adapter()
    plan=_operations(adapter,payload)
    assert _single(plan,'WorkOrder')[3]['Dispo__c']=='PNS'
    results=[row[3] for row in plan if row[1]==PRODUCT_RESULT]
    mapping={item['Product_Interest__c']:item['Result__c'] for item in results}
    assert mapping=={'Roofing':'No Pitch','Siding':'Pitch No Sale'}


def test_individual_sale_price_deposit_does_not_change_work_order_dispo():
    payload=_payload('pns',additional_products=True,
        product_results={
            'Roofing':{'result':'sale','detail':'','price':'14500','deposit':'0'},
        })
    adapter,_=_adapter()
    plan=_operations(adapter,payload)
    wo=_single(plan,'WorkOrder')[3]
    assert wo['Dispo__c']=='PNS'
    assert wo['Deposit_Payment__c']=='0/'
    assert 'SALE Roofing: $14,500 | Deposit: $0' in wo['MOD_Notes__c']
    results=[row[3] for row in plan if row[1]==PRODUCT_RESULT]
    assert {item['Product_Interest__c']:item['Result__c'] for item in results}=={
        'Roofing':'Sale','Siding':'Pitch No Sale',
    }
    assert next(item for item in results if item['Product_Interest__c']=='Roofing')['Price_Given__c']=='14500'


@pytest.mark.parametrize('dispo', ['pns', 'np', 'cxl', 'nra', 'oos'])
def test_existing_product_result_uses_correct_identity_and_clears_non_sale_price(dispo):
    adapter,_=_adapter(existing_results=[{
        'Id':PR1,'Product_Interest__c':'Roofing',
    }])
    plan=_operations(adapter,_payload(dispo,interest='Roofing'))
    result=_single(plan,PRODUCT_RESULT)
    assert result[0]=='update' and result[2]==PR1
    assert result[3]['Price_Given__c'] is None
    assert not {'Lead__c','Work_Order__c','Product_Interest__c'}.intersection(result[3])
    _assert_no_protected_fields(plan)


def test_old_duplicate_product_identity_is_rejected():
    adapter,_=_adapter(existing_results=[
        {'Id':PR1,'Product_Interest__c':'Roofing'},
        {'Id':'a12000000000002AAA','Product_Interest__c':'Roofing'},
    ])
    with pytest.raises(ResultingSalesforceError,match='ambiguous'):
        _operations(adapter,_payload('pns'))


def test_mismatched_api_field_never_falls_back_to_a_guessed_label():
    schemas=_schemas()
    schemas['WorkOrder']['fields']=[
        item for item in schemas['WorkOrder']['fields']
        if item['name']!='Dispo__c'
    ]
    schemas['WorkOrder']['fields'].append(_field('Dispo_Guessed__c','string'))
    adapter,_=_adapter(schemas=schemas)
    with pytest.raises(ResultingSalesforceError, match='WorkOrder.Dispo__c'):
        _operations(adapter,_payload('pns'))


def test_dnr_forces_do_not_call_and_keeps_reason_multiselect():
    draft=clean_draft({
        'dispo':'nra','dnr':True,'dnr_reason':'Roofing;Bath;Roofing',
    })
    assert draft['dnr_reason']=='Roofing;Bath'
    assert outcome_fields(draft)['lead_status']=='Do Not Call'
    assert outcome_fields(draft)['work_order_status']=='Completed'
    adapter,_=_adapter()
    plan=_operations(adapter,_payload('nra',dnr=True,dnr_reason='Roofing;Bath'))
    lead=_single(plan,'Lead')[3]
    assert lead['DNR_Do_Not_Reset__c'] is True
    assert lead['DNR_Reason__c']=='Roofing;Bath'
    assert lead['Status']=='Do Not Call'


def test_synthetic_runner_never_allows_live_salesforce_writes():
    adapter,calls=_adapter()
    _operations(adapter,_payload('pns'))
    assert calls and all(command[1:3] in (
        ['data','query'],['sobject','describe']
    ) for command in calls)


def test_sales_with_only_zero_priced_selections_produces_no_product_writes():
    payload=_payload('sale',sale_products={
        'Roofing':{'price':'0','deposit':'100'},
    })
    adapter,_=_adapter()
    plan=_operations(adapter,payload)
    assert [row for row in plan if row[1]==PRODUCT_RESULT]==[]
    assert _single(plan,'WorkOrder')[3]['Dispo__c']=='Sale'
    assert 'Deposit_Payment__c' not in _single(plan,'WorkOrder')[3]
    assert 'Product_Interest_lead__c' not in _single(plan,'Lead')[3]
    assert 'SALE Roofing' not in _single(plan,'WorkOrder')[3]['MOD_Notes__c']


def test_two_sales_to_same_lead_accumulate_both_pivots_without_overwriting():
    first=_payload('sale',interest='Roofing',sale_products={
        'Windows':{'price':'18000','deposit':'0'},
    })
    second=_payload('sale',interest='Siding',sale_products={
        'Doors':{'price':'12000','deposit':'0'},
    })
    second['work_order_id']='0WO000000000002AAA'
    adapter,_=_adapter()
    first_plan,second_plan=adapter.prepare([first,second])
    first_lead=_single(first_plan,'Lead')[3]
    second_lead=_single(second_plan,'Lead')[3]
    assert first_lead['Product_Interest_lead__c']=='Roofing;Siding;Windows'
    assert second_lead['Product_Interest_lead__c']=='Roofing;Siding;Windows;Doors'


def test_all_adapter_api_names_are_exactly_the_supplied_mapping():
    assert WO == {
        'dispo':'Dispo__c','status':'Status','mod':'MOD__c',
        'notes':'MOD_Notes__c','call_1':'Call_1__c','call_2':'Call_2__c',
        'docs':'Docs__c','ninety_min':'X90_Min__c',
        'promotion':'Promotion__c','start_price':'Start_Price__c',
        'final_price':'Price__c','deposit':'Deposit_Payment__c',
        'need':'Need__c','want':'Want__c',
    }
    assert LEAD_FIELDS == {
        'status':'Status','previous_result':'Previous_Result__c',
        'dnr':'DNR_Do_Not_Reset__c','dnr_reason':'DNR_Reason__c',
        'one_leg':'X1_Leg_Appointment__c',
        'product_interest':'Product_Interest_lead__c',
    }
    assert SA == {
        'status':'Status','work_order':'FSSK__FSK_Work_Order__c',
    }
    assert PR == {
        'lead':'Lead__c','work_order':'Work_Order__c',
        'product':'Product_Interest__c','result':'Result__c',
        'detail':'Result_Detail__c','price':'Price_Given__c',
        'one_leg':'PR_1_Leg_Appointment__c',
        'free_lead':'Free_Product_Lead__c',
        'cxl_at_lead':'CXL_Per_Redline__c',
    }
    assert PRODUCT_RESULT == 'Product_Interest_Result__c'


def test_financing_payment_goes_to_work_order_and_notes_preserving_review():
    payload=_payload('sale',review=True,sale_products={
        'Roofing':{'price':'17000','deposit':'0','payment':'159.50'},
    })
    adapter,_=_adapter()
    plan=_operations(adapter,payload)
    wo=_single(plan,'WorkOrder')[3]
    assert wo['Dispo__c']=='Sale'
    assert wo['Review__c'] is True
    assert wo['Deposit_Payment__c']=='0/159.50'
    assert 'SALE Roofing: $17,000 | Deposit: $0 | Payment: $159.50' in wo['MOD_Notes__c']
    assert {field for field in wo if 'Payment' in field} == {
        'Deposit_Payment__c',
    }
    product=_single(plan,'Product_Interest_Result__c')[3]
    assert product['Price_Given__c']=='17000'
    assert all('Payment' not in field for field in product)
    _assert_no_protected_fields(plan)


def test_manual_slash_deposit_payment_uses_existing_text_field():
    adapter,_ = _adapter()
    payload = _payload('sale', deposit_override='1,250/159.50', sale_products={
        'Roofing': {'price':'18000', 'deposit':'100', 'payment':'200'},
    })
    wo = _single(_operations(adapter, payload), 'WorkOrder')[3]
    assert wo['Deposit_Payment__c'] == '1250/159.50'
    assert 'Review__c' not in wo


def test_numeric_salesforce_deposit_field_is_rejected_before_any_write():
    schemas = _schemas()
    for field in schemas['WorkOrder']['fields']:
        if field['name'] == 'Deposit_Payment__c':
            field['type'] = 'currency'
    adapter,calls = _adapter(schemas=schemas)
    with pytest.raises(ResultingSalesforceError, match='Deposit_Payment__c has unexpected type'):
        _operations(adapter, _payload('sale', sale_products={
            'Roofing': {'price':'18000', 'deposit':'0', 'payment':'159'},
        }))
    assert all(command[1:3] != ['data', 'update'] for command in calls)


def test_flow_v30_kill_switch_blocks_batch_before_any_write():
    adapter,calls = _adapter()
    original=adapter._query
    adapter._query=lambda soql,**kwargs: (
        [{'SetupOwnerId':'00D000000000001AAA','trac_flows__c':True}]
        if ' FROM trac_killswitch__c ' in soql else original(soql,**kwargs))
    with pytest.raises(ResultingSalesforceError,match='kill switch is enabled'):
        adapter.prepare([_payload('pns',interest='Roofing')])
    assert all(command[1:3] not in (['data','update'],['data','create'])
               for command in calls)

    adapter._query=lambda soql,**kwargs: (
        [] if ' FROM trac_killswitch__c ' in soql else original(soql,**kwargs))
    with pytest.raises(ResultingSalesforceError,match='could not be verified'):
        adapter.prepare([_payload('pns',interest='Roofing')])


def test_flow_v30_write_order_and_salesforce_service_appointment_filter():
    adapter,calls = _adapter()
    plan = _operations(adapter, _payload(
        'sale', numbers='77494\\n69746',
        sale_products={'Siding': {'price':'69745','deposit':'23000'}},
    ))
    stages = [(action, object_name) for action, object_name, _, _ in plan]
    assert stages == [
        ('create', PRODUCT_RESULT), ('update', 'ServiceAppointment'),
        ('update', 'ServiceAppointment'), ('update', 'WorkOrder'),
        ('update', 'WorkOrder'), ('update', 'Lead'),
    ]
    assert _work_order_price(plan) == '69746'
    assert _single(plan, 'WorkOrder')[3]['Price__c']=='69746'
    queries = [cmd[cmd.index('--query')+1] for cmd in calls
               if cmd[1:3] == ['data','query'] and '--query' in cmd]
    sa_query = next(q for q in queries if ' FROM ServiceAppointment ' in q)
    assert 'ParentRecordId IN (' in sa_query
    assert "Status IN ('Scheduled','Dispatched')" in sa_query
    assert 'SchedStartTime >=' in sa_query and 'SchedStartTime <' in sa_query


def test_pns_without_prior_product_result_creates_pir_before_work_order():
    adapter,_=_adapter()
    plan=_operations(adapter,_payload('pns',interest='Roofing'))
    assert plan[0][0:2] == ('create', PRODUCT_RESULT)
    assert plan[0][3]['Result__c'] == 'Pitch No Sale'
    assert all(op[1]=='ServiceAppointment' for op in plan[1:3])
    assert [op[1] for op in plan[3:]] == ['WorkOrder','Lead']
    assert 'Price__c' not in _single(plan,'WorkOrder')[3]


def test_existing_product_result_is_updated_before_service_appointments():
    adapter,_ = _adapter(existing_results=[{
        'Id':PR1, 'Product_Interest__c':'Roofing',
        PR_ISSUED_COUNT:True, PR_APPOINTMENT_DATE:DAY,
    }])
    plan=_operations(adapter,_payload('pns',interest='Roofing'))
    assert plan[0][0:3] == ('update',PRODUCT_RESULT,PR1)
    assert plan[1][1] == 'ServiceAppointment'
    assert [row[1] for row in plan][-2:] == ['WorkOrder','Lead']


def test_phase2_salesforce_date_reader_batches_authoritative_lead_dates_only():
    adapter, calls = _adapter()
    assert adapter.lead_appointment_dates([LEAD]) == {LEAD:'2026-10-27'}
    queries = [command[command.index('--query') + 1] for command in calls
               if command[1:3] == ['data', 'query']]
    assert len(queries) == 1
    assert 'SELECT Id,Appointment_Date__c FROM Lead WHERE Id IN (' in queries[0]
    assert 'WorkOrder' not in queries[0]
    assert not any(command[1:3] == ['data', 'record'] for command in calls)

    with pytest.raises(ResultingSalesforceError, match='record identity'):
        adapter.lead_appointment_dates(['invalid-id'])
    original = adapter._query
    adapter._query = lambda query: ([] if 'Appointment_Date__c' in query else
                                    original(query))
    with pytest.raises(ResultingSalesforceError, match='unavailable'):
        adapter.lead_appointment_dates([LEAD])


def test_phase3_sales_pivot_marks_only_sold_primary_and_clears_old_issued_flag():
    adapter, calls = _adapter(existing_results=[{
        'Id': PR1, 'Product_Interest__c': 'Roofing',
        PR_ISSUED_COUNT: True, PR_APPOINTMENT_DATE: DAY,
    }])
    payload = _payload('sale', sale_products={
        'Siding': {'price':'18000','deposit':'0'},
        'Roofing': {'price':'0','deposit':''},
    }, sale_selection_order=['Siding','Roofing'])
    plan = _operations(adapter, payload)
    pir = [item for item in plan if item[1] == PRODUCT_RESULT]
    assert len(pir) == 2
    created = next(item for item in pir if item[0] == 'create')
    cleared = next(item for item in pir if item[0] == 'update')
    assert created[3]['Product_Interest__c'] == 'Siding'
    assert created[3]['Result__c'] == 'Sale'
    assert created[3]['Price_Given__c'] == '18000'
    assert created[3][PR_ISSUED_COUNT] is True
    assert created[3][PR_APPOINTMENT_DATE] == DAY
    assert cleared[2] == PR1
    assert cleared[3] == {PR_ISSUED_COUNT:False}
    assert not any(item[3].get('Result__c') == 'Pitch No Sale' for item in pir)
    assert any('Product_Interest__c,' + PR_ISSUED_COUNT in
               command[command.index('--query')+1] for command in calls
               if command[1:3] == ['data','query'] and
               '--query' in command)


def test_phase3_result_together_uses_work_type_and_additional_flags_are_false():
    source = ModSheetRecord(
        source_id=WORK, lead_source_id=LEAD, work_order_number='00012345',
        product_interest='Roofing;Gutters', work_type='Sales - Gutters',
    )
    draft = clean_draft({'dispo':'pns'})
    payload = ResultingService.submission_payload({
        'day':DAY,'work_order_id':WORK,
        'snapshot':asdict(source),'draft':draft,
    }, MOD, lead_appointment_date=DAY)
    assert payload['product_result_context']['Gutters']['role'] == 'primary'
    assert payload['product_result_context']['Roofing']['role'] == 'additional'
    adapter,_ = _adapter()
    schemas = _schemas()
    product = next(field for field in schemas[PRODUCT_RESULT]['fields']
                   if field['name'] == 'Product_Interest__c')
    product['picklistValues'].append(
        {'value':'Gutters','label':'Gutters','active':True})
    adapter,_ = _adapter(schemas=schemas)
    ops = [item for item in _operations(adapter,payload)
           if item[1] == PRODUCT_RESULT]
    flags = {item[3]['Product_Interest__c']:item[3][PR_ISSUED_COUNT]
             for item in ops}
    assert flags == {'Roofing':False,'Gutters':True}
    assert all(item[3][PR_APPOINTMENT_DATE] == DAY for item in ops)


def test_phase3_existing_future_date_is_copied_and_missing_input_blocks_write():
    source = ModSheetRecord(
        source_id=WORK, lead_source_id=LEAD, work_order_number='00012345',
        product_interest='Roofing', work_type='Sales - Roofing',
    )
    payload = ResultingService.submission_payload({
        'day':DAY,'work_order_id':WORK,
        'snapshot':asdict(source),'draft':clean_draft({'dispo':'pns'}),
    }, MOD, lead_appointment_date='2026-10-30', resulted_on=DAY)
    assert payload['product_result_context']['Roofing']['appointment_date_source'] == (
        'existing_result_input')
    adapter,_ = _adapter(existing_results=[{
        'Id':PR1,'Product_Interest__c':'Roofing',
        PR_ISSUED_COUNT:True,PR_APPOINTMENT_DATE:'2026-10-26',
    }])
    existing = _single(_operations(adapter,payload), PRODUCT_RESULT)
    assert existing[3][PR_APPOINTMENT_DATE] == '2026-10-26'
    adapter,calls = _adapter()
    with pytest.raises(ResultingSalesforceError, match='appointment date is unavailable'):
        _operations(adapter,payload)
    assert all(command[1:3] not in (['data','update'],['data','create'])
               for command in calls)


def test_future_primary_new_result_uses_saved_sa_date_and_existing_keeps_pir_date():
    source=ModSheetRecord(
        source_id=WORK, lead_source_id=LEAD,
        work_order_number='00012345', product_interest='Roofing',
        work_type='Sales - Roofing',
    )
    payload=ResultingService.submission_payload({
        'day':DAY, 'work_order_id':WORK, 'snapshot':asdict(source),
        'draft':clean_draft({'dispo':'pns'}),
    }, MOD, lead_appointment_date='2026-10-30',
       work_order_appointment_date='2026-10-29', resulted_on=DAY)
    context=payload['product_result_context']['Roofing']
    assert context['appointment_date_source']=='existing_result_input'
    assert context['fallback_appointment_date']=='2026-10-29'
    adapter,_=_adapter()
    created=_single(_operations(adapter,payload),PRODUCT_RESULT)
    assert created[0]=='create'
    assert created[3][PR_APPOINTMENT_DATE]=='2026-10-29'
    adapter,_=_adapter(existing_results=[{
        'Id':PR1, 'Product_Interest__c':'Roofing',
        PR_ISSUED_COUNT:True, PR_APPOINTMENT_DATE:'2026-10-26',
    }])
    existing=_single(_operations(adapter,payload),PRODUCT_RESULT)
    assert existing[0]=='update'
    assert existing[3][PR_APPOINTMENT_DATE]=='2026-10-26'
    adapter,_=_adapter(existing_results=[{
        'Id':PR1, 'Product_Interest__c':'Roofing',
        PR_ISSUED_COUNT:True, PR_APPOINTMENT_DATE:None,
    }])
    legacy=_single(_operations(adapter,payload),PRODUCT_RESULT)
    assert legacy[0]=='update'
    assert legacy[3][PR_APPOINTMENT_DATE]=='2026-10-29'


def test_phase3_missing_flow_metadata_rejects_batch_before_writes():
    schema = _schemas()
    schema[PRODUCT_RESULT]['fields'] = [
        field for field in schema[PRODUCT_RESULT]['fields']
        if field['name'] != PR_ISSUED_COUNT
    ]
    adapter,calls = _adapter(schemas=schema)
    with pytest.raises(ResultingSalesforceError, match=PR_ISSUED_COUNT):
        _operations(adapter,_payload('pns'))
    assert all(command[1:3] not in (['data','update'],['data','create'])
               for command in calls)


def test_20_work_order_preflight_batches_related_salesforce_reads():
    """Preflight must not issue one query per Work Order or per Lead."""
    work_ids = ['0WO' + str(index).zfill(12) + 'AAA' for index in range(1, 21)]
    history = [
        {'Id': work_id, 'Lead__c': LEAD, 'Dispo__c': None,
         'Appointment_Date_Time__c': f'2026-10-27T{index - 1:02d}:00:00Z',
         'Appointment_Date__c': DAY}
        for index, work_id in enumerate(work_ids, 1)
    ]
    adapter, calls = _adapter(history=history)
    payloads = []
    for work_id in work_ids:
        payload = _payload('pns', interest='Roofing')
        payload['work_order_id'] = work_id
        payloads.append(payload)
    plans = adapter.prepare(payloads)
    assert len(plans) == 20
    assert all(any(op[1] == 'WorkOrder' for op in plan) for plan in plans)
    queries = [command[command.index('--query') + 1] for command in calls
               if command[1:3] == ['data', 'query']]
    assert sum(' FROM WorkOrder ' in query for query in queries) == 1
    assert sum(' FROM ServiceAppointment ' in query for query in queries) == 1
    assert sum(' FROM Product_Interest_Result__c ' in query for query in queries) == 1
    assert sum(' FROM Lead ' in query for query in queries) == 1


def test_batched_preflight_accepts_salesforce_15_or_18_character_ids():
    adapter, _ = _adapter()
    query = adapter._query

    def mixed_id_query(soql, **kwargs):
        rows = query(soql, **kwargs)
        if ' FROM WorkOrder ' in soql:
            return [dict(row, Lead__c=LEAD[:15]) for row in rows]
        if ' FROM ServiceAppointment ' in soql:
            return [dict(row, ParentRecordId=WORK[:15]) for row in rows]
        if ' FROM Lead ' in soql:
            return [dict(row, Id=LEAD[:15]) for row in rows]
        return rows

    adapter._query = mixed_id_query
    planned = adapter.prepare([_payload('pns', interest='Roofing')])
    assert len(planned) == 1
    assert any(item[1] == 'WorkOrder' for item in planned[0])
