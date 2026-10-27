"""Sandbox contract regressions. No real Salesforce or Printer writes."""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo
from pypdf import PdfReader
from io import BytesIO
from types import SimpleNamespace

import pytest

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft, prices, outcome_fields
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.service import ResultingService, ResultingDailyPull
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.salesforce_adapter import ResultingSalesforceAdapter, ResultingSalesforceError

DAY = '2026-10-26'
WORK = '0WO000000000001AAA'
LEAD = '00Q000000000001AAA'
USER = '005000000000001AAA'
RECORD = ModSheetRecord(source_id=WORK,lead_source_id=LEAD,
                        lead_name='Example Customer',work_order_number='00001234',
                        scheduled_start='2026.10.26 ; 10:00:00 AM',
                        assigned_service_resources=('Example Rep',),
                        product_interest='Roofing;Siding')


def test_dispo_and_dnr_statuses_do_not_require_a_lead_dropdown():
    for dispo, status in [('sale','Sale Pending'),('pns','Nurturing'),
                          ('np','Nurturing'),('cxl','Canceled'),
                          ('nra','Nurturing'),('oos','Out of Scope')]:
        values = outcome_fields(clean_draft({'dispo':dispo}))
        assert values['lead_status'] == status
        assert outcome_fields(clean_draft({'dispo':dispo,'dnr':True}))['lead_status'] == 'Do Not Call'
        assert outcome_fields(clean_draft({'dispo':dispo,'dnr':False,'dnr_reason':'Roofing'}))['lead_status'] == status


def test_prices_use_only_number_lines_not_numbers_in_comments():
    assert prices('25,000\n$22,570.00\nno 100% guess\n17,850') == {
        'highest':'25000','lowest':'17850'}
    assert prices('redline 100,000') == {'highest':'','lowest':''}


def test_times_are_am_pm_and_disallow_unexpected_draft_fields():
    assert clean_draft({'call_1':'10:15 AM','call_2':'1:02 PM'})['call_2'] == '1:02 PM'
    with pytest.raises(ValueError,match='AM or PM'):
        clean_draft({'call_1':'23:00'})
    with pytest.raises(ValueError,match='Unknown'):
        clean_draft({'salesforce_api_field':'Status'})


def test_refresh_preserves_unsent_notes_and_removed_routing(tmp_path):
    repo = ResultingRepository(Database(tmp_path/'printer.sqlite'))
    repo.refresh(DAY,[RECORD])
    revision = repo.save_draft(DAY,WORK,clean_draft({'dispo':'pns','notes':'Do not lose'}),0)
    assert revision == 1
    changed = ModSheetRecord(source_id=WORK,lead_source_id=LEAD,lead_name='Example Customer',
        work_order_number='00001234',assigned_service_resources=('Reassigned Rep',))
    repo.refresh(DAY,[changed])
    row = repo.sheets(DAY)[0]
    assert row['draft']['notes'] == 'Do not lose'
    assert row['snapshot']['assigned_service_resources'] == ['Reassigned Rep']
    assert row['revision'] == 1
    with pytest.raises(ValueError,match='Reload'):
        repo.save_draft(DAY,WORK,clean_draft({'dispo':'sale'}),0)
    repo.refresh(DAY,[])
    assert repo.sheets(DAY)[0]['current'] == 0
    assert repo.sheets(DAY)[0]['draft']['dispo'] == 'pns'


class Source:
    def __init__(self): self.queries=[]
    def records(self,**query):
        self.queries.append(query)
        return [RECORD]


class Writer:
    def __init__(self): self.plans=[];self.applied=[]
    def mod_users(self): return [{'id':USER,'name':'MOD Example'}]
    def prepare(self,batch):
        self.plans.extend(batch)
        return [{'work_order_id':item['work_order_id']} for item in batch]
    def apply(self,plan): self.applied.append(plan)


def _service(tmp_path):
    repo=ResultingRepository(Database(tmp_path/'printer.sqlite'))
    source,writer=Source(),Writer()
    settings=SimpleNamespace(settings=lambda:None)
    service=ResultingService(repo,source,writer,settings,'America/Los_Angeles')
    return service,repo,source,writer


