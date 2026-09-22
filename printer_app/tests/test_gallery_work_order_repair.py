"""Repair saved OCR identity only where a card still lacks its Salesforce status."""
import hashlib

import pytest

from printer_app.gallery.files import GalleryFiles
from printer_app.gallery.policy import lead_key, work_order_key
from printer_app.gallery.repository import GalleryRepository
from printer_app.gallery.service import GalleryService
from printer_app.mod_sheet_contract import WorkOrderLeadStatus
from printer_app.tests.test_gallery_sales_lead_status import _seed


@pytest.fixture
def gallery(tmp_path):
    root = tmp_path / 'gallery'
    service = GalleryService(GalleryRepository(root / 'gallery.db'), GalleryFiles(root))
    service.initialize()
    return service


def _legacy_card(gallery, token, raw_number, saved_number, *, state='ACTIVE', status='',
                 lead='legacy-lead', day='2026-09-21'):
    """Represent a pre-fix saved card; current ingestion no longer creates this error."""
    ident = hashlib.sha256(token.encode()).hexdigest()
    repository = gallery.repository
    _seed(repository, ident=ident, work_order='02278850', day=day)
    with repository.connect() as c:
        c.execute("UPDATE items SET lead_name=?,lead_key=?,lead_status='confirmed' WHERE id=?",
                  ('Confirmed Customer', lead_key('Confirmed Customer'), ident))
    repository.add_note(ident, ident[:32], 'Office', 'Keep this note.')
    text = (f'Work Order Number: {raw_number}\nLead Name: Printed Customer\n'
            'Address: 123 Main Street\nPhone: 3605551212\n'
            'Local Scheduled Start Time: 9/21/2026 10:30 AM\n'
            'Assigned Service Resource: Existing Rep\nLead Description: Keep printed notes')
    with repository.connect() as c:
        c.execute("""UPDATE items SET text=?,work_order_number=?,work_order_key=?,state=?,
            sales_lead_status=?,lead_source_id=?,assigned_service_resource='Existing Rep',
            reference_kind='final',reference_source_id='existing-reference' WHERE id=?""",
                  (text, saved_number, work_order_key(saved_number), state, status, lead, ident))
    gallery.files.path('crops', ident).write_bytes(b'unchanged original scan:' + token.encode())
    return ident


def _snapshot(gallery, ident):
    with gallery.repository.connect() as c:
        row = dict(c.execute('SELECT * FROM items WHERE id=?', (ident,)).fetchone())
        notes = [dict(note) for note in c.execute('SELECT * FROM notes WHERE item_id=? ORDER BY id', (ident,))]
    return row, notes, gallery.files.path('crops', ident).read_bytes()


def test_repairs_multiple_saved_numbers_across_dates_without_changing_other_card_data(gallery):
    first = _legacy_card(gallery, 'first', '02278850 1', '022788501', day='2020-01-01')
    second = _legacy_card(gallery, 'second', '02345678 7', '023456787', day=None)
    valid = _legacy_card(gallery, 'valid', '03456789', '03456789', day='2030-01-01')
    before = {ident: _snapshot(gallery, ident) for ident in (first, second, valid)}

    assert gallery.repair_missing_work_orders() == {'repaired': 2, 'review': 0}

    for ident, number in ((first, '02278850'), (second, '02345678')):
        row, notes, image = _snapshot(gallery, ident)
        previous, previous_notes, previous_image = before[ident]
        assert row == dict(previous, work_order_number=number, work_order_key=number,
                           lead_source_id='', search_revision=previous['search_revision'] + 1)
        assert notes == previous_notes
        assert image == previous_image
    assert _snapshot(gallery, valid) == before[valid]
    assert gallery.work_order_numbers(missing_only=True) == ['02278850', '02345678', '03456789']
    repaired = {ident: _snapshot(gallery, ident) for ident in (first, second, valid)}
    assert gallery.repair_missing_work_orders() == {'repaired': 0, 'review': 0}
    assert {ident: _snapshot(gallery, ident) for ident in repaired} == repaired


def test_missing_only_refresh_leaves_filled_cards_untouched_even_for_the_same_lead(gallery):
    unresolved = _legacy_card(gallery, 'unresolved', '02278850 1', '022788501')
    same_lead = _legacy_card(gallery, 'same-lead', '02345678', '02345678',
                             status='Open', lead='shared-lead')
    same_order = _legacy_card(gallery, 'same-order', '02278850', '02278850',
                              status='Open', lead='shared-lead')
    malformed_filled = _legacy_card(gallery, 'filled-malformed', '03456789 2', '034567892',
                                    status='Sold', lead='other-lead')
    filled = {ident: _snapshot(gallery, ident) for ident in (same_lead, same_order, malformed_filled)}

    assert gallery.repair_missing_work_orders() == {'repaired': 1, 'review': 0}
    assert gallery.work_order_numbers(missing_only=True) == ['02278850']
    assert gallery.publish_lead_statuses(['02278850'], [
        WorkOrderLeadStatus('02278850', 'shared-lead', 'Closed - Sale')],
        200, missing_only=True) == {'count': 1, 'enriched': 1}

    current = gallery.item(unresolved)
    assert current['work_order_number'] == '02278850'
    assert current['lead_source_id'] == 'shared-lead'
    assert current['sales_lead_status'] == 'Closed - Sale'
    assert {ident: _snapshot(gallery, ident) for ident in filled} == filled
    assert gallery.work_order_numbers(missing_only=True) == []
    assert gallery.repair_missing_work_orders() == {'repaired': 0, 'review': 0}


