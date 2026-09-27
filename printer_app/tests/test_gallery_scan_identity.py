"""New scan candidates become identity only after an exact normalized source match."""
import hashlib

import pytest

from printer_app.gallery.policy import clear_work_order_identity, printed_work_order_number
from printer_app.mod_sheet_contract import WorkOrderReference
from printer_app.tests.test_gallery_reference import DAY, _gallery


def _publish(gallery, *, raw='022788501', candidates=(), strict=True):
    job = {'id': 'a' * 64, 'filename': 'scan.pdf'}
    gallery.repository.enqueue(job['id'], job['filename'])
    directory = gallery.files.path('work', job['id'])
    directory.mkdir()
    (directory / 'card.png').write_bytes(b'original-scan')
    entry = dict(file='card.png', page=1, part=1, bytes=13,
                 text=f'Work Order Number: {raw}\nLead Name: Same Customer\n'
                      'Address: 123 Main Street\nPhone: 3605551212\n',
                 lead_text='Lead Name: Same Customer', document_date=DAY, date_status='printed',
                 mod_notes_present=True)
    if strict:
        entry['work_order_candidates'] = candidates
    lookup = gallery.publish(job, {'items': [entry]}, directory)
    ident = hashlib.sha256(f"{job['id']}:1:1".encode()).hexdigest()
    return ident, lookup


def _record(number='02278850', source='source-one'):
    return WorkOrderReference(source_id=source, work_order_number=number,
                              appointment_date=DAY, lead_name='Same Customer',
                              address='123 Main Street', phone='3605551212',
                              sales_lead_status='Sold', lead_source_id='lead-one')


@pytest.mark.parametrize('raw', ['0227885', '022788501', '02278850', '00000001'])
def test_explicit_empty_scan_candidates_never_reparse_raw_text_or_use_other_identity(tmp_path, raw):
    gallery = _gallery(tmp_path)
    gallery.publish_reference_snapshot(DAY, 'final', [_record()], 100)
    ident, lookup = _publish(gallery, raw=raw)
    item = gallery.repository.reference_item(ident)
    assert lookup == ()
    assert item['state'] == 'REVIEW'
    assert item['work_order_number'] == ''
    assert printed_work_order_number(item['text']) == ''
    assert 'Address: 123 Main Street' in item['text']
    assert gallery.import_job('a' * 64)['items'][0]['work_order_reads'][0]['text'].startswith(
        'Work Order Number: ' + raw)
    assert gallery.repair_missing_work_orders() == {'repaired': 0, 'review': 0}
    assert gallery.work_order_lookup_numbers() == []
    assert gallery.files.path('crops', ident).read_bytes() == b'original-scan'


@pytest.mark.parametrize('number', ['02278850', '00000007'])
def test_exact_source_confirmation_supplies_prepared_identity_without_scan_rules_in_repository(tmp_path, number):
    gallery = _gallery(tmp_path)
    gallery.publish_reference_snapshot(DAY, 'final', [_record(number)], 100)
    ident, lookup = _publish(gallery, raw='022788501', candidates=(number, number))
    assert lookup == (number,)
    item = gallery.item(ident)
    assert item['work_order_number'] == number
    assert printed_work_order_number(item['text']) == number
    assert item['state'] == 'ACTIVE'
    assert gallery.repository.import_item('a' * 64, ident)['work_order_candidates'] == ()


def test_valid_unconfirmed_candidates_stay_out_of_normalized_identity_until_source_matches(tmp_path):
    gallery = _gallery(tmp_path)
    ident, lookup = _publish(gallery, raw='02278850', candidates=('02278850', '02345678'))
    assert lookup == ('02278850', '02345678')
    assert gallery.repository.reference_item(ident)['work_order_number'] == ''
    assert printed_work_order_number(gallery.repository.reference_item(ident)['text']) == ''
    assert gallery.repair_missing_work_orders() == {'repaired': 0, 'review': 0}
    assert gallery.publish_work_order_records(lookup, [_record('02345678')], 101)['enriched'] == 1
    assert gallery.item(ident)['work_order_number'] == '02345678'


def test_cached_source_key_normalization_cannot_replace_exact_scan_candidate_matching(tmp_path):
    gallery = _gallery(tmp_path)
    gallery.publish_reference_snapshot(DAY, 'final', [_record('022-78850')], 100)
    ident, lookup = _publish(gallery, candidates=('02278850',))
    assert lookup == ('02278850',)
    assert gallery.repository.reference_item(ident)['state'] == 'REVIEW'
    assert gallery.publish_work_order_records(lookup, [_record('022-78850')], 101)['enriched'] == 0
    assert gallery.repository.reference_item(ident)['work_order_number'] == ''


