"""Optional MOD reference enrichment for Gallery."""
from dataclasses import replace
import hashlib
import time

import pytest

from printer_app.gallery.files import GalleryFiles
from printer_app.gallery.repository import GalleryRepository
from printer_app.gallery.service import GalleryService
from printer_app.mod_sheet_contract import ModSheetRecord, WorkOrderLeadStatus


DAY = '2026-09-21'


def _gallery(tmp_path):
    root = tmp_path / 'gallery'
    service = GalleryService(GalleryRepository(root / 'gallery.db'), GalleryFiles(root))
    service.initialize()
    return service


def _card(service, ident, work_order, lead='Jordan Example', address='123 Main St, Lacey, WA 98503',
          rep='INK REP', day=DAY):
    import_id = 'import-' + ident
    service.repository.enqueue(import_id, 'cards.pdf')
    text = (
        f'Work Order Number: {work_order}\n'
        'Local Scheduled Start Time: 9/21/2026 8:00 AM\n'
        f'Lead Name: {lead}\n'
        f'Address: {address}\n'
        f'Assigned Service Resource: {rep}\n'
        'Set By: Setter\n'
        'Lead Description: KEEP THIS INK\n'
    )
    service.repository.finish(import_id, [{
        'id': ident,
        'import_id': import_id,
        'page': 1,
        'part': 1,
        'filename': ident + '.png',
        'text': text,
        'lead_text': f'Lead Name: {lead}',
        'document_date': day,
        'date_status': 'printed',
        'bytes': 100,
        'created': time.time(),
        'recognition_revision': 1,
    }])
    return service.item(ident)


def _reference(work_order, rep, lead='Jordan Example', address='123 Main St, Lacey, WA 98503'):
    return ModSheetRecord(
        source_id='source-' + work_order,
        work_order_number=work_order,
        lead_name=lead,
        address=address,
        assigned_service_resources=(rep,) if rep else (),
        product_interest='Windows',
        source='Internet',
    )


def test_gallery_without_reference_data_behaves_as_before(tmp_path):
    gallery = _gallery(tmp_path)
    item = _card(gallery, 'card-no-reference', '00000001')

    assert item['assigned_service_resource'] == ''
    assert item['reference_kind'] == ''
    assert 'Assigned Service Resource: INK REP' in item['text']
    assert 'Lead Description: KEEP THIS INK' in item['text']


def test_final_reference_replaces_assigned_resource_and_preserves_unrelated_ink(tmp_path):
    gallery = _gallery(tmp_path)
    _card(gallery, 'card-matched', '00000002')

    result = gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('00000002', 'Final Rep')], 100.0
    )
    item = gallery.item('card-matched')

    assert result == {'day': DAY, 'kind': 'final', 'count': 1, 'enriched': 1}
    assert item['assigned_service_resource'] == 'Final Rep'
    assert item['reference_kind'] == 'final'
    assert item['reference_source_id'] == 'source-00000002'
    assert 'Assigned Service Resource: Final Rep' in item['text']
    assert 'INK REP' not in item['text']
    assert 'Lead Description: KEEP THIS INK' in item['text']
    assert item['lead_name'] == 'Jordan Example'
    assert item['address'] == '123 Main St, Lacey, WA 98503'


def test_morning_snapshot_can_be_larger_than_final_without_gallery_error(tmp_path):
    gallery = _gallery(tmp_path)
    _card(gallery, 'card-kept', '00000003', rep='MORNING INK')
    _card(gallery, 'card-cancelled', '00000004', lead='Taylor Example',
          address='456 Second St, Lacey, WA 98503', rep='CANCELLED INK')

    morning = [
        _reference('00000003', 'Morning Rep'),
        _reference('00000004', 'Morning Rep 2', lead='Taylor Example',
                   address='456 Second St, Lacey, WA 98503'),
    ]
    gallery.publish_reference_snapshot(DAY, 'morning', morning, 50.0)
    final = gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('00000003', 'Final Rep')], 100.0
    )

    morning_snapshot, morning_rows = gallery.repository.reference_snapshot(DAY, 'morning')
    final_snapshot, final_rows = gallery.repository.reference_snapshot(DAY, 'final')
    kept = gallery.item('card-kept')
    cancelled = gallery.item('card-cancelled')

    assert morning_snapshot['count'] == 2 and len(morning_rows) == 2
    assert final_snapshot['count'] == 1 and len(final_rows) == 1
    assert final['enriched'] == 1
    assert kept['assigned_service_resource'] == 'Final Rep'
    # Missing from the later snapshot is a normal cancellation/change. Gallery
    # keeps the card's existing OCR behavior instead of erroring or deleting it.
    assert cancelled['assigned_service_resource'] == ''
    assert 'Assigned Service Resource: CANCELLED INK' in cancelled['text']


