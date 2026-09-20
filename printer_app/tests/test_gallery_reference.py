"""Optional MOD reference enrichment for Gallery."""
from dataclasses import replace
import hashlib
import time

import pytest

from printer_app.gallery.files import GalleryFiles
from printer_app.gallery.repository import GalleryRepository
from printer_app.gallery.service import GalleryService
from printer_app.mod_sheet_contract import ModSheetRecord


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
    item = _card(gallery, 'card-no-reference', '0001')

    assert item['assigned_service_resource'] == ''
    assert item['reference_kind'] == ''
    assert 'Assigned Service Resource: INK REP' in item['text']
    assert 'Lead Description: KEEP THIS INK' in item['text']


def test_final_reference_replaces_assigned_resource_and_preserves_unrelated_ink(tmp_path):
    gallery = _gallery(tmp_path)
    _card(gallery, 'card-matched', '0002')

    result = gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('0002', 'Final Rep')], 100.0
    )
    item = gallery.item('card-matched')

    assert result == {'day': DAY, 'kind': 'final', 'count': 1, 'enriched': 1}
    assert item['assigned_service_resource'] == 'Final Rep'
    assert item['reference_kind'] == 'final'
    assert item['reference_source_id'] == 'source-0002'
    assert 'Assigned Service Resource: Final Rep' in item['text']
    assert 'INK REP' not in item['text']
    assert 'Lead Description: KEEP THIS INK' in item['text']
    assert item['lead_name'] == 'Jordan Example'
    assert item['address'] == '123 Main St, Lacey, WA 98503'


def test_morning_snapshot_can_be_larger_than_final_without_gallery_error(tmp_path):
    gallery = _gallery(tmp_path)
    _card(gallery, 'card-kept', '0003', rep='MORNING INK')
    _card(gallery, 'card-cancelled', '0004', lead='Taylor Example',
          address='456 Second St, Lacey, WA 98503', rep='CANCELLED INK')

    morning = [
        _reference('0003', 'Morning Rep'),
        _reference('0004', 'Morning Rep 2', lead='Taylor Example',
                   address='456 Second St, Lacey, WA 98503'),
    ]
    gallery.publish_reference_snapshot(DAY, 'morning', morning, 50.0)
    final = gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('0003', 'Final Rep')], 100.0
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
        DAY, 'final', [_reference('0005', 'Late Card Rep')], 100.0
    )
    _card(gallery, 'card-late', '0005', rep='OLD INK')

    assert gallery._enrich_reference_item('card-late') is True
    item = gallery.item('card-late')
    assert item['assigned_service_resource'] == 'Late Card Rep'
    assert 'OLD INK' not in item['text']


def test_ambiguous_reference_match_keeps_existing_gallery_behavior(tmp_path):
    gallery = _gallery(tmp_path)
    _card(gallery, 'card-ambiguous', '', lead='Same Name', address='', rep='OCR STILL USED')
    refs = [
        _reference('1001', 'Rep One', lead='Same Name', address='1 First St'),
        _reference('1002', 'Rep Two', lead='Same Name', address='2 Second St'),
    ]

    result = gallery.publish_reference_snapshot(DAY, 'final', refs, 100.0)
    item = gallery.item('card-ambiguous')

    assert result['enriched'] == 0
    assert item['assigned_service_resource'] == ''
    assert 'OCR STILL USED' in item['text']


def test_reference_corrects_identity_and_all_resource_search_without_changing_card(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'a' * 64
    _card(gallery, ident, 'WO-0006', lead='Wrongname Mistake', address='987 Wrongstreet')
    gallery.import_item_lead('import-' + ident, ident, 'Previous Manualname')
    gallery.note(ident, 'b' * 32, 'Reviewer', 'Keep this saved note')
    image = gallery.files.path('crops', ident)
    image.write_bytes(b'original-card-image')
    before = gallery.item(ident)
    reference = replace(
        _reference('wo0006', '', lead='Correctname Example', address='123 Rightstreet'),
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


def test_empty_source_identity_and_resources_keep_existing_values(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'card-source-blanks'
    _card(gallery, ident, '0007')
    gallery.publish_reference_snapshot(DAY, 'final', [_reference('0007', 'Known Rep')], 100.0)
    gallery.import_item_lead('import-' + ident, ident, 'Confirmed Name')
    before = gallery.item(ident)

    gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('0007', '', lead='', address='')], 101.0,
    )
    item = gallery.item(ident)

    for key in ('lead_name', 'lead_key', 'lead_status', 'address', 'address_key',
                'assigned_service_resource', 'text'):
        assert item[key] == before[key]


@pytest.mark.parametrize('work_order', ['', 'unmatched-order'])
def test_same_name_or_address_never_substitutes_for_work_order_match(tmp_path, work_order):
    gallery = _gallery(tmp_path)
    before = _card(gallery, 'card-no-fuzzy', work_order)

    result = gallery.publish_reference_snapshot(DAY, 'final', [_reference('1234', 'Other Rep')], 100.0)

    assert result['enriched'] == 0
    assert gallery.item('card-no-fuzzy') == before


def test_identical_work_order_on_another_date_does_not_match(tmp_path):
    gallery = _gallery(tmp_path)
    before = _card(gallery, 'card-different-day', '0008', day='2026-09-20')

    result = gallery.publish_reference_snapshot(DAY, 'final', [_reference('0008', 'Other Day Rep')], 100.0)

    assert result['enriched'] == 0
    assert gallery._enrich_reference_item('card-different-day') is False
    assert gallery.item('card-different-day') == before


def test_duplicate_normalized_work_order_is_ambiguous_even_when_name_matches_one(tmp_path):
    gallery = _gallery(tmp_path)
    before = _card(gallery, 'card-duplicate-order', 'WO-0009')
    references = [
        _reference('wo0009', 'First Rep'),
        replace(_reference('WO-0009', 'Second Rep', lead='Different Customer'),
                source_id='second-source'),
    ]

    result = gallery.publish_reference_snapshot(DAY, 'final', references, 100.0)

    assert result['enriched'] == 0
    assert gallery.item('card-duplicate-order') == before


def test_existing_review_card_gets_reference_identity_without_being_approved(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'review-card'
    _card(gallery, ident, '0010', lead='', address='Wrong Address')
    before = gallery.repository.reference_item(ident)
    assert before['state'] == 'REVIEW'

    gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('0010', 'Assigned Rep', lead='Resolved Customer')], 100.0,
    )
    item = gallery.repository.reference_item(ident)

    assert item['lead_name'] == 'Resolved Customer'
    assert item['address'] == '123 Main St, Lacey, WA 98503'
    assert item['state'] == 'REVIEW'
    assert item['document_date'] == before['document_date']
    assert gallery.item(ident) is None