def test_conflicting_source_records_cannot_confirm_a_pending_scan(tmp_path):
    gallery = _gallery(tmp_path)
    ident, lookup = _publish(gallery, candidates=('02278850',))
    result = gallery.publish_work_order_records(lookup, [_record(), _record(source='different-source')], 101)
    assert result == {'count': 0, 'enriched': 0}
    assert gallery.repository.reference_item(ident)['state'] == 'REVIEW'
    assert gallery.repository.reference_item(ident)['work_order_number'] == ''


def test_multiple_cached_source_matches_cannot_confirm_a_pending_scan(tmp_path):
    gallery = _gallery(tmp_path)
    gallery.publish_reference_snapshot(DAY, 'final', [_record(), _record('02345678', 'second')], 100)
    ident, lookup = _publish(gallery, candidates=('02278850', '02345678'))
    assert lookup == ('02278850', '02345678')
    assert gallery.repository.reference_item(ident)['state'] == 'REVIEW'


def test_one_cached_match_cannot_discard_another_independent_scan_candidate(tmp_path):
    gallery = _gallery(tmp_path)
    gallery.publish_reference_snapshot(DAY, 'final', [_record()], 100)
    ident, lookup = _publish(gallery, candidates=('02278850', '02345678'))
    assert lookup == ('02278850', '02345678')
    assert gallery.repository.reference_item(ident)['state'] == 'REVIEW'
    assert gallery.repository.reference_item(ident)['work_order_number'] == ''
    assert gallery.publish_work_order_records(lookup, [_record(), _record('02345678', 'second')], 101)[
        'enriched'] == 0


def test_completed_lookup_must_cover_every_candidate_before_accepting_one(tmp_path):
    gallery = _gallery(tmp_path)
    ident, lookup = _publish(gallery, candidates=('02278850', '02345678'))
    # A card published while this earlier lookup was in flight may contain a
    # candidate which that lookup never requested from the source.
    assert gallery.publish_work_order_records(['02278850'], [_record()], 101)['enriched'] == 0
    assert gallery.repository.reference_item(ident)['work_order_number'] == ''
    assert gallery.publish_work_order_records(lookup, [_record()], 102)['enriched'] == 1
    assert gallery.item(ident)['work_order_number'] == '02278850'


def test_conflicting_candidate_cannot_make_another_candidate_appear_unique(tmp_path):
    gallery = _gallery(tmp_path)
    ident, lookup = _publish(gallery, candidates=('02278850', '02345678'))
    records = [_record(), _record(source='conflicting-source'), _record('02345678', 'second')]
    assert gallery.publish_work_order_records(lookup, records, 101)['enriched'] == 0
    assert gallery.repository.reference_item(ident)['state'] == 'REVIEW'
    assert gallery.repository.reference_item(ident)['work_order_number'] == ''


def test_old_manifest_without_candidate_contract_retains_generic_work_order_handling(tmp_path):
    gallery = _gallery(tmp_path)
    ident, lookup = _publish(gallery, raw='102278850', strict=False)
    assert lookup == ('10227885',)
    assert gallery.item(ident)['work_order_number'] == '10227885'


def test_strict_recognition_retry_cannot_resurrect_a_rejected_saved_number(tmp_path):
    gallery = _gallery(tmp_path)
    ident, _ = _publish(gallery)
    # A saved pre-fix review card can still contain an overlong raw field.
    with gallery.repository.connect() as connection:
        connection.execute("UPDATE items SET text='Work Order Number: 022788501' WHERE id=?", (ident,))
    assert gallery.repair_one(lambda path: dict(text='Work Order Number: 022788501', work_order_candidates=()))
    item = gallery.repository.reference_item(ident)
    assert item['work_order_number'] == ''
    assert printed_work_order_number(item['text']) == ''
    assert gallery.repair_missing_work_orders() == {'repaired': 0, 'review': 0}
    assert gallery.work_order_lookup_numbers() == []
    assert not gallery.repair_one(lambda path: pytest.fail('Empty candidates must back off'))


