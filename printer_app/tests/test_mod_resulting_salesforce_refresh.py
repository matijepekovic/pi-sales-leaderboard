"""Read-only Salesforce Refresh hydration without overwriting local MOD ink."""
from dataclasses import asdict
from types import SimpleNamespace
import json

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.salesforce_adapter import ResultingSalesforceAdapter

DAY = '2026-10-27'
WORK = '0WO000000000001AAA'
LEAD = '00Q000000000001AAA'
PRODUCT = 'a12000000000001AAA'
RECORD = ModSheetRecord(
    source_id=WORK, lead_source_id=LEAD,
    lead_name='Sample Customer', work_order_number='00012345',
    product_interest='Roofing',
)


def test_refresh_merges_changed_salesforce_fields_and_preserves_local_edits(tmp_path):
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    remote = clean_draft({
        'dispo':'pns', 'notes':'WorkOrder.MOD_Notes__c from Salesforce',
        'call_1':'10:15 AM', 'call_2':'1:27 PM',
        'dnr':True, 'dnr_reason':'Roofing',
    })
    repo.refresh(DAY, [RECORD], external_drafts={WORK:remote})
    sheet = repo.sheets(DAY)[0]
    assert sheet['draft'] == remote
    assert sheet['submitted_at'] == -1.0  # Salesforce already resulted this.
    remote_updated = clean_draft({'dispo':'cxl', 'notes':'Updated Salesforce note'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:remote_updated})
    assert repo.sheets(DAY)[0]['draft'] == remote_updated
    assert repo.sheets(DAY)[0]['submitted_at'] == -1.0
    with __import__('pytest').raises(ValueError, match='Reload'):
        repo.save_draft(DAY, WORK, clean_draft({'dispo':'sale'}), repo.sheets(DAY)[0]['revision'])

    different = '0WO000000000002AAA'
    other = ModSheetRecord(source_id=different, lead_name='Second Customer')
    repo.refresh(DAY, [RECORD, other],
                 external_drafts={different:clean_draft({'notes':'Remote note'})})
    local = clean_draft({
        'dispo':'sale', 'notes':'My notes during the day',
        'redlines':'MY REDLINE', 'need':'TEST GIBBERISH',
        'numbers':'99999', 'review':True,
    })
    repo.save_draft(DAY, different, local, 0)
    refreshed = clean_draft({
        'dispo':'pns', 'notes':'Updated Salesforce note',
        'need':'Real need', 'numbers':'18000',
        'result_detail':'Price Objection',
    })
    repo.refresh(DAY, [RECORD, other], external_drafts={different:refreshed})
    sheet = repo.sheets(DAY)[1]
    assert sheet['draft'] == dict(
        refreshed, notes='My notes during the day', redlines='MY REDLINE', review=True
    )
    assert sheet['submitted_at'] == -1.0
    assert sheet['revision'] > 1
    with __import__('pytest').raises(ValueError, match='Reload'):
        repo.save_draft(DAY, different, local, 1)


def test_refresh_only_protects_locally_changed_notes_and_clear_resets_them(tmp_path):
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    sf = clean_draft({'notes':'Original Salesforce note', 'need':'Salesforce need'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:sf})
    # A local change to some other field must never block an updated remote note.
    repo.save_draft(DAY, WORK, clean_draft({
        'notes':'Original Salesforce note', 'need':'Local only',
    }), 0)
    next_sf = clean_draft({'notes':'New Salesforce note', 'need':'New Salesforce need'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:next_sf})
    sheet = repo.sheets(DAY)[0]
    assert sheet['draft'] == next_sf
    assert sheet['revision'] == 2
    with __import__('pytest').raises(ValueError, match='Reload'):
        repo.save_draft(DAY, WORK, sf, 1)

    local_note = clean_draft(dict(next_sf, notes='My note', redlines='My redline'))
    repo.save_draft(DAY, WORK, local_note, 2)
    newest_sf = clean_draft({'dispo':'np', 'notes':'Another Salesforce note',
                             'need':'Verified Salesforce need'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:newest_sf})
    observed = repo.sheets(DAY)[0]
    assert observed['submitted_at'] == -1.0
    assert observed['draft'] == dict(newest_sf, notes='My note', redlines='My redline')

    # Clear removes local Notes/redlines too, then restores remote truth.
    repo.refresh(DAY, [RECORD], external_drafts={WORK:newest_sf}, clear_local=True)
    assert repo.sheets(DAY)[0]['draft'] == newest_sf
    assert repo.sheets(DAY)[0]['submitted_at'] == -1.0
    # The imported result stays locked, not newly eligible for submission.
    with __import__('pytest').raises(ValueError, match='Reload'):
        repo.save_draft(DAY, WORK, clean_draft({'dispo':'sale'}), repo.sheets(DAY)[0]['revision'])