def test_reference_can_arrive_before_card_and_enrich_later(tmp_path):
    gallery = _gallery(tmp_path)
    gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('00000005', 'Late Card Rep')], 100.0
    )
    _card(gallery, 'card-late', '00000005', rep='OLD INK')

    assert gallery._enrich_reference_item('card-late') is True
    item = gallery.item('card-late')
    assert item['assigned_service_resource'] == 'Late Card Rep'
    assert 'OLD INK' not in item['text']


def test_ambiguous_reference_match_keeps_existing_gallery_behavior(tmp_path):
    gallery = _gallery(tmp_path)
    _card(gallery, 'card-ambiguous', '', lead='Same Name', address='', rep='OCR STILL USED')
    refs = [
        _reference('00001001', 'Rep One', lead='Same Name', address='1 First St'),
        _reference('00001002', 'Rep Two', lead='Same Name', address='2 Second St'),
    ]

    result = gallery.publish_reference_snapshot(DAY, 'final', refs, 100.0)
    item = gallery.item('card-ambiguous')

    assert result['enriched'] == 0
    assert item['assigned_service_resource'] == ''
    assert 'OCR STILL USED' in item['text']


def test_reference_corrects_identity_and_all_resource_search_without_changing_card(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'a' * 64
    _card(gallery, ident, '00000006', lead='Wrongname Mistake', address='987 Wrongstreet')
    gallery.import_item_lead('import-' + ident, ident, 'Previous Manualname')
    gallery.note(ident, 'b' * 32, 'Reviewer', 'Keep this saved note')
    image = gallery.files.path('crops', ident)
    image.write_bytes(b'original-card-image')
    before = gallery.item(ident)
    reference = replace(
        _reference('00000006', '', lead='Correctname Example', address='123 Rightstreet'),
        assigned_service_resources=(' Rep Alpha ', 'Rep Beta', 'rep alpha', '', 'Rep Gamma'),
    )

    result = gallery.publish_reference_snapshot(DAY, 'final', [reference], 100.0)
    item = gallery.item(ident)

    assert result['enriched'] == 1
    assert item['lead_name'] == 'Correctname Example'
    assert item['lead_key'] == 'correctname example'
    assert item['lead_status'] == 'printed'
    assert item['address'] == '123 Rightstreet'
    assert item['address_key'] == '123 rightstreet'
    assert item['assigned_service_resource'] == 'Rep Alpha, Rep Beta, Rep Gamma'
    assert 'Lead Name: Correctname Example' in item['text']
    assert 'Address: 123 Rightstreet' in item['text']
    for query in ('Correctname', 'Rightstreet', 'Alpha', 'Beta', 'Gamma'):
        assert [row['id'] for row in gallery.search(query, 0)['items']] == [ident]
    for query in ('Wrongname', 'Wrongstreet', 'Manualname', '"INK REP"'):
        assert gallery.search(query, 0)['total'] == 0, query
    for key in ('id', 'import_id', 'page', 'part', 'filename', 'bytes', 'created', 'state',
                'document_date', 'date_status', 'work_order_number', 'notes', 'notes_text'):
        assert item[key] == before[key]
    assert 'Local Scheduled Start Time: 9/21/2026 8:00 AM' in item['text']
    assert 'Lead Description: KEEP THIS INK' in item['text']
    assert image.read_bytes() == b'original-card-image'


def test_empty_source_identity_is_preserved_but_confirmed_unassignment_clears_old_rep(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'card-source-blanks'
    _card(gallery, ident, '00000007')
    gallery.publish_reference_snapshot(DAY, 'final', [_reference('00000007', 'Known Rep')], 100.0)
    gallery.import_item_lead('import-' + ident, ident, 'Confirmed Name')
    before = gallery.item(ident)

    gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('00000007', '', lead='', address='')], 101.0,
    )
    item = gallery.item(ident)

    for key in ('lead_name', 'lead_key', 'lead_status', 'address', 'address_key'):
        assert item[key] == before[key]
    assert item['assigned_service_resource'] == ''
    assert 'Known Rep' not in item['text']
    assert 'Lead Description: KEEP THIS INK' in item['text']
    assert gallery.search('Known Rep', 0)['total'] == 0
    assert gallery.search('Known Rep', 0, field='rep')['total'] == 0