def test_manual_work_order_edit_wins_over_an_in_flight_scan_retry(tmp_path):
    gallery = _gallery(tmp_path)
    ident, _ = _publish(gallery)
    def reader(path):
        gallery.import_item_work_order('a' * 64, ident, '00000007')
        return dict(text='Work Order Number: 022788501', work_order_candidates=('02278850',))
    assert gallery.repair_one(reader)
    assert gallery.item(ident)['work_order_number'] == '00000007'
    assert gallery.repository.import_item('a' * 64, ident)['work_order_candidates'] == ()


def test_new_scan_retry_of_unidentified_legacy_card_waits_for_source_confirmation(tmp_path):
    from printer_app.tests.test_gallery_recognition import seed

    gallery = _gallery(tmp_path)
    ident = seed(gallery, text='Lead Name: Existing Customer', recognition_revision=0)
    assert gallery.item(ident)['state'] == 'ACTIVE'
    assert gallery.repair_one(lambda path: dict(
        text='Work Order Number: 02278850', work_order_candidates=('02278850',)))
    assert gallery.repository.reference_item(ident)['state'] == 'REVIEW'
    assert gallery.repository.reference_item(ident)['work_order_number'] == ''
    assert gallery.work_order_lookup_numbers() == ['02278850']
    assert gallery.publish_work_order_records(['02278850'], [_record()], 100)['enriched'] == 1
    assert gallery.item(ident)['work_order_number'] == '02278850'


def test_new_scan_retry_preserves_an_already_accepted_stored_work_order(tmp_path):
    from printer_app.tests.test_gallery_recognition import seed

    gallery = _gallery(tmp_path)
    ident = seed(gallery, text='Work Order Number: 00000007\nLead Name: Existing Customer',
                 recognition_revision=0)
    before = gallery.item(ident)
    assert gallery.repair_one(lambda path: dict(
        text='Work Order Number: 022788501', work_order_candidates=()))
    after = gallery.item(ident)
    assert after['work_order_number'] == '00000007'
    assert after['text'] == before['text']
    assert after['state'] == 'ACTIVE'


def test_clearing_unconfirmed_identity_uses_the_same_field_boundaries_as_generic_parsing():
    text = ('Lead Name: Customer | Work Order Number 022788501 Address: 123 Main Street\n'
            'Work Order Number: 023456789\nPhone: 3605551212\nNotes: Keep notes')
    clean = clear_work_order_identity(text)
    assert printed_work_order_number(clean) == ''
    assert 'Address: 123 Main Street' in clean
    assert 'Phone: 3605551212' in clean
    assert 'Notes: Keep notes' in clean


@pytest.mark.parametrize('pending', [False, True])
@pytest.mark.parametrize('source_day,resources,expected_rep', [
    ('', (), 'Saved Rep'),
    ('', ('Actual Rep',), 'Actual Rep'),
    (DAY, (), ''),
])
def test_source_without_dated_assignment_facts_preserves_saved_card_date_and_rep(
        tmp_path, pending, source_day, resources, expected_rep):
    from printer_app.tests.test_gallery_reference import _card

    gallery = _gallery(tmp_path)
    if pending:
        ident, _ = _publish(gallery, candidates=('02278850',))
    else:
        ident = 'existing-card'
        _card(gallery, ident, '02278850', rep='Saved Rep')
    with gallery.repository.connect() as connection:
        connection.execute("""UPDATE items SET assigned_service_resource='Saved Rep',
            text=text || '\nAssigned Service Resource: Saved Rep' WHERE id=?""", (ident,))
    before = gallery.repository.reference_item(ident)
    record = WorkOrderReference(source_id='source-confirmed', work_order_number='02278850',
                                lead_source_id='lead-confirmed', sales_lead_status='Canceled',
                                phone='3605553434', appointment_date=source_day,
                                assigned_service_resources=resources)

    assert gallery.publish_work_order_records(['02278850'], [record], 100)['enriched'] == 1

    item = gallery.item(ident)
    assert item['state'] == 'ACTIVE'
    assert item['work_order_number'] == '02278850'
    assert item['document_date'] == before['document_date']
    assert item['assigned_service_resource'] == expected_rep
    assert item['lead_source_id'] == 'lead-confirmed'
    assert item['sales_lead_status'] == 'Canceled'
    assert 'Phone: 3605553434' in item['text']
    if expected_rep:
        assert 'Assigned Service Resource: ' + expected_rep in item['text']
    else:
        assert 'Assigned Service Resource: Saved Rep' not in item['text']