def test_refresh_and_clear_preserve_real_salesforce_write_receipts(tmp_path):
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    repo.refresh(DAY, [RECORD], external_drafts={WORK:clean_draft({})})
    saved = clean_draft({'dispo':'pns', 'notes':'Already sent'})
    repo.save_draft(DAY, WORK, saved, 0)
    repo.finish_item(DAY, WORK)
    original = repo.sheets(DAY)[0]
    assert original['submitted_at'] > 0
    remote = clean_draft({'dispo':'sale', 'notes':'Changed after submission'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:remote})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:remote}, clear_local=True)
    actual = repo.sheets(DAY)[0]
    assert actual['draft'] == remote  # Salesforce wins after a real End of Day too.
    assert actual['revision'] > original['revision']
    assert actual['submitted_at'] == original['submitted_at']
    assert actual['override_active'] == 0


def test_salesforce_refresh_reads_exact_mapped_objects_without_writes():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[1:3] == ['sobject', 'describe']:
            assert command[command.index('--sobject')+1] == 'WorkOrder'
            return SimpleNamespace(stdout=json.dumps({'status':0,'result':{
                'name':'WorkOrder','fields':[
                    {'name':'Review__c','type':'string','updateable':True},
                ],
            }}), stderr='', returncode=0)
        assert command[1:3] == ['data','query']
        query = command[command.index('--query') + 1]
        if ' FROM WorkOrder ' in query:
            assert 'Review__c' in query
            assert 'MOD_Notes__c' in query
            assert 'Call_1__c' in query and 'Call_2__c' in query
            rows = [{
                'Id':WORK, 'Dispo__c':'PNS',
                'MOD_Notes__c':'Already resulted customer note',
                'Call_1__c':'10:15:00.000Z',
                'Call_2__c':'13:27:00.000Z',
                'Docs__c':True, 'X90_Min__c':True,
                'Promotion__c':False, 'Review__c':'Manager Approved',
                'Need__c':'Security',
                'Want__c':'Value', 'Start_Price__c':25000,
                'Price__c':17000, 'Deposit_Payment__c':'0/159.50',
            }]
        elif ' FROM Lead ' in query:
            assert 'DNR_Do_Not_Reset__c' in query
            rows = [{
                'Id':LEAD, 'DNR_Do_Not_Reset__c':True,
                'DNR_Reason__c':'Roofing',
                'X1_Leg_Appointment__c':False,
            }]
        elif ' FROM Product_Interest_Result__c ' in query:
            assert 'Include_in_Issued_Lead_Count__c' in query
            rows = [{
                'Id':PRODUCT, 'Work_Order__c':WORK, 'Lead__c':LEAD,
                'Product_Interest__c':'Roofing',
                'Result__c':'Pitch No Sale', 'Result_Detail__c':'Price Objection',
                'Price_Given__c':None, 'PR_1_Leg_Appointment__c':False,
                'Free_Product_Lead__c':False, 'CXL_Per_Redline__c':False,
                'Include_in_Issued_Lead_Count__c':True,
            }]
        else:
            raise AssertionError('Unexpected read query: ' + query)
        return SimpleNamespace(stdout=json.dumps({'status':0,'result':{
            'records':rows,'done':True}}), stderr='', returncode=0)

    adapter = ResultingSalesforceAdapter(runner=runner)
    external = adapter.read_results([RECORD])
    draft = clean_draft(external[WORK])
    assert draft['dispo'] == 'pns'
    assert draft['notes'] == 'Already resulted customer note'
    assert draft['redlines'] == ''
    assert draft['call_1'] == '10:15 AM'
    assert draft['call_2'] == '1:27 PM'
    assert draft['need'] == 'Security' and draft['want'] == 'Value'
    assert draft['numbers'] == '25000\n17000'
    assert draft['deposit_override'] == '0/159.50'
    assert draft['docs'] is True and draft['ninety_min'] is True
    assert draft['review'] is True
    assert draft['checkbox_values']['review'] == {
        'value': 'Manager Approved', 'edited': False,
    }
    assert draft['dnr'] is True and draft['dnr_reason'] == 'Roofing'
    assert draft['product_results']['Roofing']['detail'] == 'Price Objection'
    assert draft['primary_product'] == 'Roofing'
    assert len(calls) == 4
    assert sum(command[1:3] == ['data', 'query'] for command in calls) == 3
    assert sum(command[1:3] == ['sobject', 'describe'] for command in calls) == 1