def test_missing_final_match_and_empty_morning_resources_preserve_saved_reps(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'card-no-current-assignment-match'
    _card(gallery, ident, '00000007')
    gallery.publish_reference_snapshot(DAY, 'final', [_reference('00000007', 'Known Rep')], 100.0)
    before = gallery.item(ident)

    gallery.publish_reference_snapshot(DAY, 'final', [_reference('different-order', '')], 101.0)
    after = gallery.item(ident)
    assert after['search_revision'] > before['search_revision']
    assert after == dict(before, search_revision=after['search_revision'])
    gallery.publish_reference_snapshot(DAY, 'morning', [_reference('00000007', '')], 102.0)
    item = gallery.item(ident)
    assert item['assigned_service_resource'] == 'Known Rep'
    assert 'Assigned Service Resource: Known Rep' in item['text']
    assert gallery.search('Known Rep', 0, field='rep')['total'] == 1


@pytest.mark.parametrize('work_order', ['', 'unmatched-order'])
def test_same_name_or_address_never_substitutes_for_work_order_match(tmp_path, work_order):
    gallery = _gallery(tmp_path)
    before = _card(gallery, 'card-no-fuzzy', work_order)

    result = gallery.publish_reference_snapshot(DAY, 'final', [_reference('00001234', 'Other Rep')], 100.0)

    assert result['enriched'] == 0
    after = gallery.item('card-no-fuzzy')
    assert after['search_revision'] > before['search_revision']
    assert after == dict(before, search_revision=after['search_revision'])


def test_identical_work_order_on_another_date_does_not_match(tmp_path):
    gallery = _gallery(tmp_path)
    before = _card(gallery, 'card-different-day', '00000008', day='2026-09-20')

    result = gallery.publish_reference_snapshot(DAY, 'final', [_reference('00000008', 'Other Day Rep')], 100.0)

    assert result['enriched'] == 0
    assert gallery._enrich_reference_item('card-different-day') is False
    assert gallery.item('card-different-day') == before


def test_duplicate_normalized_work_order_is_ambiguous_even_when_name_matches_one(tmp_path):
    gallery = _gallery(tmp_path)
    before = _card(gallery, 'card-duplicate-order', '00000009')
    references = [
        _reference('00000009', 'First Rep'),
        replace(_reference('00000009', 'Second Rep', lead='Different Customer'),
                source_id='second-source'),
    ]

    result = gallery.publish_reference_snapshot(DAY, 'final', references, 100.0)

    assert result['enriched'] == 0
    after = gallery.item('card-duplicate-order')
    assert after['search_revision'] > before['search_revision']
    assert after == dict(before, search_revision=after['search_revision'])


def test_existing_review_card_gets_reference_identity_without_being_approved(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'review-card'
    _card(gallery, ident, '00000010', lead='', address='Wrong Address')
    before = gallery.repository.reference_item(ident)
    assert before['state'] == 'REVIEW'

    gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('00000010', 'Assigned Rep', lead='Resolved Customer')], 100.0,
    )
    item = gallery.repository.reference_item(ident)

    assert item['lead_name'] == 'Resolved Customer'
    assert item['address'] == '123 Main St, Lacey, WA 98503'
    assert item['state'] == 'REVIEW'
    assert item['document_date'] == before['document_date']
    assert gallery.item(ident) is None


