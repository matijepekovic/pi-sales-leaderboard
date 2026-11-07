"""Digital MOD cancellation display never discards persisted local notes.

Salesforce Service Appointment cancellation is distinct from Lead cancellation
and from an actual, already-submitted Work Order result.
"""
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfReader
import pytest

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.service import ResultingService

DAY = '2026-10-30'
WO = '0WO000000000001AAA'
MOD = '005000000000001AAA'
ACTIVE = ModSheetRecord(
    source_id=WO, work_order_number='00012345', lead_name='Customer',
    product_interest='Roofing', appointment_canceled=False,
)
CANCELED = replace(ACTIVE, appointment_canceled=True)


def _setup(tmp_path, record=ACTIVE, *, remote=None):
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    source = SimpleNamespace(records=lambda **kwargs: [source_record['value']])
    source_record = {'value': record}
    remote_result = {'value': clean_draft(remote or {})}
    writer = SimpleNamespace(read_results=lambda records: {
        item.source_id: remote_result['value'] for item in records
    })
    service = ResultingService(
        repo, source, writer,
        SimpleNamespace(settings=lambda: SimpleNamespace(market_segment='Olympia')),
        'America/Los_Angeles',
        pdf_exporter=lambda rows: tuple(item['work_order_id'] for item in rows),
    )
    return service, repo, source_record, remote_result


def test_canceled_card_without_notes_is_visible_and_resulted_cxl(tmp_path):
    service, repo, _, _ = _setup(tmp_path, CANCELED)
    assert service.refresh(DAY) == 1
    sheets = service.snapshot(DAY)['sheets']
    assert len(sheets) == 1
    assert sheets[0]['snapshot']['appointment_canceled'] is True
    assert sheets[0]['draft']['dispo'] == 'cxl'
    assert sheets[0]['result']['lead_status'] == 'Canceled'
    assert sheets[0]['result']['appointment_status'] == 'Canceled'
    assert sheets[0]['submitted_at'] is None
    assert len(repo.sheets(DAY)) == 1
    assert service.export_all_pdf(DAY) == (WO,)

def test_cancel_after_local_notes_keeps_card_and_marks_cxl_on_manual_refresh(tmp_path):
    service, repo, source, _ = _setup(tmp_path)
    service.refresh(DAY)
    original = clean_draft({
        'dispo': 'pns',
        'notes': 'Called customer to confirm cancellation',
        'redlines': 'Follow up with the homeowner',
        'note_runs': [{
            'text': 'Called customer to confirm cancellation', 'red': False,
        }],
    })
    repo.save_draft(DAY, WO, original, 0)
    source['value'] = CANCELED
    # Background source state cannot silently change an already imported day.
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'pns'
    service.refresh(DAY)
    changed = repo.sheets(DAY)[0]
    assert changed['draft'] == dict(original, dispo='cxl')
    assert changed['submitted_at'] is None  # Canceled SA is not a write receipt.
    assert changed['snapshot']['appointment_canceled'] is True
    assert len(service.snapshot(DAY)['sheets']) == 1
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'cxl'
    assert service.export_all_pdf(DAY) == (WO,)


def test_canceled_redlines_without_black_notes_still_show_cxl(tmp_path):
    service, repo, source, _ = _setup(tmp_path)
    service.refresh(DAY)
    repo.save_draft(DAY, WO, clean_draft({'redlines': 'Local red ink'}), 0)
    source['value'] = CANCELED
    service.refresh(DAY)
    sheet = service.snapshot(DAY)['sheets'][0]
    assert sheet['draft']['notes'] == ''
    assert sheet['draft']['redlines'] == 'Local red ink'
    assert sheet['draft']['dispo'] == 'cxl'


def test_cancel_read_replaces_local_dispo_and_requires_explicit_submit(tmp_path):
    service, repo, source, _ = _setup(tmp_path)
    service.refresh(DAY)
    repo.save_draft(DAY, WO, clean_draft({'dispo': 'pns'}), 0)
    repo.select_mod(DAY, MOD, 'Sales Manager')
    source['value'] = CANCELED
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'cxl'
    assert repo.day(DAY)['submitting'] == 0
    queued = repo.enqueue_submit(DAY)
    assert queued['total'] == 1
    claimed = repo.claim_submission()
    assert len(claimed['rows']) == 1
    assert claimed['rows'][0]['draft']['dispo'] == 'cxl'


