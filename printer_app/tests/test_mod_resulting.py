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
        assert outcome_fields(clean_draft({'dispo':dispo,'dnr':True,'dnr_reason':'Roofing'}))['lead_status'] == 'Do Not Call'
        assert outcome_fields(clean_draft({'dispo':dispo,'dnr':False,'dnr_reason':'Roofing'}))['lead_status'] == status


def test_prices_ignore_letters_in_numbers_column_and_keep_separate_amounts():
    assert prices('Estimate $25,000\nSale ABC17,850\nOffer 22,570.00') == {
        'highest':'25000','lowest':'17850'}
    assert prices('Start A66667B\nFinish X555') == {
        'highest':'66667','lowest':'555'}
    assert prices('redline 100,000') == {
        'highest':'100000','lowest':'100000'}
    assert prices('12.345') == {'highest':'','lowest':''}
    assert prices('Invalid -100 or 1,00') == {'highest':'','lowest':''}
    assert prices('Notes only') == {'highest':'','lowest':''}
    assert prices('Zero 0') == {'highest':'0','lowest':'0'}


def test_times_are_am_pm_and_disallow_unexpected_draft_fields():
    assert clean_draft({'call_1':'10:15 AM','call_2':'1:02 PM'})['call_2'] == '1:02 PM'
    with pytest.raises(ValueError,match='AM or PM'):
        clean_draft({'call_1':'23:00'})
    with pytest.raises(ValueError,match='Unknown'):
        clean_draft({'salesforce_api_field':'Status'})


def test_refresh_preserves_only_local_notes_and_updates_routing(tmp_path):
    repo = ResultingRepository(Database(tmp_path/'printer.sqlite'))
    repo.refresh(DAY, [RECORD], external_drafts={WORK:clean_draft({})})
    revision = repo.save_draft(
        DAY, WORK, clean_draft({'dispo':'pns','notes':'Do not lose',
                                'review':True, 'numbers':'99999'}), 0)
    assert revision == 1
    changed = ModSheetRecord(
        source_id=WORK,lead_source_id=LEAD,lead_name='Example Customer',
        work_order_number='00001234',assigned_service_resources=('Reassigned Rep',)
    )
    sf = clean_draft({'dispo':'np','numbers':'18000', 'need':'Verified',
                      'notes':'Salesforce note'})
    repo.refresh(DAY, [changed], external_drafts={WORK:sf})
    row = repo.sheets(DAY)[0]
    assert row['draft'] == dict(sf, notes='Do not lose')
    assert row['submitted_at'] == -1.0  # Already resulted in Salesforce.
    assert row['snapshot']['assigned_service_resources'] == ['Reassigned Rep']
    assert row['revision'] == 2
    with pytest.raises(ValueError,match='Reload'):
        repo.save_draft(DAY, WORK, clean_draft({'dispo':'sale'}), 1)
    repo.refresh(DAY, [])
    assert repo.sheets(DAY)[0]['current'] == 0
    assert repo.sheets(DAY)[0]['draft']['dispo'] == 'np'


class Source:
    def __init__(self): self.queries=[]
    def records(self,**query):
        self.queries.append(query)
        return [RECORD]


class Writer:
    def __init__(self): self.plans=[];self.applied=[]
    def mod_users(self, market_segment): return [{'id':USER,'name':'MOD Example'}]
    def prepare(self,batch):
        self.plans.extend(batch)
        return [{'work_order_id':item['work_order_id']} for item in batch]
    def apply(self,plan): self.applied.append(plan)


def _service(tmp_path):
    repo=ResultingRepository(Database(tmp_path/'printer.sqlite'))
    source,writer=Source(),Writer()
    settings=SimpleNamespace(settings=lambda:SimpleNamespace(market_segment="Olympia"))
    service=ResultingService(repo,source,writer,settings,'America/Los_Angeles',
                             allow_salesforce_writes=True)
    return service,repo,source,writer