@pytest.mark.parametrize('resource', ['Cached Rep', ''])
def test_normal_import_uses_cached_reference_for_identity_and_search(tmp_path, resource):
    gallery = _gallery(tmp_path)
    gallery.publish_reference_snapshot(
        DAY, 'final', [
            _reference('00000011', resource, lead='Cached Customer', address='101 Cachedstreet')],
        100.0,
    )
    gallery.publish_lead_statuses(['00000011'], [
        WorkOrderLeadStatus('00000011', 'lead-cached', 'Canceled')], 100.0)
    job = {'id': 'c' * 64, 'filename': 'cards.pdf'}
    gallery.repository.enqueue(job['id'], job['filename'])
    directory = gallery.files.path('work', job['id'])
    directory.mkdir()
    (directory / 'card.png').write_bytes(b'original-import-image')
    manifest = {'items': [{
        'file': 'card.png', 'page': 1, 'part': 1, 'bytes': 21,
        'text': 'Work Order Number: 00000011\nLead Name: Oldname\nAddress: Oldstreet\n'
                'Local Scheduled Start Time: 9/21/2026 10:30 AM\nAssigned Service Resource: Old Rep',
        'lead_text': 'Lead Name: Oldname', 'document_date': DAY, 'date_status': 'printed',
    }]}

    gallery.publish(job, manifest, directory)
    ident = hashlib.sha256(f"{job['id']}:1:1".encode()).hexdigest()
    item = gallery.item(ident)

    assert item['lead_name'] == 'Cached Customer'
    assert item['sales_lead_status'] == 'Canceled'
    assert item['address'] == '101 Cachedstreet'
    assert item['assigned_service_resource'] == resource
    assert gallery.search('Cachedstreet', 0)['total'] == 1
    assert gallery.search('Oldname', 0)['total'] == 0
    assert gallery.search('Old Rep', 0)['total'] == 0
    assert gallery.search('Old Rep', 0, field='rep')['total'] == 0
    assert '10:30 AM' in item['text']
    assert gallery.files.path('crops', ident).read_bytes() == b'original-import-image'


