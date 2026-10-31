"""Local-first MOD Resulting rules: real SQLite, no live Salesforce writes."""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.service import ResultingDailyPull, ResultingService

DAY = '2026-10-30'
WORK = '0WO000000000001AAA'
LEAD = '00Q000000000001AAA'
RECORD = ModSheetRecord(
    source_id=WORK, work_order_number='00001234', lead_source_id=LEAD,
    product_interest='Roofing', lead_name='Test Client',
)


def _service(tmp_path, initial=None):
    db = Database(tmp_path / 'printer.sqlite')
    repo = ResultingRepository(db)
    remote = {'value': clean_draft(initial or {})}

    class Source:
        def records(self, **kwargs):
            return [RECORD]

    class Writer:
        def read_results(self, records):
            return {WORK: remote['value']}

    service = ResultingService(
        repo, Source(), Writer(),
        SimpleNamespace(settings=lambda: SimpleNamespace(market_segment='Olympia')),
        'America/Los_Angeles',
    )
    return service, repo, db, remote


def _draft(**updates):
    return clean_draft(updates)


def test_unchanged_salesforce_refresh_preserves_every_local_field(tmp_path):
    service, repo, _, remote = _service(tmp_path)
    service.refresh(DAY)
    edited = _draft(
        dispo='pns', notes='Local black and red text', redlines='Extra redline',
        note_runs=[{'text':'Local black and red text','red':True}],
        need='Our need', result_detail='Price Objection',
        additional_products=True,
        product_results={'Roofing':{'result':'np','detail':'Not Home','price':'','deposit':''}},
    )
    repo.save_draft(DAY, WORK, edited, 0)
    service.refresh(DAY)
    assert repo.sheets(DAY)[0]['draft'] == edited
    assert repo.sheets(DAY)[0]['submitted_at'] is None


def test_refresh_changes_only_fields_actually_changed_in_salesforce(tmp_path):
    service, repo, _, remote = _service(tmp_path, {'need':'Original remote need'})
    service.refresh(DAY)
    edited = _draft(dispo='pns', need='Local need',
                    notes='Local MOD note', redlines='Local redline')
    repo.save_draft(DAY, WORK, edited, 0)
    remote['value'] = _draft(need='Changed in Salesforce')
    service.refresh(DAY)
    result = repo.sheets(DAY)[0]['draft']
    assert result == dict(edited, need='Changed in Salesforce')
    # A second Refresh of the identical remote state changes nothing.
    revision = repo.sheets(DAY)[0]['revision']
    service.refresh(DAY)
    assert repo.sheets(DAY)[0]['revision'] == revision


def test_cancellation_is_applied_only_on_manual_refresh(tmp_path):
    service, repo, _, remote = _service(tmp_path)
    service.refresh(DAY)
    edited = _draft(dispo='pns', notes='Keep these MOD notes',
                    redlines='Keep this ink')
    repo.save_draft(DAY, WORK, edited, 0)
    remote['value'] = _draft(dispo='cxl', lead_status='Canceled')
    assert repo.sheets(DAY)[0]['draft']['dispo'] == 'pns'
    service.refresh(DAY)
    canceled = repo.sheets(DAY)[0]
    assert canceled['draft']['dispo'] == 'cxl'
    assert canceled['draft']['notes'] == 'Keep these MOD notes'
    assert canceled['draft']['redlines'] == 'Keep this ink'
    assert canceled['submitted_at'] == -1.0
    # No newer Salesforce change: an explicitly overridden local draft stays.
    revision = repo.override(DAY, WORK, canceled['revision'])
    edited_again = _draft(dispo='pns', notes='Keep these MOD notes',
                          redlines='Keep this ink')
    repo.save_draft(DAY, WORK, edited_again, revision)
    service.refresh(DAY)
    assert repo.sheets(DAY)[0]['draft'] == edited_again
    assert repo.sheets(DAY)[0]['override_active'] == 1


def test_clear_keeps_recoverable_note_checkpoint(tmp_path):
    service, repo, db, _ = _service(tmp_path, {'notes':'Salesforce baseline'})
    service.refresh(DAY)
    edited = _draft(notes='Local notes', redlines='Local redline',
                    note_runs=[{'text':'Local notes','red':True}], dispo='pns')
    repo.save_draft(DAY, WORK, edited, 0)
    assert service.clear_local(DAY) == 1
    assert repo.sheets(DAY)[0]['draft']['notes'] == 'Salesforce baseline'
    backups = db.rows('''SELECT reason,notes,redlines,note_runs
        FROM mod_result_note_backups WHERE day=? AND work_order_id=? ORDER BY id DESC''',
        (DAY, WORK))
    assert backups
    assert backups[0]['reason'] == 'clear'
    assert backups[0]['notes'] == 'Local notes'
    assert backups[0]['redlines'] == 'Local redline'
    assert 'Local notes' in backups[0]['note_runs']


def test_8am_automatic_pull_never_replaces_existing_local_work(tmp_path):
    service, repo, _, _ = _service(tmp_path)
    service.refresh(DAY)
    repo.save_draft(DAY, WORK, _draft(dispo='pns', notes='Morning local note'), 0)
    clock = datetime(2026, 10, 30, 8, 15, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    daily = ResultingDailyPull(service)
    assert not daily.due(clock)
    assert repo.sheets(DAY)[0]['draft']['notes'] == 'Morning local note'


def test_legacy_local_edits_survive_first_refresh_without_baseline(tmp_path):
    service, repo, _, remote = _service(tmp_path)
    repo.refresh(DAY, [RECORD])
    repo.save_draft(DAY, WORK, _draft(dispo='pns', notes='Legacy saved note',
                                      need='My need'), 0)
    remote['value'] = _draft(need='Salesforce snapshot')
    service.refresh(DAY)
    row = repo.sheets(DAY)[0]['draft']
    assert row['dispo'] == 'pns'
    assert row['need'] == 'My need'
    assert row['notes'] == 'Legacy saved note'
    remote['value'] = _draft(need='Actual changed need')
    service.refresh(DAY)
    assert repo.sheets(DAY)[0]['draft']['need'] == 'Actual changed need'
    assert repo.sheets(DAY)[0]['draft']['notes'] == 'Legacy saved note'


def test_incomplete_salesforce_refresh_never_changes_local_data(tmp_path):
    service, repo, _, _ = _service(tmp_path)
    service.refresh(DAY)
    repo.save_draft(DAY, WORK, _draft(dispo='pns', notes='Unsaved elsewhere'), 0)
    before = repo.sheets(DAY)
    service.writer.read_results = lambda records: {}
    with pytest.raises(ValueError, match='incomplete records'):
        service.refresh(DAY)
    assert repo.sheets(DAY) == before
