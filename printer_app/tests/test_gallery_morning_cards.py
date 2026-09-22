"""Morning MOD cards become scanned cards without changing their saved identity."""
from dataclasses import asdict, replace
from datetime import datetime
import hashlib
from zoneinfo import ZoneInfo

import pytest

from printer_app.gallery.files import GalleryFiles
from printer_app.gallery.policy import GalleryOptions
from printer_app.gallery.repository import GalleryRepository
from printer_app.gallery.service import GalleryService
from printer_app.mod_sheet_contract import ModSheetRecord


DAY = '2026-09-21'
EARLIER_DAY = '2026-09-20'


@pytest.fixture
def gallery(tmp_path, monkeypatch):
    noon = datetime(2026, 9, 21, 12, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(noon, tz)

    monkeypatch.setattr('printer_app.gallery.service.time.time', lambda: noon)
    monkeypatch.setattr('printer_app.gallery.service.datetime', FrozenDatetime)
    root = tmp_path / 'gallery'
    service = GalleryService(GalleryRepository(root / 'gallery.db'), GalleryFiles(root))
    service.initialize()
    return service


def _record(work_order='00000011', **changes):
    record = ModSheetRecord(
        source_id='source-' + work_order,
        work_order_number=work_order,
        local_scheduled_start_time='9/21/2026 10:30 AM',
        canvass_set_by='Canvasser Example',
        lead_name='Reference Customer',
        address='101 Reference Street',
        phone='5551234567',
        scheduled_start='2026.09.21 ; 10:30:00 AM',
        assigned_service_resources=('First Resource', 'Second Resource'),
        set_by='Setter Example',
        work_type='Sales Appointment',
        product_interest='Windows',
        source='Referral',
        sub_source='Customer Referral',
        lead_description='Reference appointment details',
    )
    return replace(record, **changes)


def _publish(gallery, token, cards, *, morning=False, day=DAY):
    """Supply the existing processor's prepared images and manifest to publishing."""
    payload = b'%PDF-1.4\n' + token.encode()
    options = GalleryOptions(enabled=True)
    if morning:
        import_id = gallery.offer_morning(day, token + '.pdf', payload, options)
    else:
        import_id = gallery.offer(token + '.pdf', payload, options)
    job = gallery.repository.claim()
    assert job is not None
    assert job['id'] == import_id
    assert job['origin'] == ('morning' if morning else 'scan')
    if morning:
        assert job['reference_day'] == day
    directory = gallery.files.path('work', import_id)
    directory.mkdir()
    manifest = {'items': []}
    for part, card in enumerate(cards, 1):
        work_order, card_day = card
        crop = (token + ':' + str(part)).encode()
        filename = str(part) + '.png'
        (directory / filename).write_bytes(crop)
        text = (
            f'Work Order Number: {work_order}\n'
            'Lead Name: Printed Customer\n'
            'Address: 100 Printed Street\n'
            f'Local Scheduled Start Time: {card_day} 10:30 AM\n'
            f'Scheduled Start: {card_day} 10:30 AM'
        )
        manifest['items'].append({
            'file': filename, 'page': 1, 'part': part, 'bytes': len(crop),
            'text': text, 'lead_text': 'Lead Name: Printed Customer',
            'document_date': card_day, 'date_status': 'printed',
        })
    gallery.publish(job, manifest, directory)
    return import_id


def _row(gallery, work_order, day=DAY):
    return next(row for row in gallery.repository.reference_items(day)
                if row['work_order_number'] == work_order)


def test_morning_pdf_creates_searchable_cards_with_saved_source_data(gallery):
    reference = _record()
    gallery.publish_reference_snapshot(DAY, 'morning', [reference], 1.0)

    _publish(gallery, 'morning', [('00000011', DAY)], morning=True)
    row = _row(gallery, '00000011')
    item = gallery.item(row['id'])

    assert item['origin'] == 'morning'
    assert item['reference_kind'] == 'morning'
    assert item['lead_name'] == reference.lead_name
    assert item['address'] == reference.address
    for query in ('Reference', '5551234567', 'Canvasser', 'Windows', 'appointment details'):
        assert gallery.search(query, 0)['total'] == 1
    assert item['assigned_service_resource'] == ''
    assert gallery.search('First Resource', 0)['total'] == 0
    assert gallery.search('Second Resource', 0)['total'] == 0
    assert gallery.files.path('crops', item['id']).read_bytes() == b'morning:1'


def test_hourly_reference_refresh_preserves_cards_and_enriches_later_scans(gallery, tmp_path):
    from types import SimpleNamespace

    from printer_app.db import Database
    from printer_app.gallery.bootstrap import GalleryReferenceInbox
    from printer_app.mod_sheets.repository import ModSheetAutomationRepository
    from printer_app.mod_sheets.service import ModSheetReferenceDeliveryService

    _publish(gallery, 'today-morning', [('00000011', DAY), ('00000022', DAY)], morning=True)
    _publish(gallery, 'earlier-morning', [('00000011', EARLIER_DAY)], morning=True, day=EARLIER_DAY)
    matched_id, absent_id = _row(gallery, '00000011')['id'], _row(gallery, '00000022')['id']
    earlier_id = _row(gallery, '00000011', EARLIER_DAY)['id']
    gallery.note(matched_id, 'f' * 32, 'Reviewer', 'Keep this manual note')
    before, earlier = gallery.item(matched_id), gallery.item(earlier_id)
    calls = []
    current_records = [_record(), _record('00000033', assigned_service_resources=('Cancelled Rep',))]
    failure = [False]

    def records(**filters):
        calls.append(filters)
        if failure[0]:
            raise RuntimeError('Source unavailable')
        return tuple(current_records)

    zone = ZoneInfo('America/Los_Angeles')
    now = [datetime(2026, 9, 21, 12, tzinfo=zone).timestamp()]
    delivery = ModSheetReferenceDeliveryService(
        ModSheetAutomationRepository(Database(tmp_path / 'printer.db')),
        SimpleNamespace(
            records=records,
            work_orders=lambda numbers: tuple(
                replace(record, appointment_date=DAY)
                for record in current_records
                if record.work_order_number in set(numbers)
            ),
            lead_statuses=lambda numbers: (),
        ), object(), GalleryReferenceInbox(tmp_path),
        'America/Los_Angeles', clock=lambda: now[0],
    )

    assert delivery.run_hourly()['enriched'] == 1
    item = gallery.item(matched_id)
    assert item['assigned_service_resource'] == 'First Resource, Second Resource'
    assert gallery.search('Second Resource', 0, field='rep')['total'] == 1
    assert item['notes'] == before['notes']
    assert item['image_revision'] == before['image_revision']
    assert item['search_revision'] > before['search_revision']
    assert gallery.files.path('crops', matched_id).read_bytes() == b'today-morning:1'
    assert gallery.item(earlier_id) == earlier
    assert gallery.item(absent_id) is not None
    assert not gallery.repository.scans_received(DAY)
    assert gallery.repository.claim() is None
    assert gallery.search('', 0)['total'] == 3

    now[0] = datetime(2026, 9, 21, 13, tzinfo=zone).timestamp()
    failure[0] = True
    assert delivery.run_hourly()['status'] == 'failed'
    assert gallery.item(matched_id) == item
    failure[0] = False
    now[0] = datetime(2026, 9, 21, 14, tzinfo=zone).timestamp()
    current_records[0] = _record(assigned_service_resources=())
    assert delivery.run_hourly()['status'] == 'complete'
    unassigned = gallery.item(matched_id)
    assert unassigned['assigned_service_resource'] == ''
    assert unassigned['notes'] == before['notes']
    assert unassigned['image_revision'] == before['image_revision']
    assert unassigned['search_revision'] > item['search_revision']
    assert 'First Resource' not in unassigned['text']
    assert 'Second Resource' not in unassigned['text']
    for field in (None, 'rep'):
        assert gallery.search('First Resource', 0, field=field)['total'] == 0
        assert gallery.search('Second Resource', 0, field=field)['total'] == 0
    offline = next(row for row in gallery.offline_index()['items'] if row['id'] == matched_id)
    assert offline['assigned_service_resource'] == ''
    assert offline['search_revision'] == unassigned['search_revision']

    now[0] = datetime(2026, 9, 21, 15, tzinfo=zone).timestamp()
    current_records[0] = _record(assigned_service_resources=('Changed Rep', 'Additional Rep'))
    assert delivery.run_hourly()['status'] == 'complete'
    assert gallery.item(matched_id)['assigned_service_resource'] == 'Changed Rep, Additional Rep'
    assert gallery.search('Second Resource', 0, field='rep')['total'] == 0
    assert gallery.search('Additional Rep', 0, field='rep')['total'] == 1
    assert gallery.item(absent_id) is not None

    now[0] = datetime(2026, 9, 21, 23, tzinfo=zone).timestamp()
    current_records[0] = _record(assigned_service_resources=('Final Rep',))
    assert delivery.run_final()['status'] == 'complete'
    final_snapshot = gallery.repository.reference_snapshot(DAY, 'final')
    now[0] = datetime(2026, 9, 22, 0, tzinfo=zone).timestamp()
    current_records[:] = [_record(assigned_service_resources=('Next Day Rep',))]
    assert delivery.run_hourly()['status'] == 'complete'
    assert gallery.repository.reference_snapshot(DAY, 'final') == final_snapshot
    assert gallery.item(matched_id)['assigned_service_resource'] == 'Final Rep'
    assert gallery.item(earlier_id) == earlier
    assert not gallery.repository.scans_received(DAY)
    assert gallery.repository.claim() is None

    # Only an actual scan reconciles the morning cards. The prior day's final
    # snapshot still supplies every resource when an appointment arrives later.
    _publish(gallery, 'late-scan', [('00000011', DAY), ('00000033', DAY)])
    assert gallery.item(matched_id)['assigned_service_resource'] == 'Final Rep'
    assert gallery.item(matched_id)['notes'] == before['notes']
    assert gallery.item(_row(gallery, '00000033')['id'])['assigned_service_resource'] == 'Cancelled Rep'
    assert gallery.item(absent_id) is None
    assert gallery.item(earlier_id) == earlier
    assert gallery.files.path('crops', matched_id).read_bytes() == b'late-scan:1'
    assert gallery.repository.reference_snapshot(DAY, 'final') == final_snapshot
    assert [call['start_date'] for call in calls] == [DAY, DAY, DAY, DAY, DAY, '2026-09-22']
    assert all(call['end_date'] == call['start_date'] and not call['remove_canceled']
               and not call['remove_unconfirmed'] and call['limit'] is None for call in calls)


def test_scan_replaces_morning_image_in_place_and_preserves_saved_notes(gallery):
    gallery.publish_reference_snapshot(DAY, 'morning', [_record()], 1.0)
    _publish(gallery, 'morning', [('00000011', DAY)], morning=True)
    original_id = _row(gallery, '00000011')['id']
    gallery.note(original_id, 'a' * 32, 'Reviewer', 'Keep this manual note')
    before = gallery.item(original_id)

    _publish(gallery, 'scanned', [('00000011', DAY)])
    after = gallery.item(original_id)

    assert after is not None
    assert after['id'] == original_id
    assert after['origin'] == 'scan'
    assert after['notes'] == before['notes']
    assert after['notes_text'] == before['notes_text']
    assert after['image_revision'] != before['image_revision']
    assert after['search_revision'] > before['search_revision']
    offline = gallery.offline_index()['items'][0]
    assert offline['image_revision'] == after['image_revision']
    assert offline['search_revision'] == after['search_revision']
    assert gallery.files.path('crops', original_id).read_bytes() == b'scanned:1'
    assert gallery.search('', 0)['total'] == 1
    assert gallery.search('manual note', 0)['total'] == 1
    assert gallery.search('Second Resource', 0)['total'] == 0


def test_repeated_scan_keeps_one_card_and_its_original_identity(gallery):
    _publish(gallery, 'first-scan', [('00000011', DAY)])
    original_id = _row(gallery, '00000011')['id']
    gallery.note(original_id, 'b' * 32, 'Reviewer', 'Carry this forward')

    _publish(gallery, 'repeat-scan', [('00000011', DAY)])

    assert gallery.search('', 0)['total'] == 1
    assert _row(gallery, '00000011')['id'] == original_id
    assert gallery.files.path('crops', original_id).read_bytes() == b'repeat-scan:1'
    assert gallery.item(original_id)['notes'][0]['body'] == 'Carry this forward'


def test_same_work_order_on_different_date_does_not_replace_morning_card(gallery):
    _publish(gallery, 'morning', [('00000011', DAY)], morning=True)
    morning_id = _row(gallery, '00000011')['id']

    _publish(gallery, 'earlier-scan', [('00000011', EARLIER_DAY)])

    assert gallery.item(morning_id)['origin'] == 'morning'
    assert gallery.files.path('crops', morning_id).read_bytes() == b'morning:1'
    assert _row(gallery, '00000011', EARLIER_DAY)['id'] != morning_id
    assert gallery.search('', 0)['total'] == 2


def test_different_work_order_is_not_merged_and_unmatched_morning_card_is_removed(gallery):
    _publish(gallery, 'morning', [('00000011', DAY)], morning=True)
    morning_id = _row(gallery, '00000011')['id']
    gallery.note(morning_id, 'c' * 32, 'Reviewer', 'Belongs to another work order')

    _publish(gallery, 'other-work-order', [('00000022', DAY)])
    scanned = gallery.item(_row(gallery, '00000022')['id'])

    assert scanned['id'] != morning_id
    assert scanned['notes'] == []
    assert gallery.item(morning_id) is None
    assert not gallery.files.path('crops', morning_id).exists()
    assert gallery.search('', 0)['total'] == 1


def test_scan_reconciles_only_its_dates_and_never_deletes_existing_scans(gallery):
    _publish(gallery, 'morning', [('00000011', DAY), ('00000022', DAY)], morning=True)
    matched_id = _row(gallery, '00000011')['id']
    absent_id = _row(gallery, '00000022')['id']
    _publish(gallery, 'older-scan', [('00000033', EARLIER_DAY)])
    older_scan_id = _row(gallery, '00000033', EARLIER_DAY)['id']

    _publish(gallery, 'current-scan', [('00000011', DAY)])
    _publish(gallery, 'additional-scan', [('00000044', DAY)])

    assert gallery.item(absent_id) is None
    assert gallery.item(matched_id)['origin'] == 'scan'
    assert gallery.item(older_scan_id)['origin'] == 'scan'
    assert gallery.search('', 0)['total'] == 3


def test_completed_day_does_not_recreate_morning_cards(gallery):
    _publish(gallery, 'scanned-first', [('00000011', DAY)])
    original_id = _row(gallery, '00000011')['id']

    _publish(gallery, 'late-morning', [('00000011', DAY), ('00000022', DAY)], morning=True)

    assert gallery.search('', 0)['total'] == 1
    assert _row(gallery, '00000011')['id'] == original_id
    assert gallery.item(original_id)['origin'] == 'scan'
    assert gallery.files.path('crops', original_id).read_bytes() == b'scanned-first:1'


def test_reconciliation_keeps_complete_reference_snapshot_for_later_scans(gallery):
    records = [_record('00000011'), _record('00000022', lead_name='Later Customer')]
    gallery.publish_reference_snapshot(DAY, 'morning', records, 1.0)
    _publish(gallery, 'morning', [('00000011', DAY), ('00000022', DAY)], morning=True)
    removed_id = _row(gallery, '00000022')['id']
    _publish(gallery, 'first-scan', [('00000011', DAY)])
    assert gallery.item(removed_id) is None

    snapshot, stored = gallery.repository.reference_snapshot(DAY, 'morning')
    assert snapshot['count'] == 2
    for expected in records:
        actual = next(row for row in stored if row['source_id'] == expected.source_id)
        assert {key: actual[key] for key in asdict(expected)} == asdict(expected)

    _publish(gallery, 'later-scan', [('00000022', DAY)])
    item = gallery.item(_row(gallery, '00000022')['id'])
    assert item['lead_name'] == 'Later Customer'
    assert item['address'] == '101 Reference Street'
    assert item['assigned_service_resource'] == ''
    assert gallery.search('Second Resource', 0)['total'] == 0
    assert gallery.search('5551234567', 0)['total'] == 2


def test_final_data_changes_search_revision_without_changing_card_image(gallery):
    gallery.publish_reference_snapshot(DAY, 'morning', [_record()], 1.0)
    _publish(gallery, 'morning', [('00000011', DAY)], morning=True)
    ident = _row(gallery, '00000011')['id']
    before = gallery.item(ident)
    image = gallery.files.path('crops', ident).read_bytes()

    gallery.publish_reference_snapshot(DAY, 'final', [_record()], 2.0)
    after = gallery.item(ident)

    assert after['image_revision'] == before['image_revision']
    assert gallery.files.path('crops', ident).read_bytes() == image
    assert after['search_revision'] > before['search_revision']
    assert after['assigned_service_resource'] == 'First Resource, Second Resource'
    assert gallery.search('Second Resource', 0)['total'] == 1
    offline = gallery.offline_index()['items'][0]
    assert offline['image_revision'] == before['image_revision']
    assert offline['search_revision'] == after['search_revision']
    assert offline['assigned_service_resource'] == after['assigned_service_resource']


def test_later_scan_prefers_final_assignments_over_saved_morning_data(gallery):
    gallery.publish_reference_snapshot(DAY, 'morning', [_record()], 1.0)
    final = _record(lead_name='Final Customer', assigned_service_resources=('Final Resource',))
    gallery.publish_reference_snapshot(DAY, 'final', [final], 2.0)

    _publish(gallery, 'late-scan', [('00000011', DAY)])
    item = gallery.item(_row(gallery, '00000011')['id'])

    assert item['reference_kind'] == 'final'
    assert item['lead_name'] == 'Final Customer'
    assert item['assigned_service_resource'] == 'Final Resource'
    assert gallery.search('First Resource', 0)['total'] == 0


def test_scan_keeps_morning_identity_when_final_source_fields_are_blank(gallery):
    gallery.publish_reference_snapshot(DAY, 'morning', [_record()], 1.0)
    _publish(gallery, 'morning', [('00000011', DAY)], morning=True)
    ident = _row(gallery, '00000011')['id']
    final = _record(
        lead_name='', address='', phone='', canvass_set_by='', lead_description='',
        assigned_service_resources=('Final Resource',),
    )
    gallery.publish_reference_snapshot(DAY, 'final', [final], 2.0)

    _publish(gallery, 'scan-after-blank-final', [('00000011', DAY)])
    item = gallery.item(ident)

    assert item['origin'] == 'scan'
    assert item['reference_kind'] == 'final'
    assert item['lead_name'] == 'Reference Customer'
    assert item['address'] == '101 Reference Street'
    assert item['assigned_service_resource'] == 'Final Resource'
    for query in ('Reference Customer', 'Reference Street', '5551234567',
                  'Canvasser', 'appointment details', 'Final Resource'):
        assert gallery.search(query, 0)['total'] == 1, query
    for query in ('Printed Customer', 'Printed Street', 'First Resource', 'Second Resource'):
        assert gallery.search(query, 0)['total'] == 0, query
    assert gallery.files.path('crops', ident).read_bytes() == b'scan-after-blank-final:1'


def test_scan_keeps_previous_source_identity_and_clears_confirmed_unassigned_resources(gallery):
    gallery.publish_reference_snapshot(DAY, 'final', [_record()], 1.0)
    _publish(gallery, 'original-scan', [('00000011', DAY)])
    ident = _row(gallery, '00000011')['id']
    before = gallery.item(ident)
    blank = _record(lead_name='', address='', assigned_service_resources=())
    gallery.publish_reference_snapshot(DAY, 'final', [blank], 2.0)
    assert gallery.repository.reference_snapshot(DAY, 'morning')[0] is None

    _publish(gallery, 'replacement-scan', [('00000011', DAY)])
    item = gallery.item(ident)

    assert item['lead_name'] == before['lead_name'] == 'Reference Customer'
    assert item['address'] == before['address'] == '101 Reference Street'
    assert item['assigned_service_resource'] == ''
    for query in ('Reference Customer', 'Reference Street'):
        assert gallery.search(query, 0)['total'] == 1, query
    for query in ('Printed Customer', 'Printed Street', 'First Resource', 'Second Resource'):
        assert gallery.search(query, 0)['total'] == 0, query
    assert item['image_revision'] != before['image_revision']
    assert gallery.files.path('crops', ident).read_bytes() == b'replacement-scan:1'


def test_card_without_work_order_stays_in_review(gallery):
    import_id = _publish(gallery, 'unidentified-scan', [('', DAY)])
    card_id = hashlib.sha256(f'{import_id}:1:1'.encode()).hexdigest()

    item = gallery.import_item(import_id, card_id)

    assert item['state'] == 'REVIEW'
    assert item['work_order_number'] == ''
    assert gallery.item(card_id) is None
    assert gallery.search('', 0)['total'] == 0


def test_yesterdays_morning_cards_remain_until_scans_or_normal_retention(gallery):
    gallery.publish_reference_snapshot(EARLIER_DAY, 'morning', [_record()], 1.0)
    _publish(gallery, 'yesterday-morning', [('00000011', EARLIER_DAY)],
             morning=True, day=EARLIER_DAY)
    ident = _row(gallery, '00000011', EARLIER_DAY)['id']

    gallery.expire(90, 'America/Los_Angeles')

    assert gallery.item(ident)['origin'] == 'morning'
    assert gallery.files.path('crops', ident).read_bytes() == b'yesterday-morning:1'
    assert gallery.repository.reference_snapshot(EARLIER_DAY, 'morning')[0]['count'] == 1
    assert not gallery.repository.scans_received(EARLIER_DAY)


def test_cleanup_failure_does_not_block_scanned_card_and_retries_later(gallery, monkeypatch):
    gallery.publish_reference_snapshot(DAY, 'final', [_record()], 2.0)
    _publish(gallery, 'morning', [('00000011', DAY), ('00000022', DAY)], morning=True)
    retired = _row(gallery, '00000022')['id']
    remove = gallery.files.remove

    def unavailable(category, ident):
        if category == 'crops' and ident == retired:
            raise OSError('Temporary file is busy')
        return remove(category, ident)

    monkeypatch.setattr(gallery.files, 'remove', unavailable)
    _publish(gallery, 'scan', [('00000011', DAY)])

    assert gallery.search('', 0)['total'] == 1
    assert gallery.search('Second Resource', 0)['total'] == 1
    assert gallery.item(retired) is None
    assert gallery.files.path('crops', retired).exists()
    monkeypatch.setattr(gallery.files, 'remove', remove)
    gallery.expire(90, 'America/Los_Angeles')
    assert not gallery.files.path('crops', retired).exists()