def test_raw_checkbox_text_hydrates_visually_and_survives_refresh_without_conversion(tmp_path):
    from zoneinfo import ZoneInfo
    from printer_app.mod_resulting.salesforce_drafts import project_salesforce_drafts

    work = {
        WORK: {
            'Id': WORK, 'Dispo__c': None, 'Docs__c': '  Completed  ',
            'X90_Min__c': 'No', 'Promotion__c': True,
            'MOD_Notes__c': '',
        },
    }
    leads = {LEAD: {
        'DNR_Do_Not_Reset__c': False,
        'X1_Leg_Appointment__c': True,
    }}
    remote = clean_draft(project_salesforce_drafts(
        ZoneInfo('America/Los_Angeles'), {WORK: LEAD}, work, leads, {}
    )[WORK])
    assert remote['docs'] is True
    assert remote['ninety_min'] is False
    assert remote['promotion'] is True
    assert remote['checkbox_values']['docs'] == {
        'value': '  Completed  ', 'edited': False
    }
    assert remote['checkbox_values']['ninety_min'] == {
        'value': 'No', 'edited': False
    }
    assert remote['checkbox_values']['promotion'] == {
        'value': True, 'edited': False
    }
    assert remote['checkbox_values']['dnr'] == {
        'value': False, 'edited': False
    }
    assert remote['checkbox_values']['one_leg'] == {
        'value': True, 'edited': False
    }

    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    repo.refresh(DAY, [RECORD], external_drafts={WORK: remote})
    sheet = repo.sheets(DAY)[0]
    assert sheet['submitted_at'] is None
    assert sheet['draft']['checkbox_values'] == remote['checkbox_values']

    # Saving other fields must never mark an untouched raw value as edited.
    edited = clean_draft(dict(remote, notes='MOD note only'))
    repo.save_draft(DAY, WORK, edited, sheet['revision'])
    assert repo.sheets(DAY)[0]['draft']['checkbox_values']['docs']['edited'] is False
    # Unchanged Salesforce values must not undo a local popup edit.
    changed = clean_draft(dict(edited, checkbox_values={
        **edited['checkbox_values'],
        'docs': {'value': 'Checked in office', 'edited': True},
    }))
    repo.save_draft(DAY, WORK, changed, repo.sheets(DAY)[0]['revision'])
    repo.refresh(DAY, [RECORD], external_drafts={WORK: remote})
    assert repo.sheets(DAY)[0]['draft']['checkbox_values']['docs'] == {
        'value': 'Checked in office', 'edited': True
    }


def test_mixed_product_checkbox_values_are_visible_without_guessing_one():
    from zoneinfo import ZoneInfo
    from printer_app.mod_resulting.salesforce_drafts import project_salesforce_drafts

    works = {WORK: {'Id': WORK, 'Dispo__c': 'PNS'}}
    products = {WORK: [
        {
            'Product_Interest__c': 'Roofing', 'Result__c': 'Pitch No Sale',
            'Free_Product_Lead__c': True, 'CXL_Per_Redline__c': False,
        },
        {
            'Product_Interest__c': 'Siding', 'Result__c': 'Pitch No Sale',
            'Free_Product_Lead__c': False, 'CXL_Per_Redline__c': False,
        },
    ]}
    draft = clean_draft(project_salesforce_drafts(
        ZoneInfo('America/Los_Angeles'), {WORK:''}, works, {}, products,
    )[WORK])
    assert draft['free_lead'] is True
    assert draft['checkbox_values']['free_lead'] == {
        'value': 'True / False', 'edited': False,
    }
    assert draft['checkbox_values']['cxl_at_lead'] == {
        'value': False, 'edited': False,
    }


