"""Submission isolation, durable unknown outcomes, and the live Notes counter."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import (
    ResultingWriteRejected, clean_draft, mod_note_text, text_units,
)
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.service import ResultingService


DAY = '2026-10-27'
MOD = '005000000000001AAA'


class Writer:
    def __init__(self):
        self.events = []
        self.attempted = []
        self.applied = []
        self.reject = set()
        self.timeout = set()
        self.verifications = []
        self.verification_plans = []
        self.verified_outcome = 'ready'

    @staticmethod
    def submission_group_key(payload):
        return payload['lead_id'][:15]

    def prepare(self, payloads):
        self.events.append(('prepare', [p['work_order_id'] for p in payloads]))
        if any('INVALID' in p['draft']['notes'] for p in payloads):
            raise ResultingWriteRejected('MOD Notes exceeds the destination limit.')
        return payloads

    def apply(self, plan):
        ident = plan['work_order_id']
        self.events.append(('apply', ident))
        self.attempted.append(ident)
        if ident in self.reject:
            raise ResultingWriteRejected('Work Order update was rolled back.')
        if ident in self.timeout:
            raise TimeoutError('Transport timed out after a possible commit.')
        self.applied.append(plan)

    def reconcile_submission(self, payload, *, verification=None):
        self.events.append(('verify', payload['work_order_id']))
        self.verifications.append(payload)
        self.verification_plans.append(verification)
        if isinstance(self.verified_outcome, Exception):
            raise self.verified_outcome
        return self.verified_outcome


def _service(tmp_path, leads=(1, 2, 1)):
    records = [ModSheetRecord(
        source_id='0WO' + str(index).zfill(12) + 'AAA',
        lead_source_id='00Q' + str(lead).zfill(12) + 'AAA',
        work_order_number=str(index).zfill(8),
        product_interest='Roofing',
    ) for index, lead in enumerate(leads, 1)]
    writer = Writer()
    repository = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    repository.refresh(DAY, records, market_segment='Olympia')
    repository.select_mod(DAY, MOD, 'Test MOD')
    for index, record in enumerate(records, 1):
        repository.save_draft(DAY, record.source_id, clean_draft({
            'dispo': 'pns', 'notes': 'Keep note ' + str(index),
            'numbers': str(index * 100),
        }), 0)
    service = ResultingService(repository,
        SimpleNamespace(records=lambda **kwargs: records), writer,
        SimpleNamespace(settings=lambda: SimpleNamespace(market_segment='Olympia')),
        'America/Los_Angeles', allow_salesforce_writes=True)
    service.day = lambda: DAY
    return service, repository, writer, records


def _run(service, repository, selected=None):
    service.enqueue(DAY, selected)
    result = service.process_next_submission()
    status = repository.latest_submission(DAY)
    assert status['pending'] == status['processing'] == 0
    assert repository.day(DAY)['submitting'] == 0
    return result, status


def _unresolved(repository, day, work_order_id):
    return next((attempt for attempt in repository.unresolved_submission_attempts()
                 if attempt['day'] == day and attempt['work_order_id'] == work_order_id), None)


def test_group_preflight_rejection_preserves_drafts_and_submits_unrelated_lead(tmp_path):
    service, repo, writer, records = _service(tmp_path)
    bad = repo.sheets(DAY)[2]
    repo.save_draft(DAY, records[2].source_id,
                    dict(bad['draft'], notes='INVALID but safely saved'), bad['revision'])
    drafts = [row['draft'] for row in repo.sheets(DAY)]
    result, status = _run(service, repo)
    assert not result['ok']
    assert [i['state'] for i in status['items']] == ['rejected', 'submitted', 'rejected']
    assert (status['submitted'], status['rejected'], status['failed']) == (1, 2, 2)
    assert writer.attempted == [records[1].source_id]
    assert [event[0] for event in writer.events] == ['prepare', 'prepare', 'apply']
    assert [row['draft'] for row in repo.sheets(DAY)] == drafts
    assert 'no writes performed' in status['items'][0]['error']


@pytest.mark.parametrize('background', [False, True])
def test_definitive_rejection_blocks_same_lead_but_continues_other_lead(tmp_path, background):
    service, repo, writer, records = _service(tmp_path)
    writer.reject.add(records[0].source_id)
    if background:
        result, status = _run(service, repo)
        assert not result['ok']
        assert [i['state'] for i in status['items']] == ['rejected', 'submitted', 'not_submitted']
    else:
        with pytest.raises(ResultingWriteRejected, match='rolled back'):
            service.submit(DAY)
    assert writer.attempted == [records[0].source_id, records[1].source_id]
    rows = repo.sheets(DAY)
    assert rows[0]['submitted_at'] is None
    assert rows[1]['submitted_at'] > 0
    assert rows[2]['submitted_at'] is None
    assert [event[0] for event in writer.events[:2]] == ['prepare', 'prepare']


def test_unknown_write_stops_remaining_batch_without_terminal_pending_items(tmp_path):
    service, repo, writer, records = _service(tmp_path)
    writer.timeout.add(records[0].source_id)
    before = [row['draft'] for row in repo.sheets(DAY)]
    result, status = _run(service, repo)
    assert not result['ok']
    assert [i['state'] for i in status['items']] == ['uncertain', 'not_submitted', 'not_submitted']
    assert (status['uncertain'], status['not_submitted']) == (1, 2)
    assert writer.attempted == [records[0].source_id]
    assert [row['draft'] for row in repo.sheets(DAY)] == before
    frozen = _unresolved(repo, DAY, records[0].source_id)
    assert frozen['payload']['draft'] == before[0]
    assert frozen['plan']['work_order_id'] == records[0].source_id


def test_unknown_retry_verifies_frozen_payload_and_skips_already_committed_write(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    writer.timeout.clear()
    writer.verified_outcome = 'submitted'
    result, status = _run(service, repo)
    assert result['ok'] and status['submitted'] == 1
    assert len(writer.attempted) == 1
    assert writer.verifications[0]['draft']['notes'] == 'Keep note 1'
    assert writer.verification_plans[0]['work_order_id'] == records[0].source_id
    assert repo.sheets(DAY)[0]['submitted_at'] > 0
    assert _unresolved(repo, DAY, records[0].source_id) is None


def test_edited_unknown_retry_verifies_prior_attempt_before_fresh_plan(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    saved = repo.sheets(DAY)[0]
    repo.save_draft(DAY, records[0].source_id,
                    dict(saved['draft'], notes='Corrected and preserved'), saved['revision'])
    writer.timeout.clear()
    writer.events.clear()
    result, status = _run(service, repo)
    assert result['ok'] and status['submitted'] == 1
    assert [event[0] for event in writer.events] == ['verify', 'prepare', 'apply']
    assert writer.verifications[0]['draft']['notes'] == 'Keep note 1'
    assert writer.applied[0]['draft']['notes'] == 'Corrected and preserved'


def test_unavailable_verification_cannot_replay_unknown_write(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    writer.timeout.clear()
    writer.reconcile_submission = None
    result, status = _run(service, repo)
    assert not result['ok'] and status['uncertain'] == 1
    assert len(writer.attempted) == 1
    assert 'still needs verification' in status['items'][0]['error']
    assert _unresolved(repo, DAY, records[0].source_id) is not None


def test_legacy_unknown_retry_requires_fresh_verification_without_frozen_payload(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    queued = service.enqueue(DAY)
    repo.claim_submission()
    repo.submission_item(queued['job_id'], records[0].source_id, 'uncertain', 'Old timeout')
    repo.finish_submission_job(queued['job_id'], 'Old timeout')
    repo.finish_submit(DAY)
    result, status = _run(service, repo)
    assert result['ok'] and status['submitted'] == 1
    assert [event[0] for event in writer.events] == ['verify', 'prepare', 'apply']
    assert writer.verifications[0]['work_order_id'] == records[0].source_id


def test_corrected_definite_rejection_can_retry_without_unknown_outcome_handshake(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    writer.reject.add(records[0].source_id)
    _run(service, repo)
    writer.reject.clear()
    row = repo.sheets(DAY)[0]
    repo.save_draft(DAY, records[0].source_id,
                    dict(row['draft'], notes='Corrected note'), row['revision'])
    result, status = _run(service, repo)
    assert result['ok'] and status['submitted'] == 1
    assert writer.verifications == []
    assert writer.applied[0]['draft']['notes'] == 'Corrected note'


def test_restart_finishes_unattempted_items_without_replaying_transport(tmp_path):
    service, repo, writer, records = _service(tmp_path)
    queued = service.enqueue(DAY)
    repo.claim_submission()
    repo.submission_item(queued['job_id'], records[0].source_id, 'processing')
    repo.interrupt_abandoned_submissions()
    status = repo.latest_submission(DAY)
    assert [i['state'] for i in status['items']] == ['uncertain', 'not_submitted', 'not_submitted']
    assert status['pending'] == status['processing'] == 0
    assert writer.attempted == []


def test_selecting_another_work_order_cannot_bypass_same_lead_unknown_attempt(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1, 1, 2))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    writer.timeout.clear()
    writer.verified_outcome = RuntimeError('Fresh verification is unavailable.')
    result, status = _run(service, repo, [records[1].source_id])
    assert not result['ok']
    assert status['items'][0]['state'] == 'not_submitted'
    assert writer.attempted == [records[0].source_id]
    assert writer.verifications[-1]['work_order_id'] == records[0].source_id
    assert 'unverified earlier submission' in status['items'][0]['error']


def test_same_lead_ready_verification_allows_selected_peer_without_claiming_prior_success(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1, 1))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    writer.timeout.clear()
    writer.events.clear()
    result, status = _run(service, repo, [records[1].source_id])
    assert result['ok'] and status['submitted'] == 1
    assert [event[0] for event in writer.events] == ['verify', 'prepare', 'apply']
    assert writer.verifications[-1]['work_order_id'] == records[0].source_id
    assert writer.attempted == [records[0].source_id, records[1].source_id]
    assert repo.sheets(DAY)[0]['submitted_at'] is None
    assert _unresolved(repo, DAY, records[0].source_id) is not None


def test_unrelated_selected_lead_is_not_blocked_by_another_leads_unknown_attempt(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1, 2))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    writer.timeout.clear()
    writer.verified_outcome = RuntimeError('The unrelated Lead is unavailable.')
    result, status = _run(service, repo, [records[1].source_id])
    assert result['ok'] and status['submitted'] == 1
    assert writer.verifications == []
    assert writer.attempted == [records[0].source_id, records[1].source_id]


def test_unknown_attempt_from_an_earlier_day_is_verified_before_same_lead_write(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    writer.timeout.clear()
    later_day = '2026-10-28'
    later = ModSheetRecord(source_id='0WO000000000099AAA',
        lead_source_id=records[0].lead_source_id, work_order_number='00000099',
        product_interest='Roofing')
    repo.refresh(later_day, [later], market_segment='Olympia')
    repo.select_mod(later_day, MOD, 'Test MOD')
    repo.save_draft(later_day, later.source_id,
                    clean_draft({'dispo':'pns', 'notes':'Next day note'}), 0)
    service.day = lambda: later_day
    service.enqueue(later_day, [later.source_id])
    result = service.process_next_submission()
    assert result['ok']
    assert writer.verifications[-1]['day'] == DAY
    assert writer.verifications[-1]['work_order_id'] == records[0].source_id
    assert writer.applied[-1]['work_order_id'] == later.source_id


def test_exact_recovery_of_unselected_attempt_retains_later_unsent_local_edits(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1, 1))
    writer.timeout.add(records[0].source_id)
    _, failed = _run(service, repo)
    writer.timeout.clear()
    old = repo.sheets(DAY)[0]
    repo.save_draft(DAY, records[0].source_id,
                    dict(old['draft'], notes='New unsent edit'), old['revision'])
    writer.verified_outcome = 'submitted'
    result, _ = _run(service, repo, [records[1].source_id])
    assert result['ok']
    recovered = repo.sheets(DAY)[0]
    assert recovered['submitted_at'] > 0 and recovered['override_active'] == 1
    assert recovered['draft']['notes'] == 'New unsent edit'
    assert repo.latest_submission(DAY, failed['id'])['items'][0]['state'] == 'submitted'
    old_notice = next(item for item in repo.recent_submission_items(DAY)
                     if item['work_order_id'] == records[0].source_id)
    assert old_notice['override_active'] == 1
    assert writer.attempted == [records[0].source_id, records[1].source_id]


def test_exact_old_receipt_keeps_changed_mod_update_eligible_until_current_write_finishes(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    writer.timeout.clear()
    writer.verified_outcome = 'submitted'
    changed_mod = '005000000000099AAA'
    repo.select_mod(DAY, changed_mod, 'Changed MOD')
    result, status = _run(service, repo)
    assert result['ok'] and status['submitted'] == 1
    assert writer.verifications[-1]['mod_id'] == MOD
    assert writer.applied[-1]['mod_id'] == changed_mod
    assert repo.sheets(DAY)[0]['override_active'] == 0


def test_edit_during_unselected_receipt_verification_remains_pending_for_override(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1, 1))
    writer.timeout.add(records[0].source_id)
    _run(service, repo)
    writer.timeout.clear()
    original = writer.reconcile_submission

    def verify_while_another_device_edits(payload, *, verification=None):
        row = repo.sheets(DAY)[0]
        repo.save_draft(DAY, records[0].source_id,
                        dict(row['draft'], notes='Typed while verification was running'), row['revision'])
        original(payload, verification=verification)
        return 'submitted'

    writer.reconcile_submission = verify_while_another_device_edits
    result, status = _run(service, repo, [records[1].source_id])
    assert result['ok'] and status['submitted'] == 1
    preserved = repo.sheets(DAY)[0]
    assert preserved['draft']['notes'] == 'Typed while verification was running'
    assert preserved['override_active'] == 1


def test_refresh_of_a_remote_disposition_does_not_confirm_unknown_historical_receipt(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    writer.timeout.add(records[0].source_id)
    _, failed = _run(service, repo)
    repo.refresh(DAY, records, external_drafts={records[0].source_id: clean_draft({'dispo':'pns'})})
    assert repo.latest_submission(DAY, failed['id'])['items'][0]['state'] == 'uncertain'
    assert _unresolved(repo, DAY, records[0].source_id) is not None


@pytest.mark.parametrize('original,incoming', [
    ({'numbers':'100\n80','prefix':'Start 100\nOffer 90\nFinal 80'},
     {'numbers':'100\n80','prefix':''}),
    ({'numbers':'100\n80','prefix':''},
     {'numbers':'100\n80','prefix':'100\n80'}),
    (None, {'numbers':'100\n80','prefix':''}),
])
def test_refresh_keeps_note_provenance_with_protected_local_notes(tmp_path, original, incoming):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    ident = records[0].source_id
    first = {'numbers':'100\n80', 'notes':'Original source text'}
    if original is not None:
        first['note_origin'] = original
    first = clean_draft(first)
    repo.refresh(DAY, records, external_drafts={ident:first}, clear_local=True)
    row = repo.sheets(DAY)[0]
    local = dict(row['draft'], notes='Local edited Notes must keep their own prefix')
    repo.save_draft(DAY, ident, local, row['revision'])
    expected = mod_note_text(local)
    remote = clean_draft({'numbers':'100\n80', 'notes':'Changed source text',
                          'note_origin':incoming})
    repo.refresh(DAY, records, external_drafts={ident:remote})
    actual = repo.sheets(DAY)[0]['draft']
    assert actual['notes'] == local['notes']
    assert actual.get('note_origin') == original
    assert mod_note_text(actual) == expected


def _counter_js():
    source = (Path(__file__).parents[1] / 'static' / 'mod_resulting' / 'sheet.js').read_text(encoding='utf-8')
    return 'function modNotesText(draft) {' + source.split(
        '  function modNotesText(draft) {', 1)[1].split('  function manualRedlinePreview(', 1)[0]


def test_recovered_receipt_notification_does_not_lock_unsent_override_edits():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed for the notification editor-state contract.')
    source = (Path(__file__).parents[1] / 'static' / 'mod_resulting' / 'sheet.js').read_text(encoding='utf-8')
    function = 'function markWorkOrderSubmitted(item) {' + source.split(
        '  function markWorkOrderSubmitted(item) {', 1)[1].split('  function renderNotifications(', 1)[0]
    script = function + '''
const assert = require('node:assert/strict');
const root = {dataset:{day:'2026-10-27'}};
const sheet = {dataset:{id:'a',submitted:'no'},
  querySelector(){throw new Error('Unsent edits must not be disabled.');}};
const sheets = [sheet];
markWorkOrderSubmitted({day:root.dataset.day,work_order_id:'a',state:'submitted',override_active:1});
assert.equal(sheet.dataset.submitted,'no');
'''
    subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', check=True)


def test_live_counter_matches_written_text_and_blocks_submit_without_truncation():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is needed for the browser text-counter contract.')
    cases = [
        {'numbers':'100\r\n80', 'notes':'Customer note'},
        {'numbers':'100\n80', 'notes':'100\n80\nExisting note'},
        {'numbers':'', 'notes':'Two emoji: \U0001f600\U0001f600'},
        {'numbers':'  100\r80  ', 'notes':'\r\nFirst\rSecond '},
        {'numbers':'100\n80', 'notes':'Annotated source and a middle 90 amount',
         'note_origin':{'numbers':'100\n80', 'prefix':''}},
        {'numbers':'100\n80', 'notes':'Customer note',
         'note_origin':{'numbers':'100\n80', 'prefix':'Start 100\nMid 90\nFinal 80'}},
        {'numbers':'200\n80', 'notes':'Changed numbers start a new prefix',
         'note_origin':{'numbers':'100\n80', 'prefix':'Start 100\nFinal 80'}},
        {'numbers':'100', 'notes':'Black text', 'redlines':'Manually typed red text'},
        {'numbers':'', 'notes':'', 'redlines':'Only manual red notes'},
        {'numbers':'100', 'notes':'Black text\nManual red text', 'redlines':'Manual red text'},
        {'numbers':'100\n80', 'notes':'Annotated source\nManual red text',
         'redlines':'Manual red text', 'note_origin':{'numbers':'100\n80','prefix':''}},
        {'numbers':'100', 'notes':'Black text', 'redlines':'First red line\r\nSecond red line '},
    ]
    script = _counter_js() + '''
const assert = require('node:assert/strict');
const root = {dataset:{noteLimit:'10'}};
let draft = {numbers:'100',notes:'Long note stays saved'};
const counter = {textContent:'',classList:{toggle(name,on){this[name]=on;}}};
const button = {disabled:false};
const sheet = {dataset:{submitted:'no',workNumber:'00000001'},
  querySelector(selector){return selector === '.mod-notes-counter' ? counter : button;}};
function serialize(){return draft;}
const cases = JSON.parse(process.argv[1]);
const counts = cases.map(value => ({text:modNotesText(value),length:modNotesText(value).length}));
assert.throws(() => validateModNotes([sheet]), /Your draft is saved/);
assert.equal(draft.notes, 'Long note stays saved');
assert.equal(button.disabled,true);
assert.match(counter.textContent,/over limit/);
draft = {numbers:'',notes:'Short'};
validateModNotes([sheet]);
assert.equal(button.disabled,false);
assert.equal(counter.textContent,'5 / 10 characters');
root.dataset.noteLimit='';
draft.notes='No metadata must not truncate or prevent preflight';
validateModNotes([sheet]);
assert.equal(button.disabled,false);
console.log(JSON.stringify(counts));
'''
    result = subprocess.run([node, '-e', script, json.dumps(cases)], capture_output=True,
                            text=True, encoding='utf-8', check=True)
    assert json.loads(result.stdout) == [
        {'text': mod_note_text(value), 'length': text_units(mod_note_text(value))}
        for value in cases
    ]
