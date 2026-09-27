"""Scans reconcile one dated placeholder only after their content is trusted."""
import pytest

from printer_app.gallery.repository import GalleryRepository


DAY = '2026-09-21'
OTHER_DAY = '2026-09-22'
NUMBER = '02000001'
OTHER_NUMBER = '02000002'


@pytest.fixture
def repository(tmp_path):
    result = GalleryRepository(tmp_path / 'gallery.db')
    result.initialize()
    return result


def _entry(ident, *, origin='scan', day=DAY, number=NUMBER, pending=False,
           notes='legacy', revision=None, replace=False):
    return dict(id=ident, import_id='batch-' + ident, filename='fixture.pdf', page=1, part=1,
                text=f'Work Order Number: {number}\nLead Name: Example Customer',
                document_date=day, date_status='reference' if origin == 'morning' else 'printed',
                bytes=100, created=1, origin=origin, image_revision=revision or ident,
                recognition_revision=1, work_order_number='' if pending else number,
                work_order_candidates=(number,) if pending else (),
                mod_notes_status=notes, replace_existing=replace)


def _save(repo, ident, **kwargs):
    entry = _entry(ident, **kwargs)
    repo.enqueue(entry['import_id'], entry['filename'], origin=entry['origin'])
    repo.finish(entry['import_id'], [entry])
    return entry


def _accept(repo, ident='scan', *, day=OTHER_DAY, revision=None, number=NUMBER):
    return repo.apply_validated_work_order_reference(
        ident, (number,), number, 'source-order',
        f'Work Order Number: {number}\nLead Name: Source Customer',
        'Source Customer', 'Example Address', 'Example Rep', day, 'source-lead', 'Sold',
        expected_image_revision=revision or ident)


def _enrich(repo, ident, day=OTHER_DAY):
    return repo.apply_work_order_reference(
        ident, NUMBER, 'source-order', 'Lead Name: Source Customer',
        'Source Customer', 'Example Address', 'Example Rep', day, 'source-lead', 'Sold')


def test_partial_scan_does_not_remove_other_morning_cards_or_close_day(repository):
    _save(repository, 'first', origin='morning')
    _save(repository, 'other', origin='morning', number=OTHER_NUMBER)
    _save(repository, 'scan', pending=True, notes='present')
    assert repository.item('first') is not None
    assert repository.item('other') is not None

    assert _accept(repository) == 1
    assert repository.item('first') is None
    assert repository.item('other')['origin'] == 'morning'
    _save(repository, 'later-morning', origin='morning', number='02000003')
    assert repository.item('later-morning')['origin'] == 'morning'
    assert repository.retired_morning_cards() == ['first']


def test_pending_scan_keeps_id_and_merges_only_same_day_work_order_user_history(repository):
    _save(repository, 'morning', origin='morning')
    _save(repository, 'other-day', origin='morning', day=OTHER_DAY)
    _save(repository, 'other-order', origin='morning', number=OTHER_NUMBER)
    repository.add_note('morning', 'note-id', 'Office', 'Keep appointment note')
    repository.add_note('morning', 'call-id', 'Office', 'Called +13605550100.')
    repository.add_note('morning', 'message-id', 'Office', 'Texted +13605550100.')
    repository.add_note('other-day', 'other-note', 'Office', 'Different appointment')
    old_notes = repository.item('morning')['notes']
    _save(repository, 'scan', pending=True, notes='present')

    assert _accept(repository) == 1

    scan = repository.item('scan')
    assert scan['id'] == 'scan'
    assert scan['image_revision'] == 'scan'
    assert scan['document_date'] == DAY
    assert scan['date_status'] == 'printed'
    assert scan['notes'] == old_notes
    assert 'Keep appointment note' in scan['notes_text']
    assert 'Called +13605550100.' in scan['notes_text']
    assert repository.item('other-day')['notes'][0]['id'] == 'other-note'
    assert repository.item('other-order') is not None
    repository.forget('morning')
    assert repository.item('scan')['notes'] == old_notes
    assert _accept(repository) == 0
    assert repository.item('scan')['notes'] == old_notes


def test_stale_confirmation_cannot_retire_placeholder_or_move_its_notes(repository):
    _save(repository, 'morning', origin='morning')
    repository.add_note('morning', 'note-id', 'Office', 'Keep it here')
    _save(repository, 'scan', pending=True, notes='present')
    before = repository.item('morning')

    assert _accept(repository, revision='obsolete-image') == 0
    assert repository.item('morning') == before
    assert repository.retired_morning_cards() == []


