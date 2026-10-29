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


def test_refresh_imports_remote_results_and_preserves_local_draft(tmp_path):
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    remote = clean_draft({
        'dispo':'pns', 'notes':'WorkOrder.MOD_Notes__c from Salesforce',
        'call_1':'10:15 AM', 'call_2':'1:27 PM',
        'dnr':True, 'dnr_reason':'Roofing',
    })
    repo.refresh(DAY, [RECORD], external_drafts={WORK:remote})
    sheet = repo.sheets(DAY)[0]
    assert sheet['draft']['notes'] == remote['notes']
    assert sheet['draft']['redlines'] == ''
    assert sheet['draft']['dnr_reason'] == 'Roofing'
    assert sheet['submitted_at'] is not None  # Never re-submit an existing result.
    remote_updated = clean_draft({'dispo':'pns', 'notes':'Updated remote note'})
    repo.refresh(DAY, [RECORD], external_drafts={WORK:remote_updated})
    assert repo.sheets(DAY)[0]['draft'] == remote_updated
    assert repo.sheets(DAY)[0]['submitted_at'] == -1.0

    different = '0WO000000000002AAA'
    record_two = ModSheetRecord(source_id=different,lead_name='Second Customer')
    repo.refresh(DAY, [RECORD,record_two],
                 external_drafts={different:clean_draft({'notes':'Remote note'})})
    assert repo.sheets(DAY)[1]['draft']['notes'] == 'Remote note'
    local = clean_draft({'notes':'Edited on Pi before Refresh'})
    repo.save_draft(DAY,different,local,0)
    repo.refresh(DAY, [RECORD,record_two],
                 external_drafts={different:clean_draft({'dispo':'pns','notes':'Remote changed'})})
    assert repo.sheets(DAY)[1]['draft'] == local
    assert repo.sheets(DAY)[1]['submitted_at'] is None
    # Positive local write receipts must not be overwritten by Salesforce.
    repo.finish_item(DAY, different)
    repo.refresh(DAY, [RECORD,record_two],
                 external_drafts={different:clean_draft({'dispo':'cxl'})})
    assert repo.sheets(DAY)[1]['draft'] == local


def test_salesforce_refresh_reads_exact_mapped_objects_without_writes():
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        assert command[1:3] == ['data','query']
        query = command[command.index('--query') + 1]
        if ' FROM WorkOrder ' in query:
            assert 'MOD_Notes__c' in query
            assert 'Call_1__c' in query and 'Call_2__c' in query
            rows = [{
                'Id':WORK, 'Dispo__c':'PNS',
                'MOD_Notes__c':'Already resulted customer note',
                'Call_1__c':'10:15:00.000Z',
                'Call_2__c':'13:27:00.000Z',
                'Docs__c':True, 'X90_Min__c':True,
                'Promotion__c':False, 'Need__c':'Security',
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
            rows = [{
                'Id':PRODUCT, 'Work_Order__c':WORK, 'Lead__c':LEAD,
                'Product_Interest__c':'Roofing',
                'Result__c':'Pitch No Sale', 'Result_Detail__c':'Price Objection',
                'Price_Given__c':None, 'PR_1_Leg_Appointment__c':False,
                'Free_Product_Lead__c':False, 'CXL_Per_Redline__c':False,
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
    assert draft['dnr'] is True and draft['dnr_reason'] == 'Roofing'
    assert draft['product_results']['Roofing']['detail'] == 'Price Objection'
    assert len(calls) == 3
    assert all(command[1:3] == ['data', 'query'] for command in calls)


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