def test_remote_unresulted_notes_stay_black():
    from printer_app.mod_resulting.salesforce_drafts import project_salesforce_drafts
    from zoneinfo import ZoneInfo
    work = {
        'Id':WORK, 'Dispo__c':None,
        'MOD_Notes__c':'Pre-disposition black notes',
        'Call_1__c':None, 'Call_2__c':None,
    }
    drafts = project_salesforce_drafts(ZoneInfo('America/Los_Angeles'),
                                      {WORK:''}, {WORK:work}, {}, {})
    draft = clean_draft(drafts[WORK])
    assert draft['dispo'] == ''
    assert draft['notes'] == 'Pre-disposition black notes'
    assert draft['redlines'] == ''


def test_salesforce_refresh_handles_shared_leads_across_pages():
    """Multiple jobs sharing one lead must never cause duplicate Lead errors."""
    import re
    from zoneinfo import ZoneInfo
    from printer_app.mod_resulting.salesforce_refresh import read_result_drafts

    records = tuple(ModSheetRecord(
        source_id='0WO' + f'{index:012d}' + 'AAA',
        lead_source_id=LEAD, product_interest='Roofing',
    ) for index in range(41))
    lead_queries = []

    def query(text):
        if ' FROM WorkOrder ' in text:
            ids = re.findall(r'0WO[0-9]{12}AAA', text)
            return [{'Id':ident} for ident in ids]
        if ' FROM Lead ' in text:
            lead_queries.append(text)
            return [{'Id':LEAD}]
        if ' FROM Product_Interest_Result__c ' in text:
            return []
        raise AssertionError('Unexpected Salesforce object')

    fake = SimpleNamespace(zone=ZoneInfo('America/Los_Angeles'), _query=query)
    hydrated = read_result_drafts(fake, records)
    assert len(hydrated) == 41
    assert len(lead_queries) == 1
    assert all(row['dispo'] == '' for row in hydrated.values())


def test_refresh_recovers_canceled_lead_when_source_record_has_no_lead_id():
    from zoneinfo import ZoneInfo
    from printer_app.mod_resulting.salesforce_refresh import read_result_drafts

    record = ModSheetRecord(
        source_id=WORK, lead_source_id='', product_interest='Roofing'
    )
    def query(text):
        if ' FROM WorkOrder ' in text:
            assert 'Lead__c' in text
            return [{'Id':WORK, 'Lead__c':LEAD, 'Dispo__c':None}]
        if ' FROM Lead ' in text:
            return [{'Id':LEAD, 'Status':'Canceled'}]
        if ' FROM Product_Interest_Result__c ' in text:
            return []
        raise AssertionError('Unexpected Salesforce object')
    fake = SimpleNamespace(zone=ZoneInfo('America/Los_Angeles'), _query=query)
    remote = clean_draft(read_result_drafts(fake, [record])[WORK])
    assert remote['lead_status'] == 'Canceled'
    assert remote['dispo'] == 'cxl'


def test_salesforce_text_deposit_payment_is_hydrated_into_one_sale():
    from printer_app.mod_resulting.salesforce_drafts import project_salesforce_drafts
    from zoneinfo import ZoneInfo

    works = {WORK: {
        'Id': WORK, 'Dispo__c':'Sale', 'MOD_Notes__c':'Black note',
        'Deposit_Payment__c':'500/159.50',
    }}
    products = {WORK: [{
        'Product_Interest__c':'Roofing', 'Result__c':'Sale',
        'Price_Given__c':18000,
    }]}
    draft = clean_draft(project_salesforce_drafts(
        ZoneInfo('America/Los_Angeles'), {WORK: LEAD},
        works, {LEAD:{}}, products)[WORK])
    assert draft['deposit_override']=='500/159.50'
    assert draft['sale_products']['Roofing']=={
        'price':'18000', 'deposit':'500', 'payment':'159.50'}