def test_direct_work_order_record_supplies_date_identity_and_rep_to_undated_card(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'direct-undated'
    _card(gallery, ident, '00002001', lead='', address='', day=None)
    assert gallery.repository.reference_item(ident)['state'] == 'REVIEW'

    record = ModSheetRecord(
        source_id='source-direct',
        work_order_number='00002001',
        appointment_date=DAY,
        lead_name='Resolved Customer',
        address='222 Resolved Ave, Lacey, WA 98503',
        phone='360-555-0199',
        assigned_service_resources=('Resolved Rep',),
        scheduled_start='2026.09.21 ; 10:30:00 AM',
        sales_lead_status='Sold',
        lead_source_id='lead-direct',
    )
    result = gallery.publish_work_order_records(('00002001',), (record,), 100)

    item = gallery.item(ident)
    assert result == {'count': 1, 'enriched': 1}
    assert item['state'] == 'ACTIVE'
    assert item['document_date'] == DAY
    assert item['date_status'] == 'reference'
    assert item['lead_name'] == 'Resolved Customer'
    assert item['address'] == '222 Resolved Ave, Lacey, WA 98503'
    assert item['assigned_service_resource'] == 'Resolved Rep'
    assert item['sales_lead_status'] == 'Sold'
    assert item['lead_source_id'] == 'lead-direct'
    assert item['reference_kind'] == 'work-order'
    assert gallery.search('Resolved', 0)['total'] == 1

    job = gallery.import_job('import-' + ident)
    assert job['items'][0]['work_order_number'] == '00002001'


def test_reference_dates_exposes_only_distinct_valid_retained_card_dates(tmp_path):
    from printer_app.gallery.bootstrap import GalleryReferenceInbox

    gallery = _gallery(tmp_path)
    _card(gallery, 'active-date', '00001001')
    _card(gallery, 'review-date', '00001002', lead='')
    _card(gallery, 'earlier-date', '00001003', lead='', day='2026-09-19')
    _card(gallery, 'no-date', '00001004', day=None)
    _card(gallery, 'invalid-date', '00001005', day='2026-99-10')
    _card(gallery, 'unsupported-year', '00001006', day='2500-01-01')
    _card(gallery, 'deleting-date', '00001007', day='2026-09-18')
    gallery.repository.claim_import_item_delete('import-deleting-date', 'deleting-date')

    assert gallery.reference_dates() == ['2026-09-19', DAY]
    assert GalleryReferenceInbox(tmp_path).dates() == ['2026-09-19', DAY]


def test_reference_text_replaces_flattened_fields_and_preserves_times():
    from printer_app.gallery.policy import authoritative_reference_text

    original = ('Lead Name: Wrongname Address: Wrongstreet Phone: 5551234 '
                'Scheduled Start: 9/21/2026 10:30 AM Assigned Service Resource: Wrongrep '
                'Set By: KEEP SETTER\nLead Description: KEEP NOTES')

    text = authoritative_reference_text(original, 'Correctname', '123 Rightstreet', 'Rep One, Rep Two')

    assert 'Lead Name: Correctname Address: 123 Rightstreet Phone: 5551234' in text
    assert 'Scheduled Start: 9/21/2026 10:30 AM Assigned Service Resource: Rep One, Rep Two' in text
    assert 'Wrongname' not in text and 'Wrongstreet' not in text and 'Wrongrep' not in text
    assert text.endswith('Set By: KEEP SETTER\nLead Description: KEEP NOTES')


@pytest.mark.parametrize('separator', ['\n', ' | '])
def test_confirmed_unassignment_clears_wrapped_rep_text_without_changing_other_fields(separator):
    from printer_app.gallery.policy import authoritative_reference_text

    original = separator.join([
        'Lead Name: Keep Customer',
        'Assigned Service Resource: Former Rep\nSecond Former Rep',
        'Set By: Keep Setter', 'Lead Description: Keep Notes',
    ])

    assert authoritative_reference_text(original) == original
    assert authoritative_reference_text(original, clear_assigned_resource=True) == separator.join([
        'Lead Name: Keep Customer', 'Assigned Service Resource: ',
        'Set By: Keep Setter', 'Lead Description: Keep Notes',
    ])


@pytest.mark.parametrize('separator', ['\n', ' | '])
def test_reference_text_replaces_delimited_identity_fields_without_touching_timestamps(separator):
    from printer_app.gallery.policy import authoritative_reference_text

    original = separator.join([
        'Work Order Number: 00000001', 'Local Scheduled Start Time: 2026-09-21 8:00 AM',
        'Lead Name: Wrongname', 'Address: Wrongstreet',
        'Scheduled Start: 2026-09-21 10:30 AM', 'Lead Description: KEEP NOTES',
    ])

    text = authoritative_reference_text(original, 'Correctname', '123 Rightstreet', 'Rep One, Rep Two')

    assert text == separator.join([
        'Work Order Number: 00000001', 'Local Scheduled Start Time: 2026-09-21 8:00 AM',
        'Lead Name: Correctname', 'Address: 123 Rightstreet',
        'Scheduled Start: 2026-09-21 10:30 AM', 'Lead Description: KEEP NOTES',
    ]) + '\nAssigned Service Resource: Rep One, Rep Two'


def test_reference_removes_wrapped_old_identity_from_search_but_keeps_notes_and_times(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'multiline-card'
    _card(gallery, ident, '00000012', lead='Wrongfirst\nWronglast',
          address='42 Wrongstreet\nWrongcity, WA 98503')

    gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('00000012', 'Final Rep', lead='Correctname', address='123 Rightstreet')],
        100.0,
    )
    item = gallery.item(ident)

    for query in ('Wrongfirst', 'Wronglast', 'Wrongstreet', 'Wrongcity'):
        assert gallery.search(query, 0)['total'] == 0, query
    assert item['lead_name'] == 'Correctname'
    assert item['address'] == '123 Rightstreet'
    assert 'Local Scheduled Start Time: 9/21/2026 8:00 AM' in item['text']
    assert 'Lead Description: KEEP THIS INK' in item['text']


def test_reference_text_preserves_following_labels_with_missing_colons():
    from printer_app.gallery.policy import authoritative_reference_text

    original = ('Address: Wrong Sourcebook Street\n'
                'Scheduled Start 9/21/2026 10:30 AM\n'
                'Assigned Service Resource: Old Rep\n'
                'Set By Old Setter\nLead Description: KEEP NOTES')

    text = authoritative_reference_text(original, address='123 Rightstreet', assigned_resource='New Rep')

    assert text == ('Address: 123 Rightstreet\n'
                    'Scheduled Start 9/21/2026 10:30 AM\n'
                    'Assigned Service Resource: New Rep\n'
                    'Set By Old Setter\nLead Description: KEEP NOTES')