@pytest.mark.parametrize('remote', [None, {'dispo': 'cxl', 'lead_status': 'Canceled'}])
def test_salesforce_cancellation_finishes_for_pdf_without_calling_writer(tmp_path, remote):
    service, repo, _, _ = _setup(tmp_path, CANCELED, remote=remote)
    service.allow_salesforce_writes = True
    service.refresh(DAY)
    repo.select_mod(DAY, MOD, 'Sales Manager')
    sheet = service.snapshot(DAY)['sheets'][0]
    assert sheet['pdf_only'] and not sheet['completed']
    # Even an imported CXL receipt leaves the documentation editable. The
    # posted Dispo cannot override a Salesforce cancellation on a PDF-only card.
    service.save(DAY, WO, clean_draft({
        'dispo': 'np', 'notes': 'Local cancellation note', 'redlines': 'Local red ink',
    }), sheet['revision'])
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'cxl'
    queued = service.enqueue(DAY, [WO])
    assert service.process_next_submission() == {
        'ok': True, 'submitted': 0, 'day': DAY, 'pdf_only': 1,
    }
    batch = repo.latest_submission(DAY, queued['job_id'])
    assert batch['state'] == 'completed' and batch['pdf_only'] == 1
    assert batch['items'][0]['state'] == 'pdf_only'
    finished = service.snapshot(DAY)['sheets'][0]
    assert finished['completed'] and finished['submitted_at'] == sheet['submitted_at']
    assert repo.unresolved_submission_attempts() == []
    with pytest.raises(ValueError, match='already submitted'):
        service.enqueue(DAY, [WO])
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'][0]['completed']
    pdf = PdfReader(BytesIO(render_resulting_pdf(repo.print_sheets(DAY))))
    text = pdf.pages[0].extract_text()
    assert 'Local cancellation note' in text and 'Local red ink' in text


def test_reactivated_appointment_can_submit_manual_cxl_without_pdf_only_notes(tmp_path):
    service, repo, source, _ = _setup(tmp_path)
    service.allow_salesforce_writes = True
    service.refresh(DAY)
    repo.select_mod(DAY, MOD, 'Sales Manager')
    service.save(DAY, WO, clean_draft({'dispo': 'pns', 'notes': 'Active note'}), 0)
    source['value'] = CANCELED
    service.refresh(DAY)
    sheet = service.snapshot(DAY)['sheets'][0]
    service.save(DAY, WO, clean_draft({
        'dispo': 'cxl', 'notes': 'Active note\nPrivate cancellation note',
        'redlines': 'Private cancellation redline',
    }), sheet['revision'])
    assert service.submit(DAY, [WO])['pdf_only'] == 1

    source['value'] = ACTIVE
    service.refresh(DAY)
    active = service.snapshot(DAY)['sheets'][0]
    assert not active['pdf_only'] and not active['completed']
    assert active['draft']['dispo'] == 'pns'
    assert active['draft']['notes'] == 'Active note' and not active['draft']['redlines']
    service.save(DAY, WO, clean_draft({
        'dispo': 'cxl', 'notes': 'Active note', 'redlines': 'Manually entered result',
    }), active['revision'])
    written = []
    service.writer.prepare = lambda payloads: list(payloads)
    service.writer.apply = written.append
    assert service.submit(DAY, [WO])['submitted'] == 1
    assert written[0]['dispo'] == 'cxl'
    assert written[0]['draft']['notes'] == 'Active note'
    assert written[0]['product_results'][0]['comment'] == 'Manually entered result'
    pdf = PdfReader(BytesIO(render_resulting_pdf(repo.print_sheets(DAY))))
    assert 'Private cancellation note' in pdf.pages[0].extract_text()
    assert 'Private cancellation redline' in pdf.pages[0].extract_text()


def test_batch_only_sends_the_cxl_chosen_in_mod(tmp_path):
    service, repo, _, remote = _setup(tmp_path)
    service.allow_salesforce_writes = True
    manual = replace(ACTIVE, source_id='0WO000000000002AAA')
    service.source.records = lambda **kwargs: [CANCELED, manual]
    service.refresh(DAY)
    repo.select_mod(DAY, MOD, 'Sales Manager')
    service.save(DAY, WO, clean_draft({'notes': 'PDF only'}), 0)
    service.save(DAY, manual.source_id, clean_draft({
        'dispo': 'cxl', 'notes': 'Send with manual CXL', 'redlines': 'Product comment',
    }), 0)
    prepared = []
    written = []

    def prepare(payloads):
        prepared.extend(payloads)
        return list(payloads)

    service.writer.prepare = prepare
    service.writer.apply = written.append
    job_id = service.enqueue(DAY)['job_id']
    assert service.process_next_submission() == {
        'ok': True, 'submitted': 1, 'day': DAY, 'pdf_only': 1,
    }
    assert [payload['work_order_id'] for payload in prepared] == [manual.source_id]
    assert written[0]['draft']['notes'] == 'Send with manual CXL'
    assert written[0]['product_results'][0]['comment'] == 'Product comment'
    batch = repo.latest_submission(DAY, job_id)
    assert [item['state'] for item in batch['items']] == ['pdf_only', 'submitted']
    service.source.records = lambda **kwargs: [CANCELED, replace(manual, appointment_canceled=True)]
    remote['value'] = clean_draft({'dispo': 'cxl', 'lead_status': 'Canceled'})
    service.refresh(DAY)
    assert all(sheet['completed'] for sheet in service.snapshot(DAY)['sheets'])


