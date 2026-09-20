"""Optional MOD reference enrichment for Gallery."""
import time

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


def test_final_reference_replaces_only_assigned_resource_ink(tmp_path):
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