def test_sales_lead_status_matches_work_order_across_dates_without_name_matching(tmp_path):
    gallery = _gallery(tmp_path)
    _card(gallery, 'same-customer-different-order', '00000012')
    _card(gallery, 'same-order-different-date', '00000011', day='2026-09-20')
    _card(gallery, 'matched-card', '00000011')
    _card(gallery, 'same-order-undated', '00000011', day=None)
    _card(gallery, 'same-order-future', '00000011', day='2026-09-22')
    result = gallery.publish_lead_statuses(['00000011'], [
        WorkOrderLeadStatus('00000011', 'lead-one', 'Sold')], 100)

    assert result['enriched'] == 4
    for ident in ('matched-card', 'same-order-different-date', 'same-order-undated', 'same-order-future'):
        assert gallery.item(ident)['sales_lead_status'] == 'Sold'
    assert gallery.item('same-customer-different-order')['sales_lead_status'] == ''
    related = {row['id']: row for row in gallery.related('matched-card')['items']}
    assert related['matched-card']['sales_lead_status'] == 'Sold'
    assert related['same-customer-different-order']['sales_lead_status'] == ''

    gallery.publish_lead_statuses(['00000012'], [
        WorkOrderLeadStatus('00000012', 'lead-two', 'Canceled')], 101)
    assert gallery.item('matched-card')['sales_lead_status'] == 'Sold'
    assert gallery.item('same-customer-different-order')['sales_lead_status'] == 'Canceled'
    assert gallery.item('same-order-different-date')['sales_lead_status'] == 'Sold'