def test_old_active_card_needs_a_refresh_before_it_can_write(tmp_path):
    service, repo, _, _ = _setup(tmp_path)
    service.allow_salesforce_writes = True
    service.refresh(DAY)
    repo.select_mod(DAY, MOD, 'Sales Manager')
    service.save(DAY, WO, clean_draft({'dispo': 'pns', 'notes': 'Keep me'}), 0)
    with repo.db.connect() as conn:
        conn.execute("UPDATE mod_result_sheets SET snapshot=json_remove(snapshot,'$.appointment_source_id')")
    with pytest.raises(ValueError, match='Refresh MOD Sheets'):
        service.submit(DAY, [WO])
    assert not service.snapshot(DAY)['sheets'][0]['completed']
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'][0]['draft']['notes'] == 'Keep me'

def test_reactivated_appointment_clears_only_its_automatic_cxl(tmp_path):
    service, repo, source, _ = _setup(tmp_path, CANCELED)
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'cxl'
    source['value'] = ACTIVE
    service.refresh(DAY)
    sheets = service.snapshot(DAY)['sheets']
    assert len(sheets) == 1
    assert sheets[0]['draft']['dispo'] == ''
    assert sheets[0]['result'] is None
    assert sheets[0]['snapshot']['appointment_canceled'] is False
    assert service.export_all_pdf(DAY) == (WO,)

def test_canceled_lead_without_notes_stays_visible_and_resulted(tmp_path):
    canceled_lead = replace(ACTIVE, sales_lead_status='Canceled')
    service, repo, _, _ = _setup(tmp_path, canceled_lead, remote={
        'dispo': 'cxl', 'lead_status': 'Canceled',
    })
    service.refresh(DAY)
    sheets = service.snapshot(DAY)['sheets']
    assert len(sheets) == 1
    assert sheets[0]['draft']['dispo'] == 'cxl'
    assert sheets[0]['result']['work_order_status'] == 'Canceled'
    assert service.export_all_pdf(DAY) == (WO,)
    assert repo.sheets(DAY)[0]['submitted_at'] == -1.0

def test_canceled_lead_with_local_notes_remains_visible(tmp_path):
    service, repo, source, remote = _setup(tmp_path)
    service.refresh(DAY)
    repo.save_draft(DAY, WO, clean_draft({
        'dispo': 'pns', 'notes': 'I spoke to this homeowner',
    }), 0)
    source['value'] = replace(ACTIVE, sales_lead_status='Canceled')
    remote['value'] = clean_draft({'dispo': 'cxl', 'lead_status': 'Canceled'})
    service.refresh(DAY)
    sheet = service.snapshot(DAY)['sheets'][0]
    assert sheet['draft']['dispo'] == 'cxl'
    assert sheet['draft']['notes'] == 'I spoke to this homeowner'


def test_reactivation_restores_pre_cancellation_local_dispo_and_notes(tmp_path):
    service, repo, source, _ = _setup(tmp_path)
    service.refresh(DAY)
    repo.save_draft(DAY, WO, clean_draft({
        'dispo': 'pns', 'notes': 'Confirmed with homeowner',
    }), 0)
    source['value'] = CANCELED
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'cxl'
    source['value'] = ACTIVE
    service.refresh(DAY)
    draft = service.snapshot(DAY)['sheets'][0]['draft']
    assert draft['dispo'] == 'pns'
    assert draft['notes'] == 'Confirmed with homeowner'

def test_canceled_appointment_does_not_replace_a_real_salesforce_sale(tmp_path):
    service, repo, _, _ = _setup(tmp_path, CANCELED, remote={
        'dispo': 'sale', 'notes': 'Sale already recorded in Salesforce',
    })
    service.refresh(DAY)
    row = service.snapshot(DAY)['sheets'][0]
    assert row['draft']['notes'] == 'Sale already recorded in Salesforce'
    assert row['draft']['dispo'] == 'sale'
    assert row['submitted_at'] == -1.0

def test_canceled_lead_does_not_replace_a_real_salesforce_sale(tmp_path):
    canceled_lead = replace(ACTIVE, sales_lead_status='Canceled')
    service, repo, _, _ = _setup(tmp_path, canceled_lead, remote={
        'dispo': 'sale', 'lead_status': 'Canceled',
    })
    service.refresh(DAY)
    row = service.snapshot(DAY)['sheets'][0]
    assert row['draft']['dispo'] == 'sale'
    assert row['submitted_at'] == -1.0

def test_clear_local_disposes_previous_auto_cxl_backup(tmp_path):
    service, repo, source, _ = _setup(tmp_path)
    service.refresh(DAY)
    repo.save_draft(DAY, WO, clean_draft({
        'dispo': 'pns', 'notes': 'Temporary local notes',
    }), 0)
    source['value'] = CANCELED
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'cxl'
    service.clear_local(DAY)
    cleared = service.snapshot(DAY)['sheets'][0]['draft']
    assert cleared['notes'] == ''
    assert cleared['dispo'] == 'cxl'
    source['value'] = ACTIVE
    service.refresh(DAY)
    restored = service.snapshot(DAY)['sheets'][0]['draft']
    assert restored['dispo'] == ''
    assert restored['notes'] == ''


def test_salesforce_lead_canceled_without_resulting_draft_sets_cxl(tmp_path):
    canceled_lead = replace(ACTIVE, sales_lead_status='Canceled')
    service, repo, _, _ = _setup(tmp_path, canceled_lead)
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'cxl'
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'][0]['draft']['dispo'] == 'cxl'
