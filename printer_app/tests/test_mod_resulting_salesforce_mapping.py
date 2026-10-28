"""The user-supplied MOD -> Salesforce contract, exercised without live writes."""
from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
import json

import pytest

from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft, outcome_fields
from printer_app.mod_resulting.service import ResultingService
from printer_app.mod_resulting.salesforce_adapter import (
    ResultingSalesforceAdapter, ResultingSalesforceError, WO, SA, LEAD_FIELDS, PR,
    PRODUCT_RESULT, REVIEW_FIELD,
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
        _field('Deposit_Payment__c','currency'),
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
    ]
    sa = [
        _field('Status','picklist',[
            'Completed','Canceled','No Rep Available',
        ]),
        _field('FSSK__FSK_Work_Order__c','reference',refs=['WorkOrder']),
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
        _field('Comment__c','textarea'),
        _field('Original_Disposition__c','string'),
        _field('PR_Set_By__c','string'),
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
            if ' FROM ServiceAppointment ' in query:
                result = {'records':[{'Id':SA1},{'Id':SA2}], 'done':True}
            elif ' FROM WorkOrder ' in query:
                assert 'WHERE Lead__c = ' in query
                assert 'Appointment_Date_Time__c' in query
                result = {'records':historical_works, 'done':True}
            elif ' FROM Product_Interest_Result__c ' in query:
                result = {'records':list(existing_results),'done':True}
            elif ' FROM Lead ' in query:
                result = {'records':[{
                    'Id': LEAD, 'Product_Interest_lead__c': lead_interest,
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
    )
    values=clean_draft(dict(draft,dispo=dispo))
    return ResultingService.submission_payload({
        'day':DAY,'work_order_id':WORK,
        'snapshot':asdict(source),'draft':values,
    },MOD)


def _operations(adapter,payload):
    return adapter.prepare([payload])[0]


def _single(plan,name):
    matches=[row for row in plan if row[1]==name]
    assert len(matches)==1, (name,matches)
    return matches[0]


def _assert_no_protected_fields(plan):
    forbidden={
        'Pictures__c','Power_Questions__c','T_Close__c',
        'Bid_Sheet_Submitted__c','Comment__c','Original_Disposition__c',
        'PR_Set_By__c',
    }
    for op,obj,ident,values in plan:
        assert not set(values).intersection(forbidden), (obj,values)
    # Every updated field is in the declared API mapping for that object.
    allowed={
        'WorkOrder':set(WO.values()) | {REVIEW_FIELD},
        'Lead':set(LEAD_FIELDS.values()),
        'ServiceAppointment':{SA['status']},
        'Product_Interest_Result__c':set(PR.values()),
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
    wo=_single(_operations(adapter,_payload(
        'pns',final_price_override='15500'
    )), 'WorkOrder')[3]
    assert 'Start_Price__c' not in wo
    assert wo['Price__c']=='15500'


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
    assert wo['Price__c']=='17000'
    assert wo['Deposit_Payment__c']=='5000'
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
    assert wo['Deposit_Payment__c']=='0'
    assert 'SALE Roofing: $14,500 | Deposit: $0' in wo['MOD_Notes__c']
    results=[row[3] for row in plan if row[1]==PRODUCT_RESULT]
    assert {item['Product_Interest__c']:item['Result__c'] for item in results}=={
        'Roofing':'Sale','Siding':'Pitch No Sale',
    }
    assert next(item for item in results if item['Product_Interest__c']=='Roofing')['Price_Given__c']=='14500'


def test_existing_product_result_uses_correct_identity_and_clears_pns_price_only():
    adapter,_=_adapter(existing_results=[{
        'Id':PR1,'Product_Interest__c':'Roofing',
    }])
    plan=_operations(adapter,_payload('pns',interest='Roofing'))
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