def test_sales_status_refresh_changes_caption_data_without_notes_or_image_changes(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'd' * 64
    _card(gallery, ident, '00000013')
    image = gallery.files.path('crops', ident)
    image.write_bytes(b'original-scan')
    gallery.note(ident, 'b' * 32, 'Office', 'Keep this note')
    reference = _reference('00000013', 'Same Rep')
    gallery.publish_reference_snapshot(DAY, 'final', [reference], 100)
    gallery.publish_lead_statuses(['00000013'], [
        WorkOrderLeadStatus('00000013', 'lead-one', 'Open')], 100)
    gallery.repository.correct_lead(ident, 'Jordan Example')
    before = gallery.item(ident)

    gallery.publish_lead_statuses(['00000013'], [
        WorkOrderLeadStatus('00000013', 'lead-one', 'Sold')], 101)
    after = gallery.item(ident)

    assert after['sales_lead_status'] == 'Sold'
    assert after['search_revision'] > before['search_revision']
    assert after['text'] == before['text']
    assert after['notes'] == before['notes']
    assert after['lead_status'] == before['lead_status'] == 'confirmed'
    assert image.read_bytes() == b'original-scan'
    assert gallery.search('', 0)['items'][0]['sales_lead_status'] == 'Sold'
    assert gallery.offline_index()['items'][0]['sales_lead_status'] == 'Sold'


@pytest.mark.parametrize('replacement', ['missing', 'ambiguous', 'blank'])
def test_unmatched_or_unknown_sales_status_does_not_keep_a_stale_status(tmp_path, replacement):
    gallery = _gallery(tmp_path)
    ident = 'status-no-longer-known'
    _card(gallery, ident, '00000014')
    reference = WorkOrderLeadStatus('00000014', 'lead-one', 'Sold')
    gallery.publish_lead_statuses(['00000014'], [reference], 100)
    rows = [] if replacement == 'missing' else [
        replace(reference, sales_lead_status='') if replacement == 'blank' else reference]
    if replacement == 'ambiguous':
        rows.append(replace(reference, lead_source_id='another-lead', sales_lead_status='Canceled'))

    gallery.publish_lead_statuses(['00000014'], rows, 101)

    assert gallery.item(ident)['sales_lead_status'] == ''
    assert gallery.item(ident)['lead_name'] == 'Jordan Example'


@pytest.mark.parametrize('missing', [False, True])
def test_morning_and_final_appointments_cannot_replace_direct_lead_status(tmp_path, missing):
    gallery = _gallery(tmp_path)
    _card(gallery, 'status-morning', '00000015')
    reference = _reference('00000015', '')
    gallery.publish_lead_statuses(['00000015'], [
        WorkOrderLeadStatus('00000015', 'lead-current', 'Sold')], 100)
    gallery.publish_reference_snapshot(DAY, 'morning', [
        replace(reference, lead_source_id='lead-stale', sales_lead_status='Open')], 101)

    gallery.publish_reference_snapshot(DAY, 'final', [] if missing else [reference], 102)

    assert gallery.item('status-morning')['sales_lead_status'] == 'Sold'
    assert gallery.item('status-morning')['lead_source_id'] == 'lead-current'


def test_corrected_card_date_preserves_work_order_lead_status(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'status-date-correction'
    _card(gallery, ident, '00000016')
    reference = _reference('00000016', '')
    gallery.publish_lead_statuses(['00000016'], [
        WorkOrderLeadStatus('00000016', 'lead-one', 'Sold')], 100)
    gallery.publish_reference_snapshot('2026-09-20', 'final', [
        replace(reference, lead_source_id='lead-stale', sales_lead_status='Open')], 101)

    gallery.date(ident, '2026-09-20')
    assert gallery.item(ident)['sales_lead_status'] == 'Sold'
    gallery.date(ident, '2026-09-19')
    assert gallery.item(ident)['sales_lead_status'] == 'Sold'
    assert gallery.item(ident)['lead_source_id'] == 'lead-one'


def test_sold_status_copies_to_other_work_orders_and_dates_for_the_same_lead_id(tmp_path):
    gallery = _gallery(tmp_path)
    _card(gallery, 'older-work-order', '00000101', day='2026-09-20')
    _card(gallery, 'today-work-order', '00000102')
    _card(gallery, 'different-lead-same-name', '00000103')
    older = _reference('00000101', 'Older Rep')
    today = _reference('00000102', 'Today Rep')
    different = _reference('00000103', 'Different Rep')
    gallery.publish_reference_snapshot('2026-09-20', 'final', [older], 100)
    gallery.publish_reference_snapshot(DAY, 'final', [today, different], 101)
    gallery.publish_lead_statuses(['00000101', '00000102', '00000103'], [
        WorkOrderLeadStatus('00000101', 'lead-shared', 'Open'),
        WorkOrderLeadStatus('00000102', 'lead-shared', 'Open'),
        WorkOrderLeadStatus('00000103', 'lead-different', 'Open')], 101)
    before = gallery.item('older-work-order')

    gallery.publish_lead_statuses(['00000102'], [
        WorkOrderLeadStatus('00000102', 'lead-shared', 'Sold')], 102)

    assert gallery.item('today-work-order')['sales_lead_status'] == 'Sold'
    after = gallery.item('older-work-order')
    assert after['sales_lead_status'] == 'Sold'
    assert after['search_revision'] > before['search_revision']
    assert after['assigned_service_resource'] == before['assigned_service_resource'] == 'Older Rep'
    assert after['document_date'] == '2026-09-20'
    assert gallery.item('different-lead-same-name')['sales_lead_status'] == 'Open'
    statuses = {row['id']: row['sales_lead_status'] for row in gallery.offline_index()['items']}
    assert statuses == {'older-work-order': 'Sold', 'today-work-order': 'Sold',
                        'different-lead-same-name': 'Open'}

    # Dropping an appointment does not erase the confirmed customer identity or
    # the latest known Sold status shared from that customer's other work order.
    gallery.publish_reference_snapshot('2026-09-20', 'final', [], 103)
    assert gallery.item('older-work-order')['sales_lead_status'] == 'Sold'


def test_later_card_link_uses_shared_current_status_not_older_work_order_snapshot(tmp_path):
    gallery = _gallery(tmp_path)
    reference = replace(_reference('00000201', ''), lead_source_id='lead-shared', sales_lead_status='Open')
    gallery.publish_reference_snapshot('2026-09-20', 'morning', [reference], 100)
    gallery.publish_lead_statuses(['00000201'], [
        WorkOrderLeadStatus('00000201', 'lead-shared', 'Open')], 100)
    gallery.publish_lead_statuses(['00000202'], [
        WorkOrderLeadStatus('00000202', 'lead-shared', 'Sold')], 101)
    _card(gallery, 'late-card', '00000201', day='2026-09-20')

    gallery._enrich_reference_item('late-card')

    assert gallery.item('late-card')['sales_lead_status'] == 'Sold'
    assert gallery.item('late-card')['lead_source_id'] == 'lead-shared'