def test_normal_import_uses_cached_reference_for_identity_and_search(tmp_path):
    gallery = _gallery(tmp_path)
    gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('0011', 'Cached Rep', lead='Cached Customer', address='101 Cachedstreet')],
        100.0,
    )
    job = {'id': 'c' * 64, 'filename': 'cards.pdf'}
    gallery.repository.enqueue(job['id'], job['filename'])
    directory = gallery.files.path('work', job['id'])
    directory.mkdir()
    (directory / 'card.png').write_bytes(b'original-import-image')
    manifest = {'items': [{
        'file': 'card.png', 'page': 1, 'part': 1, 'bytes': 21,
        'text': 'Work Order Number: 0011\nLead Name: Oldname\nAddress: Oldstreet\n'
                'Local Scheduled Start Time: 9/21/2026 10:30 AM',
        'lead_text': 'Lead Name: Oldname', 'document_date': DAY, 'date_status': 'printed',
    }]}

    gallery.publish(job, manifest, directory)
    ident = hashlib.sha256(f"{job['id']}:1:1".encode()).hexdigest()
    item = gallery.item(ident)

    assert item['lead_name'] == 'Cached Customer'
    assert item['address'] == '101 Cachedstreet'
    assert item['assigned_service_resource'] == 'Cached Rep'
    assert gallery.search('Cachedstreet', 0)['total'] == 1
    assert gallery.search('Oldname', 0)['total'] == 0
    assert '10:30 AM' in item['text']
    assert gallery.files.path('crops', ident).read_bytes() == b'original-import-image'


def test_reference_dates_exposes_only_distinct_valid_retained_card_dates(tmp_path):
    from printer_app.gallery.bootstrap import GalleryReferenceInbox

    gallery = _gallery(tmp_path)
    _card(gallery, 'active-date', '1001')
    _card(gallery, 'review-date', '1002', lead='')
    _card(gallery, 'earlier-date', '1003', lead='', day='2026-09-19')
    _card(gallery, 'no-date', '1004', day=None)
    _card(gallery, 'invalid-date', '1005', day='2026-99-10')
    _card(gallery, 'unsupported-year', '1006', day='2500-01-01')
    _card(gallery, 'deleting-date', '1007', day='2026-09-18')
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
def test_reference_text_replaces_delimited_identity_fields_without_touching_timestamps(separator):
    from printer_app.gallery.policy import authoritative_reference_text

    original = separator.join([
        'Work Order Number: 0001', 'Local Scheduled Start Time: 2026-09-21 8:00 AM',
        'Lead Name: Wrongname', 'Address: Wrongstreet',
        'Scheduled Start: 2026-09-21 10:30 AM', 'Lead Description: KEEP NOTES',
    ])

    text = authoritative_reference_text(original, 'Correctname', '123 Rightstreet', 'Rep One, Rep Two')

    assert text == separator.join([
        'Work Order Number: 0001', 'Local Scheduled Start Time: 2026-09-21 8:00 AM',
        'Lead Name: Correctname', 'Address: 123 Rightstreet',
        'Scheduled Start: 2026-09-21 10:30 AM', 'Lead Description: KEEP NOTES',
    ]) + '\nAssigned Service Resource: Rep One, Rep Two'


def test_reference_removes_wrapped_old_identity_from_search_but_keeps_notes_and_times(tmp_path):
    gallery = _gallery(tmp_path)
    ident = 'multiline-card'
    _card(gallery, ident, '0012', lead='Wrongfirst\nWronglast',
          address='42 Wrongstreet\nWrongcity, WA 98503')

    gallery.publish_reference_snapshot(
        DAY, 'final', [_reference('0012', 'Final Rep', lead='Correctname', address='123 Rightstreet')],
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