@pytest.mark.parametrize('raw_number,saved_number,expected', [
    ('022788501', '022788501', '02278850'),
    ('02278850 02345678', '0227885002345678', '02278850'),
])
def test_overlong_or_noisy_saved_number_repairs_to_first_complete_eight_digits(
        gallery, raw_number, saved_number, expected):
    ident = _legacy_card(gallery, 'overlong-' + raw_number, raw_number, saved_number)
    before, notes, image = _snapshot(gallery, ident)

    assert gallery.repair_missing_work_orders() == {'repaired': 1, 'review': 0}

    after, after_notes, after_image = _snapshot(gallery, ident)
    assert after == dict(before, work_order_number=expected, work_order_key=expected,
                         lead_source_id='', search_revision=before['search_revision'] + 1)
    assert after_notes == notes
    assert after_image == image


def test_fragmented_saved_number_is_never_joined_and_requires_review(gallery):
    ident = _legacy_card(gallery, 'fragmented', '0227 8850', '02278850')
    before, notes, image = _snapshot(gallery, ident)

    assert gallery.repair_missing_work_orders() == {'repaired': 0, 'review': 1}

    after, after_notes, after_image = _snapshot(gallery, ident)
    assert after == dict(before, work_order_number='', work_order_key='', lead_source_id='',
                         state='REVIEW', search_revision=before['search_revision'] + 1)
    assert after_notes == notes
    assert after_image == image
    assert gallery.work_order_numbers(missing_only=True) == []
    assert gallery.item(ident) is None


def test_readable_repair_does_not_publish_a_card_already_awaiting_review(gallery):
    ident = _legacy_card(gallery, 'review', '02278850 1', '022788501', state='REVIEW')
    before, notes, image = _snapshot(gallery, ident)

    assert gallery.repair_missing_work_orders() == {'repaired': 1, 'review': 0}
    after, after_notes, after_image = _snapshot(gallery, ident)
    assert after == dict(before, work_order_number='02278850', work_order_key='02278850',
                         lead_source_id='', search_revision=before['search_revision'] + 1)
    assert after['state'] == 'REVIEW'
    assert after_notes == notes and after_image == image
    assert gallery.item(ident) is None


@pytest.mark.parametrize('column,value', [
    ('text', 'Work Order Number: 02345678\nLead Name: Corrected Customer'),
    ('work_order_number', '02345678'),
    ('work_order_key', '02345678'),
    ('sales_lead_status', 'Sold'),
    ('state', 'REVIEW'),
    ('state', 'DELETING'),
])
def test_repair_cannot_overwrite_card_changed_after_candidate_read(gallery, column, value):
    ident = _legacy_card(gallery, 'concurrent', '02278850 1', '022788501')
    candidate = gallery.repository.missing_work_order_items()[0]
    with gallery.repository.connect() as c:
        c.execute(f'UPDATE items SET {column}=? WHERE id=?', (value, ident))
    changed = _snapshot(gallery, ident)

    assert gallery.repository.repair_missing_work_order(candidate, '02278850') == 0
    assert _snapshot(gallery, ident) == changed


def test_repair_cannot_overwrite_a_review_card_approved_after_candidate_read(gallery):
    ident = _legacy_card(gallery, 'approved-race', '022788501', '022788501', state='REVIEW')
    candidate = gallery.repository.missing_work_order_items()[0]
    row, _, _ = _snapshot(gallery, ident)
    assert gallery.repository.approve_import_item(row['import_id'], ident)
    approved = _snapshot(gallery, ident)

    assert gallery.repository.repair_missing_work_order(candidate, '') == 0
    assert _snapshot(gallery, ident) == approved


def test_missing_only_publish_preserves_status_arriving_while_lookup_is_running(gallery):
    ident = _legacy_card(gallery, 'status-race', '02278850', '02278850', lead='shared-lead')
    requested = gallery.work_order_numbers(missing_only=True)
    with gallery.repository.connect() as c:
        c.execute("UPDATE items SET sales_lead_status='Sold' WHERE id=?", (ident,))
    filled = _snapshot(gallery, ident)

    assert gallery.publish_lead_statuses(requested, [
        WorkOrderLeadStatus('02278850', 'shared-lead', 'Open')],
        200, missing_only=True) == {'count': 1, 'enriched': 0}
    assert _snapshot(gallery, ident) == filled