def _mapped(work_dispo, products, *, lead=None, notes=''):
    from zoneinfo import ZoneInfo
    from printer_app.mod_resulting.salesforce_drafts import project_salesforce_drafts
    work = {WORK: {
        'Id': WORK, 'Dispo__c': work_dispo, 'MOD_Notes__c': notes,
        'Deposit_Payment__c': '250',
    }}
    result = project_salesforce_drafts(
        ZoneInfo('America/Los_Angeles'), {WORK: LEAD}, work,
        {LEAD: lead or {}}, {WORK: products},
    )
    return clean_draft(result[WORK])


def test_product_result_is_primary_disposition_when_salesforce_work_order_blank():
    pns = _mapped(None, [{
        'Product_Interest__c':'Windows',
        'Result__c':'Pitch No Sale',
        'Result_Detail__c':'Procrastination',
        'Price_Given__c':14100,
    }], lead={'Status':'Nurturing',
             'Previous_Result__c':'Pitch No Sale',
             'DNR_Do_Not_Reset__c':True})
    assert pns['dispo'] == 'pns'
    assert pns['result_detail'] == 'Procrastination'
    assert pns['product_results']['Windows']['result'] == 'pns'
    assert pns['product_results']['Windows']['price'] == '14100'
    assert pns['lead_status'] == 'Nurturing'
    assert pns['previous_result'] == 'Pitch No Sale'
    assert pns['dnr'] is True and pns['dnr_reason'] == ''
    assert pns['deposit_override'] == '250'

    sale = _mapped(None, [{
        'Product_Interest__c':'Bath', 'Result__c':'Sale',
        'Price_Given__c':14500,
    }], lead={'Status':'Sale Pending'})
    assert sale['dispo'] == 'sale'
    assert sale['sale_products']['Bath'] == {'price':'14500', 'deposit':'250'}
    assert sale['product_results']['Bath']['result'] == 'sale'
    assert sale['lead_status'] == 'Sale Pending'

    canceled = _mapped(None, [{
        'Product_Interest__c':'Bath', 'Result__c':'Canceled',
        'Result_Detail__c':'Out Of Scope', 'Price_Given__c':0,
    }], lead={'Status':'Out of Scope'})
    assert canceled['dispo'] == 'cxl'
    assert canceled['lead_status'] == 'Out of Scope'
    assert canceled['result_detail'] == 'Out Of Scope'

    no_pitch = _mapped(None, [{
        'Product_Interest__c':'Roofing', 'Result__c':'No Pitch',
    }])
    assert no_pitch['dispo'] == 'np'


def test_canceled_lead_overrides_work_order_and_product_results_first():
    blank = _mapped(None, [], lead={'Status':'Canceled'})
    assert blank['dispo'] == 'cxl'
    assert blank['lead_status'] == 'Canceled'
    assert blank['result_detail'] == ''

    # The Lead wins over explicit Work Order Sale and a fully priced product.
    conflicting = _mapped('Sale', [{
        'Product_Interest__c':'Roofing', 'Result__c':'Sale',
        'Result_Detail__c':'Price Objection', 'Price_Given__c':20000,
    }], lead={'Status':' CANCELED '})
    assert conflicting['dispo'] == 'cxl'
    assert conflicting['result_detail'] == ''
    assert conflicting['product_results']['Roofing']['result'] == 'sale'

    # The same rule applies to unrecognized Work Order/product values: neither
    # may veto an authoritative canceled Lead, and no extra product is invented.
    unexpected = _mapped('Unknown Dispo', [{
        'Product_Interest__c':'Bath', 'Result__c':'Unknown Result',
    }], lead={'Status':'Canceled'})
    assert unexpected['dispo'] == 'cxl'
    assert unexpected['product_results'] == {}

    unchanged = _mapped('Sale', [], lead={'Status':'Nurturing'})
    assert unchanged['dispo'] == 'sale'