def test_clear_local_restores_salesforce_and_never_writes_to_salesforce(tmp_path):
    service,repo,source,writer = _service(tmp_path)
    sf_before = clean_draft({'notes':'Initial remote note'})
    writer.read_results = lambda records: {WORK: sf_before}
    service.refresh(DAY)
    initial = repo.sheets(DAY)[0]
    assert initial['draft']['notes'] == 'Initial remote note'
    assert initial['submitted_at'] is None

    repo.save_draft(DAY, WORK, clean_draft({
        'dispo':'sale', 'notes':'Local testing', 'redlines':'Local ink',
        'numbers':'99999', 'review':True,
    }), initial['revision'])
    sf_after = clean_draft({
        'dispo':'pns', 'notes':'Real Salesforce note',
        'numbers':'25000\\n17000',
        'result_detail':'Procrastination',
    })
    writer.read_results = lambda records: {WORK:sf_after}
    assert service.clear_local(DAY) == 1
    actual = repo.sheets(DAY)[0]
    assert actual['draft'] == sf_after
    assert actual['submitted_at'] == -1.0
    assert actual['revision'] > initial['revision']
    assert writer.applied == [] and writer.plans == []
    assert len(source.queries) == 2

    # A failed Salesforce read cannot erase the user's local drafts.
    def unavailable(records):
        raise RuntimeError('Salesforce unavailable')
    writer.read_results = unavailable
    previous = dict(actual)
    with pytest.raises(RuntimeError, match='Salesforce unavailable'):
        service.clear_local(DAY)
    assert repo.sheets(DAY)[0] == previous