def test_no_printed_scan_date_does_not_reconcile_using_only_current_source_date(repository):
    _save(repository, 'morning', origin='morning')
    _save(repository, 'scan', day=None, pending=True, notes='present')

    assert _accept(repository, day=DAY) == 1
    assert repository.item('scan')['document_date'] == DAY
    assert repository.item('morning')['origin'] == 'morning'
    assert repository.retired_morning_cards() == []
    assert _enrich(repository, 'scan', day=DAY) == 1
    assert repository.item('morning')['origin'] == 'morning'
    assert repository.retired_morning_cards() == []


@pytest.mark.parametrize('origin,status', [('scan', 'printed'), ('scan', 'confirmed'), ('morning', 'reference')])
def test_direct_source_refresh_preserves_existing_batch_date(repository, origin, status):
    _save(repository, 'card', origin=origin)
    with repository.connect() as c:
        c.execute('UPDATE items SET date_status=? WHERE id=?', (status, 'card'))

    assert _enrich(repository, 'card') == 1

    card = repository.item('card')
    assert (card['document_date'], card['date_status']) == (DAY, status)
    assert card['sales_lead_status'] == 'Sold'


def test_source_date_only_fills_a_missing_card_date(repository):
    _save(repository, 'card', day=None)
    assert _enrich(repository, 'card') == 1
    card = repository.item('card')
    assert (card['document_date'], card['date_status']) == (OTHER_DAY, 'reference')


def test_late_morning_duplicates_are_skipped_per_order_and_existing_scans_are_unchanged(repository):
    _save(repository, 'scan', notes='present')
    before = repository.item('scan')
    _save(repository, 'duplicate-morning', origin='morning')
    _save(repository, 'new-morning', origin='morning', number=OTHER_NUMBER)
    assert repository.item('duplicate-morning') is None
    assert repository.item('new-morning') is not None
    assert repository.item('scan') == before


def test_confirmed_scan_replacement_preserves_existing_id_and_notes(repository):
    _save(repository, 'card', origin='morning')
    repository.add_note('card', 'note-id', 'Office', 'Keep me')
    _save(repository, 'card', notes='present', revision='second-image', replace=True)
    row = repository.item('card')
    assert row['origin'] == 'scan'
    assert row['image_revision'] == 'second-image'
    assert row['notes'][0]['id'] == 'note-id'


def test_unknown_notes_prevent_all_identity_activation_and_leave_placeholder(repository):
    _save(repository, 'morning', origin='morning')
    _save(repository, 'scan', pending=True, notes='unknown')
    assert _accept(repository) == 0
    with pytest.raises(ValueError, match='MOD Notes'):
        repository.approve_import_item('batch-scan', 'scan')
    repository.correct_import_item_lead('batch-scan', 'scan', 'Corrected Name', 'corrected name')
    assert repository.item('scan') is None
    repository.correct_import_item_work_order('batch-scan', 'scan', NUMBER)
    assert _enrich(repository, 'scan') == 0
    assert repository.item('scan') is None
    assert repository.item('morning') is not None
    retry = repository.recognition_candidate(10**12)
    assert retry['id'] == 'scan'
    assert retry['work_order_key'] == NUMBER
    assert retry['mod_notes_status'] == 'unknown'


def test_unknown_scan_cannot_replace_an_existing_image_at_persistence_boundary(repository):
    _save(repository, 'card', origin='morning')
    before = repository.item('card')
    with pytest.raises(ValueError, match='cannot replace'):
        _save(repository, 'card', notes='unknown', revision='unreadable', replace=True)
    assert repository.item('card') == before


def test_unknown_notes_retries_back_off_and_stop_after_three_attempts(repository):
    _save(repository, 'scan', pending=True, notes='unknown')
    for attempt in range(3):
        assert repository.recognition_candidate(10**12)['id'] == 'scan'
        assert repository.update_notes_status('scan', 'scan', 'unknown') == 1
        assert repository.recognition_candidate(0) is None
    assert repository.recognition_candidate(10**12) is None
    assert repository.import_item('batch-scan', 'scan')['state'] == 'REVIEW'