def test_conflicting_product_results_use_most_information_or_remain_unresolved():
    more_info = _mapped(None, [{
        'Product_Interest__c':'Roofing', 'Result__c':'Pitch No Sale',
        'Result_Detail__c':'Price Objection', 'Price_Given__c':18000,
    }, {
        'Product_Interest__c':'Windows', 'Result__c':'No Pitch',
    }])
    assert more_info['dispo'] == 'pns'
    assert more_info['result_detail'] == 'Price Objection'
    assert more_info['product_results']['Roofing']['result'] == 'pns'
    assert more_info['product_results']['Windows']['result'] == 'np'

    tie = _mapped(None, [{
        'Product_Interest__c':'Roofing', 'Result__c':'Pitch No Sale',
        'Price_Given__c':18000,
    }, {
        'Product_Interest__c':'Windows', 'Result__c':'No Pitch',
        'Result_Detail__c':'Not Home',
    }])
    assert tie['dispo'] == ''
    assert tie['result_detail'] == ''
    assert tie['product_results']['Roofing']['result'] == 'pns'
    assert tie['product_results']['Windows']['result'] == 'np'

    same = _mapped(None, [{
        'Product_Interest__c':'Roofing', 'Result__c':'Pitch No Sale',
    }, {
        'Product_Interest__c':'Windows', 'Result__c':'Pitch No Sale',
        'Result_Detail__c':'Procrastination',
    }])
    assert same['dispo'] == 'pns'

    # A losing product's Result Detail must never be paired with the winning
    # main disposition simply because it is the only nonempty detail.
    mismatch = _mapped(None, [{
        'Product_Interest__c':'Roofing', 'Result__c':'Pitch No Sale',
        'Price_Given__c':18000, 'Free_Product_Lead__c':True,
    }, {
        'Product_Interest__c':'Windows', 'Result__c':'No Pitch',
        'Result_Detail__c':'Not Home',
    }])
    assert mismatch['dispo'] == 'pns'
    assert mismatch['result_detail'] == ''
    assert mismatch['product_results']['Windows']['detail'] == 'Not Home'

    work_order_wins = _mapped('OOS', [{
        'Product_Interest__c':'Windows', 'Result__c':'Sale',
        'Price_Given__c':17000,
    }])
    assert work_order_wins['dispo'] == 'oos'
    assert work_order_wins['product_results']['Windows']['result'] == 'sale'


def test_lead_canceled_without_any_work_order_result_is_already_completed(tmp_path):
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    canceled = _mapped(None, [], lead={'Status':'Canceled'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:canceled})
    sheet = repo.sheets(DAY)[0]
    assert sheet['draft']['dispo'] == 'cxl'
    assert sheet['submitted_at'] == -1.0
    assert sheet['override_active'] == 0
    with __import__('pytest').raises(ValueError, match='Reload'):
        repo.save_draft(DAY, WORK, clean_draft({'dispo':'sale'}), sheet['revision'])


def test_conflicting_remote_product_results_are_still_already_submitted(tmp_path):
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    remote = clean_draft({
        'additional_products': True,
        'product_results': {
            'Roofing': {'result':'pns', 'detail':'', 'price':'', 'deposit':''},
            'Windows': {'result':'np', 'detail':'', 'price':'', 'deposit':''},
        },
    })
    assert remote['dispo'] == ''
    repo.refresh(DAY, [RECORD], external_drafts={WORK:remote})
    sheet = repo.sheets(DAY)[0]
    assert sheet['draft'] == remote
    assert sheet['submitted_at'] == -1.0
    with __import__('pytest').raises(ValueError, match='Reload'):
        repo.save_draft(DAY, WORK, clean_draft({'dispo':'sale'}), sheet['revision'])


def test_refresh_preserves_existing_red_note_runs_when_text_matches_remote(tmp_path):
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    imported = clean_draft({'notes':'Same note'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:imported})
    local = clean_draft({
        'notes':'Same note',
        'note_runs':[{'text':'Same note', 'red':True}],
        'review':True,
    })
    repo.save_draft(DAY, WORK, local, 0)
    updated = clean_draft({'notes':'Changed Salesforce note'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:updated})
    actual = repo.sheets(DAY)[0]['draft']
    assert actual['notes'] == 'Same note'
    assert actual['note_runs'] == [{'text':'Same note', 'red':True}]
    assert actual['review'] is True