def test_daily_mod_selection_refresh_and_end_of_day_idempotence(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    assert service.refresh(DAY)==1
    assert source.queries[0]['remove_canceled'] is False
    assert source.queries[0]['limit'] is None
    assert service.set_mod(DAY,USER)=='MOD Example'
    draft=clean_draft({'dispo':'sale','numbers':'20000\n17000',
                       'notes':'Black comment', 'redlines':'REDLINE',
                       'additional_products':True,
                       'product_results':{'Roofing':{'result':'sale','detail':''},
                                          'Siding':{'result':'pns','detail':'Price Objection'}}})
    service.save(DAY,WORK,draft,0)
    assert service.submit(DAY)=={'submitted':1,'day':DAY}
    assert len(writer.applied)==1
    payload=writer.plans[0]
    assert payload['fields']['price']['lowest']=='17000'
    assert payload['draft']['notes']=='Black comment'
    assert len(payload['product_results'])==2
    assert repo.sheets(DAY)[0]['submitted_at'] is not None
    with pytest.raises(ValueError):
        service.submit(DAY)


def test_unresulted_sheet_is_not_submitted_and_no_writes_happen(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    service.refresh(DAY)
    service.set_mod(DAY,USER)
    with pytest.raises(ValueError,match='No unsubmitted'):
        service.submit(DAY)
    assert writer.applied==[]
    assert repo.day(DAY)['submitting']==0


def test_dnr_reason_goes_to_generated_redline_and_never_overwrites_black_comment(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    service.refresh(DAY)
    sheet=repo.sheets(DAY)[0]
    draft=clean_draft({'dispo':'pns','notes':'Normal comment',
                       'redlines':'Scope changed',
                       'dnr':True,'dnr_reason':'Roofing'})
    result=service.submission_payload(dict(sheet,day=DAY,draft=draft), USER)
    assert result['final_redlines']=='Scope changed\nDNR - Roofing'
    assert result['draft']['notes']=='Normal comment'


def test_real_adapter_refuses_guessed_salesforce_identifiers():
    adapter=ResultingSalesforceAdapter(
        executable='/does-not-exist/sf')
    with pytest.raises(ResultingSalesforceError):
        adapter._appointment_ids('this is not an ID',DAY)
    with pytest.raises(ResultingSalesforceError):
        adapter._describe('WorkOrder; DROP TABLE')


def test_mod_sheet_grid_and_architecture_boundaries_are_stable():
    root=Path(__file__).parents[1]
    css=(root/'static/mod_resulting/sheet.css').read_text()
    html=(root/'templates/mod_resulting.html').read_text()
    service=(root/'mod_resulting/service.py').read_text()
    assert '571.65 / 236.25' in css
    for height in ('13.5fr','25.5fr','33.75fr','16.5fr','30fr'):
        assert height in css
    for label in ('MOD Notes:','Dispo:','90 Min','DNR','CXL At Lead'):
        assert label in html
    assert 'Lead Name:' in html and 'Address:' in html
    assert 'import salesforce' not in service
    assert 'sf data' not in service
    assert 'subprocess' not in service


def test_single_product_result_uses_selected_primary_product(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    service.refresh(DAY)
    sheet=dict(repo.sheets(DAY)[0],day=DAY)
    sheet['draft']=clean_draft({'dispo':'pns','primary_product':'Siding'})
    payload=service.submission_payload(sheet,USER)
    assert payload['product_results']==[{
        'product':'Siding','result':'pns','detail':'',
    }]


def test_eight_am_pull_keeps_the_existing_printer_schedule_untouched(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    scheduler=ResultingDailyPull(service)
    zone=ZoneInfo('America/Los_Angeles')
    early=datetime(2026,10,26,7,59,tzinfo=zone).timestamp()
    due=datetime(2026,10,26,8,0,tzinfo=zone).timestamp()
    assert not scheduler.due(early)
    assert scheduler.due(due)
    assert scheduler.run_due(due)=={'ok':True,'count':1}
    assert not scheduler.due(due+120)


def test_pdf_uses_existing_print_renderer_with_redlines_and_fixed_sheets():
    notes=clean_draft({'dispo':'sale','numbers':'25000\n17000',
                       'notes':'Customer comment',
                       'redlines':'CHANGE SCOPE','docs':True,
                       'ninety_min':True,'dnr':True,'dnr_reason':'Roofing'})
    sheet={'snapshot':asdict(RECORD),'draft':notes}
    payload=render_resulting_pdf([sheet])
    pdf=PdfReader(BytesIO(payload))
    assert len(pdf.pages)==1
    text=pdf.pages[0].extract_text()
    assert 'Work Order Number:' in text
    assert 'MOD Notes:' in text
    assert 'CHANGE SCOPE' in text
    assert 'DNR - Roofing' in text
    assert 'Customer comment' in text
    # Print generator's original label must remain; never redraw all boxes.
    assert 'Local Scheduled Start Time:' in text