def test_notes_retry_preserves_pending_identity_and_stale_retry_cannot_publish(repository):
    _save(repository, 'morning', origin='morning')
    _save(repository, 'scan', pending=True, notes='unknown')
    before = repository.work_order_candidate_items()[0]
    assert repository.update_notes_status('scan', 'obsolete-image', 'present') == 0
    assert repository.work_order_candidate_items()[0] == before
    assert repository.update_notes_status('scan', 'scan', 'present') == 1
    assert repository.item('scan') is None
    assert repository.work_order_candidate_items()[0]['candidates'] == before['candidates']
    assert _accept(repository) == 1
    assert repository.item('scan')['mod_notes_status'] == 'present'
    assert repository.retired_morning_cards() == ['morning']


def test_notes_retry_after_manual_work_order_edit_keeps_the_manual_identity(repository):
    _save(repository, 'scan', pending=True, notes='unknown')
    repository.correct_import_item_work_order('batch-scan', 'scan', OTHER_NUMBER)
    assert repository.reference_item('scan')['document_date'] == DAY
    assert repository.update_notes_status('scan', 'scan', 'present') == 1
    assert repository.reference_item('scan')['work_order_number'] == OTHER_NUMBER
    assert repository.approve_import_item('batch-scan', 'scan')
    assert repository.item('scan')['work_order_number'] == OTHER_NUMBER


def test_unknown_notes_with_manually_saved_identity_do_not_block_missing_morning_card(repository):
    _save(repository, 'scan', pending=True, notes='unknown')
    repository.correct_import_item_work_order('batch-scan', 'scan', NUMBER)
    assert repository.card_for_work_order(DAY, NUMBER) is None
    _save(repository, 'morning', origin='morning')
    assert repository.item('morning')['origin'] == 'morning'
    assert repository.item('scan') is None


def test_active_work_order_correction_preserves_manually_confirmed_date(repository):
    _save(repository, 'card')
    repository.correct_date('card', OTHER_DAY)
    repository.correct_work_order('card', OTHER_NUMBER)
    card = repository.item('card')
    assert (card['document_date'], card['date_status']) == (OTHER_DAY, 'confirmed')


@pytest.mark.parametrize('import_edit', [False, True])
def test_work_order_correction_clears_only_old_source_derived_scan_date(repository, import_edit):
    _save(repository, 'card', day=None)
    assert _enrich(repository, 'card', day=OTHER_DAY) == 1
    assert repository.item('card')['date_status'] == 'reference'

    if import_edit:
        repository.correct_import_item_work_order('batch-card', 'card', OTHER_NUMBER)
    else:
        repository.correct_work_order('card', OTHER_NUMBER)

    card = repository.item('card')
    assert (card['document_date'], card['date_status']) == (None, 'needs-date')
    assert repository.apply_work_order_reference(
        'card', OTHER_NUMBER, 'new-source', 'Lead Name: Correct Customer',
        'Correct Customer', '', '', DAY, 'new-lead', 'Sold') == 1
    card = repository.item('card')
    assert (card['document_date'], card['date_status']) == (DAY, 'reference')


@pytest.mark.parametrize('import_edit', [False, True])
def test_work_order_correction_keeps_morning_batch_reference_date(repository, import_edit):
    _save(repository, 'card', origin='morning')
    if import_edit:
        repository.correct_import_item_work_order('batch-card', 'card', OTHER_NUMBER)
    else:
        repository.correct_work_order('card', OTHER_NUMBER)
    card = repository.item('card')
    assert (card['document_date'], card['date_status']) == (DAY, 'reference')


@pytest.mark.parametrize('import_edit', [False, True])
def test_manual_work_order_correction_reconciles_the_matching_printed_day_placeholder(repository, import_edit):
    _save(repository, 'morning', origin='morning')
    repository.add_note('morning', 'note-id', 'Office', 'Keep corrected appointment history')
    _save(repository, 'scan', number=OTHER_NUMBER, notes='present')

    if import_edit:
        repository.correct_import_item_work_order('batch-scan', 'scan', NUMBER)
    else:
        repository.correct_work_order('scan', NUMBER)

    assert repository.retired_morning_cards() == ['morning']
    assert repository.item('scan')['notes'][0]['id'] == 'note-id'
    assert repository.item('scan')['document_date'] == DAY


def test_manually_confirmed_date_reconciles_previously_undated_scan_only_with_matching_placeholder(repository):
    _save(repository, 'morning', origin='morning')
    _save(repository, 'other-day', origin='morning', day=OTHER_DAY)
    _save(repository, 'other-order', origin='morning', number=OTHER_NUMBER)
    repository.add_note('morning', 'note-id', 'Office', 'Called +13605550100.')
    _save(repository, 'scan', day=None, pending=True, notes='present')
    assert _accept(repository, day=DAY) == 1
    assert repository.item('morning') is not None

    repository.correct_date('scan', DAY)

    assert repository.retired_morning_cards() == ['morning']
    assert repository.item('scan')['date_status'] == 'confirmed'
    assert repository.item('scan')['notes'][0]['id'] == 'note-id'
    assert repository.item('other-day') is not None
    assert repository.item('other-order') is not None


