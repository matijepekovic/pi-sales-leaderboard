"""Source-owned placeholders survive partial, blank and unverified uploads."""
import hashlib

import pytest

from printer_app.mod_sheet_contract import WorkOrderReference
from printer_app.tests.test_gallery_reference import DAY, _gallery


def _record(number):
    return WorkOrderReference(source_id='source-' + number, work_order_number=number,
                              appointment_date=DAY, lead_name='Example Homeowner',
                              address='123 Example Street', phone='3605551212',
                              lead_source_id='lead-' + number, sales_lead_status='Open')


def _publish(gallery, tag, numbers, *, origin='scan', notes=True):
    ident = hashlib.sha256(tag.encode()).hexdigest()
    gallery.repository.enqueue(ident, tag + '.pdf', origin=origin, reference_day=DAY)
    job = gallery.repository.claim()
    assert job['id'] == ident
    directory = gallery.files.path('work', ident)
    directory.mkdir()
    entries = []
    for part, number in enumerate(numbers, 1):
        filename = f'{part}.png'
        (directory / filename).write_bytes(tag.encode())
        entry = dict(file=filename, page=1, part=part, bytes=len(tag),
                     document_date=DAY, date_status='printed',
                     text=f'Work Order Number: {number}\nLead Name: Example Homeowner',
                     mod_notes_present=notes)
        if origin == 'scan':
            entry['work_order_candidates'] = (number,)
        entries.append(entry)
    gallery.publish(job, {'items': entries}, directory)
    return gallery.import_job(ident)


def test_partial_scan_keeps_unmatched_placeholders_and_later_pull_fills_missing(tmp_path):
    gallery = _gallery(tmp_path)
    numbers = ('02000001', '02000002', '02000003')
    gallery.publish_reference_snapshot(DAY, 'morning', [_record(n) for n in numbers], 100)
    _publish(gallery, 'morning', numbers[:2], origin='morning', notes=False)
    first = {x['work_order_number']: x for x in gallery.search('', 0)['items']}
    gallery.note(first[numbers[0]]['id'], 'c' * 32, 'Example', 'Called customer')
    _publish(gallery, 'one-returned-card', numbers[:1])
    later = _publish(gallery, 'later-pull', numbers, origin='morning', notes=False)
    cards = {x['work_order_number']: x for x in gallery.search('', 0)['items']}
    assert set(cards) == set(numbers)
    assert cards[numbers[0]]['origin'] == 'scan'
    assert cards[numbers[0]]['id'] == first[numbers[0]]['id']
    assert gallery.item(cards[numbers[0]]['id'])['notes'][0]['body'] == 'Called customer'
    assert all(cards[n]['origin'] == 'morning' for n in numbers[1:])
    assert later['progress']['publication']['saved'] == 1
    assert later['progress']['publication']['skipped_existing'] == 2


@pytest.mark.parametrize('notes', [False, None])
def test_blank_or_unknown_scan_never_replaces_matching_placeholder(tmp_path, notes):
    gallery = _gallery(tmp_path)
    number = '02000001'
    gallery.publish_reference_snapshot(DAY, 'morning', [_record(number)], 100)
    _publish(gallery, 'placeholder', (number,), origin='morning', notes=False)
    before = gallery.search('', 0)['items'][0]
    job = _publish(gallery, 'uploaded-screenshot', (number,), notes=notes)
    gallery.publish_work_order_records((number,), (_record(number),), 200)
    cards = gallery.search('', 0)['items']
    assert len(cards) == 1 and cards[0]['id'] == before['id']
    assert cards[0]['origin'] == 'morning'
    assert gallery.files.path('crops', before['id']).read_bytes() == b'placeholder'
    if notes is False:
        assert job['retained'] == 0
        assert job['progress']['publication']['skipped_blank_notes'] == 1
    else:
        assert job['pending_review'] == 1
        assert job['items'][0]['mod_notes_status'] == 'unknown'
        assert job['progress']['publication']['needs_notes_review'] == 1


@pytest.mark.parametrize('later_notes', [False, True, None])
def test_notes_retry_cannot_remove_a_placeholder_until_notes_are_verified(tmp_path, later_notes):
    gallery = _gallery(tmp_path)
    number = '02000001'
    gallery.publish_reference_snapshot(DAY, 'morning', [_record(number)], 100)
    _publish(gallery, 'placeholder', (number,), origin='morning', notes=False)
    _publish(gallery, 'uncertain-upload', (number,), notes=None)
    assert gallery.repair_one(lambda path: dict(
        text='Work Order Number: ' + number, work_order_candidates=(number,),
        mod_notes_present=later_notes))
    gallery.publish_work_order_records((number,), (_record(number),), 200)
    cards = gallery.search('', 0)['items']
    assert len(cards) == 1
    assert cards[0]['origin'] == ('scan' if later_notes is True else 'morning')


def test_successful_notes_retry_keeps_newly_read_work_order_candidates(tmp_path):
    gallery = _gallery(tmp_path)
    number = '02000001'
    job = _publish(gallery, 'unreadable-upload', ('',), notes=None)
    assert gallery.repair_one(lambda path: dict(
        text='Work Order Number: ' + number, work_order_candidates=(number,),
        mod_notes_present=True))
    item = gallery.import_job(job['id'])['items'][0]
    assert item['mod_notes_status'] == 'present'
    assert tuple(item['work_order_candidates']) == (number,)
    gallery.publish_work_order_records((number,), (_record(number),), 200)
    assert gallery.search('', 0)['items'][0]['work_order_number'] == number