def test_daily_mod_selection_refresh_and_end_of_day_idempotence(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    assert service.refresh(DAY)==1
    assert source.queries[0]['remove_canceled'] is False
    assert source.queries[0]['limit'] is None
    assert service.set_mod(DAY,USER)=='MOD Example'
    draft=clean_draft({'dispo':'sale','numbers':'20000\n17000',
                       'notes':'Black comment', 'redlines':'REDLINE',
                       'sale_products':{
                           'Roofing':{'price':'17000','deposit':'0'},
                           'Siding':{'price':'0','deposit':''},
                       }})
    service.save(DAY,WORK,draft,0)
    assert service.submit(DAY)=={'submitted':1,'day':DAY,'pdf':False}
    assert len(writer.applied)==1
    payload=writer.plans[0]
    assert payload['fields']['price']['lowest']=='17000'
    assert payload['draft']['notes']=='Black comment'
    assert payload['product_results']==[{
        'product':'Roofing','result':'sale','detail':'',
        'price':'17000','deposit':'0',
    }]
    assert payload['deposit_payment']=='0/'
    assert 'SALE Roofing: $17,000 | Deposit: $0' in payload['final_redlines']
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
    # The form must never be rebuilt as a parallel browser grid.
    assert 'grid-template-columns' not in css
    assert 'grid-template-rows' not in css
    assert 'style=' not in html
    assert 'printer-sheet' in html and 'mod_resulting.sheet_image' in html
    assert 'mod_resulting.surface_styles' in html
    for label in ('MOD Notes:','Dispo:','90 Min','DNR','CXL At Lead'):
        assert label in html
    assert 'Lead Name:' in html and 'Address:' in html
    assert 'import salesforce' not in service
    assert 'sf data' not in service
    assert 'subprocess' not in service


def test_default_product_result_uses_main_dispo_for_every_original_product(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    service.refresh(DAY)
    sheet=dict(repo.sheets(DAY)[0],day=DAY)
    sheet['draft']=clean_draft({'dispo':'pns','result_detail':'Price Objection'})
    payload=service.submission_payload(sheet,USER)
    assert payload['product_results']==[
        {'product':'Roofing','result':'pns','detail':'Price Objection','price':'','deposit':''},
        {'product':'Siding','result':'pns','detail':'Price Objection','price':'','deposit':''},
    ]


def test_sale_zero_price_is_not_sold_and_zero_deposit_is_valid(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    service.refresh(DAY)
    sheet=dict(repo.sheets(DAY)[0],day=DAY)
    sheet['draft']=clean_draft({
        'dispo':'sale',
        'numbers':'25000\n18000',
        'sale_products':{
            'Roofing':{'price':'18000','deposit':'0'},
            'Windows':{'price':'0','deposit':'500'},
        },
    })
    payload=service.submission_payload(sheet,USER)
    assert payload['fields']['price']=={'highest':'25000','lowest':'18000'}
    assert payload['deposit_payment']=='0/'
    assert [item['product'] for item in payload['product_results']]==['Roofing']
    assert 'Windows' not in payload['final_redlines']
    assert 'SALE Roofing: $18,000 | Deposit: $0' in payload['final_redlines']


def test_dnr_sets_do_not_call_and_unchecking_restores_dispo_status():
    draft=clean_draft({
        'dispo':'pns','dnr':True,'dnr_reason':'Roofing;Bath',
        # Historic local manual values must never override current resulting.
        'lead_status':'Sale Pending', 'previous_result':'No Pitch',
    })
    fields=outcome_fields(draft)
    assert fields['lead_status']=='Do Not Call'
    assert 'previous_result' not in fields
    assert fields['work_order_status']=='Completed'
    draft['dnr']=False
    assert outcome_fields(draft)['lead_status']=='Nurturing'
    draft['dispo']='sale'
    assert outcome_fields(draft)['lead_status']=='Sale Pending'


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


def test_printer_sandbox_is_read_only_for_salesforce_by_default(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    service.refresh(DAY)
    service.set_mod(DAY,USER)
    repo.save_draft(DAY,WORK,clean_draft({'dispo':'pns','notes':'Review only'}),0)
    # The real application never opts into live writes. Only explicit test
    # fixtures with a fake Salesforce writer can exercise submission.
    service.allow_salesforce_writes=False
    with pytest.raises(ValueError, match='Live Salesforce submission is disabled'):
        service.submit(DAY)
    assert writer.plans == []
    assert writer.applied == []
    assert repo.day(DAY)['submitting'] == 0
    assert repo.sheets(DAY)[0]['submitted_at'] is None


def test_app_does_not_enable_live_salesforce_writes():
    from printer_app.app import create_app
    from printer_app.config import Config
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        from pathlib import Path
        root=Path(directory)
        env=root/'env'
        env.write_text('EMAIL_ENABLED=0\n')
        app=create_app(Config(data_dir=root/'data',env_file=env,
                              secret_key='s'*64,email_enabled=False))
        assert app.extensions['mod_resulting'].allow_salesforce_writes is False



def test_sandbox_is_reachable_from_printer_and_never_writes_salesforce(tmp_path):
    from printer_app.app import create_app
    from printer_app.config import Config
    from printer_app.tests.auth_helpers import login_admin
    root=tmp_path
    env=root/'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app=create_app(Config(data_dir=root/'data',env_file=env,
                          secret_key='s'*64,email_enabled=False))
    app.testing=True
    service=app.extensions['mod_resulting']
    service.source=Source()
    service.writer=Writer()
    service.settings_repository=SimpleNamespace(
        settings=lambda: SimpleNamespace(market_segment='Olympia'))
    client=app.test_client()

    unauthenticated=client.get('/mod-resulting')
    assert unauthenticated.status_code in (302,303)
    assert '/login?' in unauthenticated.headers['Location']

    csrf=login_admin(client)
    control=client.get('/system/print-control')
    assert control.status_code==200
    assert b'MOD Resulting Sandbox' in control.data
    assert b'/mod-resulting' in control.data
    sandbox=client.get('/mod-resulting')
    assert sandbox.status_code==200
    assert b'Search customer or assigned service resource' in sandbox.data
    assert b'Hide completed' in sandbox.data
    assert b'End of day' in sandbox.data
    assert b'MOD Notes:' in sandbox.data
    assert b'MOD Example' in sandbox.data
    assert b'<header>' not in sandbox.data
    assert service.allow_salesforce_writes is False

    result=client.post('/mod-resulting/api/submit',
                       data={'csrf':csrf,'mode':'all'},headers={'Origin':'http://localhost'})
    assert result.status_code==422
    assert b'Live Salesforce submission is disabled' in result.data
    assert service.writer.applied==[]
    db=app.extensions['printer_db']
    for table in ('jobs','print_attempts','commands','print_queue_releases'):
        assert db.rows('SELECT * FROM '+table)==[]

def test_select_mod_inherits_market_from_the_imported_daily_batch(tmp_path):
    service, repository, source, writer = _service(tmp_path)
    settings = SimpleNamespace(market_segment='Olympia')
    service.settings_repository = SimpleNamespace(settings=lambda:settings)
    chosen_markets = []
    def managers(market):
        chosen_markets.append(market)
        return [{'id':USER,'name':market + ' Sales Manager'}]
    writer.mod_users = managers

    service.refresh(DAY)
    assert repository.imported_market(DAY) == 'Olympia'
    assert service.users(DAY)[0]['name'] == 'Olympia Sales Manager'
    service.set_mod(DAY, USER)
    assert repository.day(DAY)['mod_user_name'] == 'Olympia Sales Manager'
    # Editing MOD Settings alone does not silently change the loaded batch.
    settings.market_segment = 'Seattle'
    assert service.users(DAY)[0]['name'] == 'Olympia Sales Manager'
    assert repository.day(DAY)['mod_user_id'] == USER
    # A deliberate Refresh imports the new market and clears the old MOD.
    service.refresh(DAY)
    assert repository.imported_market(DAY) == 'Seattle'
    assert repository.day(DAY)['mod_user_id'] == ''
    assert service.users(DAY)[0]['name'] == 'Seattle Sales Manager'
    assert source.queries[-1]['market_segment'] == 'Seattle'
    assert chosen_markets == ['Olympia', 'Olympia', 'Olympia', 'Seattle']


def test_preexisting_import_without_market_automatically_reimports_its_scope(tmp_path):
    service, repository, source, writer = _service(tmp_path)
    repository.refresh(DAY, [RECORD])  # Old version, no market metadata.
    assert repository.imported_market(DAY) == ''
    assert service.users(DAY) == [{'id':USER,'name':'MOD Example'}]
    assert repository.imported_market(DAY) == 'Olympia'
    assert source.queries[-1]['market_segment'] == 'Olympia'


def test_notes_keep_separate_ink_and_result_detail_is_always_red():
    from printer_app.mod_resulting.contract import (
        final_redline_text, note_runs_for_display)
    draft = clean_draft({
        'dispo':'pns', 'notes':'Before disposition\nAfter disposition',
        'note_runs':[
            {'text':'Before disposition','red':False},
            {'text':'\nAfter disposition','red':True},
        ],
        'result_detail':'Price Objection',
    })
    assert note_runs_for_display(draft) == [
        {'text':'Before disposition','red':False},
        {'text':'\nAfter disposition','red':True},
    ]
    assert final_redline_text(draft) == 'Price Objection'
    with pytest.raises(ValueError,match='does not match'):
        clean_draft({
            'notes':'Actual', 'note_runs':[{'text':'Different','red':True}]
        })


def test_selected_submissions_keep_remaining_work_orders_editable_and_preserve_pdf(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    second = ModSheetRecord(
        source_id='0WO000000000002AAA', lead_source_id=LEAD,
        lead_name='Second Customer', work_order_number='00001235',
        product_interest='Roofing',
    )
    repo.refresh(DAY, [RECORD, second], market_segment='Olympia')
    service.set_mod(DAY, USER)
    repo.save_draft(DAY, WORK, clean_draft({'dispo':'pns','notes':'First'}), 0)
    repo.save_draft(DAY, second.source_id, clean_draft({'dispo':'np','notes':'Second'}), 0)
    service.pdf_exporter = render_resulting_pdf
    service.output_directory = tmp_path/'completed'

    assert service.submit(DAY,[WORK])['submitted'] == 1
    assert [item['work_order_id'] for item in repo.submitted_sheets(DAY)] == [WORK]
    pdf_path=service.output_directory/(DAY + '-completed.pdf')
    first_pdf=PdfReader(BytesIO(pdf_path.read_bytes())).pages[0].extract_text()
    assert '00001234' in first_pdf and '00001235' not in first_pdf
    assert repo.day(DAY)['submitted_at'] is not None

    with pytest.raises(ValueError,match='already submitted'):
        service.submit(DAY,[WORK])
    assert repo.day(DAY)['submitting'] == 0
    with pytest.raises(ValueError):
        service.set_mod(DAY,USER)

    # Unselected sheets can still be edited after an earlier submission.
    pending=next(row for row in repo.sheets(DAY) if row['work_order_id']==second.source_id)
    assert pending['submitted_at'] is None
    revised=clean_draft(dict(pending['draft'], notes='Second edited'))
    repo.save_draft(DAY, second.source_id, revised, pending['revision'])

    assert service.submit(DAY,[second.source_id])['submitted']==1
    assert len(writer.applied)==2
    assert len(repo.submitted_sheets(DAY))==2
    combined=PdfReader(BytesIO(pdf_path.read_bytes())).pages[0].extract_text()
    assert '00001234' in combined and '00001235' in combined
    assert 'Second edited' in combined
    with pytest.raises(ValueError,match='No unsubmitted'):
        service.submit(DAY)
    assert len(writer.applied)==2


def test_selected_submission_rejects_blank_unknown_and_duplicate_ids(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    repo.refresh(DAY,[RECORD],market_segment='Olympia')
    service.set_mod(DAY,USER)
    repo.save_draft(DAY,WORK,clean_draft({'dispo':'pns'}),0)
    for selected in ([],[WORK,WORK],['0WO000000000999AAA'],[WORK,'0WO000000000999AAA']):
        with pytest.raises(ValueError):
            service.submit(DAY,selected)
        assert repo.day(DAY)['submitting']==0
        assert writer.applied==[]
    assert service.submit(DAY,[WORK])['submitted']==1


def test_partial_failure_preserves_receipts_pdf_and_retries_only_remaining(tmp_path):
    service,repo,source,writer=_service(tmp_path)
    second=ModSheetRecord(source_id='0WO000000000002AAA',lead_source_id=LEAD,
        lead_name='Second Customer',work_order_number='00001235',product_interest='Roofing')
    repo.refresh(DAY,[RECORD,second],market_segment='Olympia')
    service.set_mod(DAY,USER)
    repo.save_draft(DAY,WORK,clean_draft({'dispo':'pns'}),0)
    repo.save_draft(DAY,second.source_id,clean_draft({'dispo':'np'}),0)
    service.pdf_exporter=render_resulting_pdf
    service.output_directory=tmp_path/'completed'
    original=writer.apply
    def fail_second(plan):
        if plan['work_order_id']==second.source_id:
            raise RuntimeError('Simulated Salesforce outage')
        original(plan)
    writer.apply=fail_second
    with pytest.raises(RuntimeError,match='Salesforce outage'):
        service.submit(DAY)
    assert [row['work_order_id'] for row in repo.submitted_sheets(DAY)]==[WORK]
    pending=next(row for row in repo.sheets(DAY) if row['work_order_id']==second.source_id)
    assert 'Salesforce outage' in pending['submit_error']
    assert pending['submitted_at'] is None
    partial_pdf=service.output_directory/(DAY+'-completed.pdf')
    text=PdfReader(BytesIO(partial_pdf.read_bytes())).pages[0].extract_text()
    assert '00001234' in text and '00001235' not in text
    writer.apply=original
    assert service.submit(DAY,[second.source_id])['submitted']==1
    assert [item['work_order_id'] for item in writer.applied]==[WORK,second.source_id]


def test_live_salesforce_write_setting_requires_explicit_opt_in(tmp_path, monkeypatch):
    from printer_app.config import Config
    from printer_app.app import create_app
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\nPRINTER_SECRET_KEY=' + 's'*64 + '\nMOD_RESULTING_LIVE_WRITES=1\n')
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setenv('PRINTER_DATA_DIR', str(tmp_path/'enabled'))
    monkeypatch.delenv('MOD_RESULTING_LIVE_WRITES', raising=False)
    cfg = Config.from_env()
    assert cfg.mod_resulting_live_writes is True
    app = create_app(cfg)
    assert app.extensions['mod_resulting'].allow_salesforce_writes is True
    # Opt-in config alone does not invoke Salesforce; no submission is made.
    assert app.extensions['mod_resulting'].repository.sheets(DAY) == []


def test_submit_api_rejects_unselected_and_malformed_scope_before_live_write(tmp_path):
    from printer_app.app import create_app
    from printer_app.config import Config
    from printer_app.tests.auth_helpers import login_admin

    env = tmp_path/'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app=create_app(Config(data_dir=tmp_path/'data',env_file=env,
                          secret_key='s'*64,email_enabled=False))
    client=app.test_client()
    csrf=login_admin(client)
    for values in ({}, {'mode':'invalid'},
                   {'mode':'selected','work_order_ids':'{}'},
                   {'mode':'selected','work_order_ids':'not-json'}):
        result=client.post('/mod-resulting/api/submit',
                           data=dict({'csrf':csrf},**values),
                           headers={'Origin':'http://localhost'})
        assert result.status_code==422
    assert app.extensions['mod_resulting'].allow_salesforce_writes is False