def test_manual_approval_reconciles_only_after_notes_and_identity_are_confirmed(repository):
    _save(repository, 'morning', origin='morning')
    repository.add_note('morning', 'note-id', 'Office', 'Texted +13605550100.')
    _save(repository, 'scan', pending=True, notes='unknown')
    repository.correct_import_item_work_order('batch-scan', 'scan', NUMBER)
    assert repository.item('morning') is not None
    assert repository.update_notes_status('scan', 'scan', 'present') == 1
    assert repository.item('morning') is not None

    assert repository.approve_import_item('batch-scan', 'scan')

    assert repository.retired_morning_cards() == ['morning']
    assert repository.item('scan')['notes'][0]['id'] == 'note-id'
    assert not repository.approve_import_item('batch-scan', 'scan')


@pytest.mark.parametrize('stored,expected', [
    ('[]', ()), ('null', ()), ('"02000001"', ()),
    ('["02000001", 1, "bad"]', (NUMBER,)),
])
def test_recognition_queue_decodes_candidates_before_service_truth_checks(repository, stored, expected):
    _save(repository, 'scan', pending=True, notes='unknown')
    with repository.connect() as c:
        c.execute('UPDATE items SET work_order_candidates=? WHERE id=?', (stored, 'scan'))
    row = repository.recognition_candidate(10**12)
    assert row['work_order_candidates'] == expected
    assert bool(row['work_order_candidates']) == bool(expected)


def test_blank_notes_discard_only_claims_unchanged_unknown_scan(repository):
    _save(repository, 'morning', origin='morning')
    _save(repository, 'known', notes='present', number=OTHER_NUMBER)
    _save(repository, 'scan', pending=True, notes='unknown')
    assert repository.discard_candidate('scan', 'obsolete') == 0
    assert repository.discard_candidate('morning', 'morning') == 0
    assert repository.discard_candidate('known', 'known') == 0
    assert repository.discard_candidate('scan', 'scan') == 1
    assert repository.discarded_scan_candidates() == ['scan']
    assert repository.item('morning') is not None
    assert repository.item('known') is not None
    repository.forget('scan')
    assert repository.discarded_scan_candidates() == []


def test_publication_reports_actual_saved_rows_and_unknown_notes_separately(repository):
    _save(repository, 'scan', notes='present')
    duplicate = _entry('duplicate', origin='morning')
    unknown = _entry('unknown', pending=True, notes='unknown', number=OTHER_NUMBER)
    for entry in (duplicate, unknown):
        entry['import_id'] = 'combined'
    repository.enqueue('combined', 'fixture.pdf')
    repository.finish('combined', [duplicate, unknown], publication=dict(
        prepared=5, saved=99, skipped_existing=1, skipped_blank_notes=2, needs_notes_review=99))
    job = repository.import_job('combined')
    assert job['progress']['publication'] == dict(
        prepared=5, saved=1, skipped_existing=2, skipped_blank_notes=2, needs_notes_review=1)
    assert job['progress']['stage'] == 'complete'
    assert '1 saved' in job['progress']['message']
    assert '2 already present' in job['progress']['message']
    assert job['items'][0]['mod_notes_status'] == 'unknown'
    assert job['published'] == 0
    assert job['pending_review'] == 1


def test_migration_keeps_old_day_marker_inert_and_does_not_review_legacy_cards(repository):
    _save(repository, 'accepted')
    with repository.connect() as c:
        assert c.execute("SELECT 1 FROM sqlite_master WHERE name='scan_days'").fetchone() is None
        c.execute('CREATE TABLE scan_days(day TEXT PRIMARY KEY,reconciled REAL NOT NULL)')
        c.execute('INSERT INTO scan_days VALUES(?,1)', (DAY,))
        c.execute('ALTER TABLE items DROP COLUMN mod_notes_status')
    repository.initialize()
    assert repository.item('accepted')['mod_notes_status'] == 'legacy'
    _save(repository, 'new-morning', origin='morning', number=OTHER_NUMBER)
    assert repository.item('new-morning') is not None
    with repository.connect() as c:
        assert dict(c.execute('SELECT * FROM scan_days').fetchone()) == dict(day=DAY, reconciled=1.0)
