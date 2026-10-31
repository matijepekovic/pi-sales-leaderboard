"""Digital MOD cancellation display never discards persisted local notes.

Salesforce Service Appointment cancellation is distinct from Lead cancellation
and from an actual, already-submitted Work Order result.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft, canceled_without_notes
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


def test_canceled_only_card_without_notes_is_hidden_but_saved(tmp_path):
    service, repo, _, _ = _setup(tmp_path, CANCELED)
    assert service.refresh(DAY) == 1
    assert service.snapshot(DAY)['sheets'] == []
    saved = repo.sheets(DAY)
    assert len(saved) == 1
    assert saved[0]['snapshot']['appointment_canceled'] is True
    assert saved[0]['submitted_at'] is None
    assert saved[0]['draft']['dispo'] == ''
    with pytest.raises(LookupError, match='no MOD sheets'):
        service.export_all_pdf(DAY)


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


def test_canceled_without_notes_does_not_submit_old_local_disposition(tmp_path):
    service, repo, source, _ = _setup(tmp_path)
    service.refresh(DAY)
    repo.save_draft(DAY, WO, clean_draft({'dispo': 'pns'}), 0)
    repo.select_mod(DAY, MOD, 'Sales Manager')
    source['value'] = CANCELED
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'] == []
    assert repo.sheets(DAY)[0]['draft']['dispo'] == 'pns'  # Keep local copy.
    with pytest.raises(ValueError, match='No unsubmitted'):
        repo.enqueue_submit(DAY)
    with pytest.raises(ValueError, match='Selected Work Orders changed'):
        repo.enqueue_submit(DAY, [WO])
    assert repo.day(DAY)['submitting'] == 0


def test_reactivated_appointment_without_notes_reappears(tmp_path):
    service, repo, source, _ = _setup(tmp_path, CANCELED)
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'] == []
    source['value'] = ACTIVE
    service.refresh(DAY)
    assert len(service.snapshot(DAY)['sheets']) == 1
    assert service.export_all_pdf(DAY) == (WO,)


def test_canceled_lead_without_notes_hidden_even_if_appointment_active(tmp_path):
    canceled_lead = replace(ACTIVE, sales_lead_status='Canceled')
    service, repo, _, _ = _setup(tmp_path, canceled_lead, remote={
        'dispo': 'cxl', 'lead_status': 'Canceled',
    })
    service.refresh(DAY)
    assert service.snapshot(DAY)['sheets'] == []
    # Salesforce-derived CXL is still stored; never delete the source result.
    assert repo.sheets(DAY)[0]['draft']['dispo'] == 'cxl'
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


def test_only_real_notes_preserve_canceled_visibility():
    snapshot = {'appointment_canceled': True, 'sales_lead_status': ''}
    assert canceled_without_notes(snapshot, clean_draft({
        'dispo': 'pns', 'numbers': '23000', 'docs': True,
    }))
    assert not canceled_without_notes(snapshot, clean_draft({
        'notes': 'MOD note',
    }))
    assert not canceled_without_notes(snapshot, clean_draft({
        'note_runs': [{'text':'Written locally', 'red': True}],
        'notes': 'Written locally',
    }))
