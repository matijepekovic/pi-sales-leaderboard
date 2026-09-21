"""Card contact details use one safe, date-specific customer phone number."""
import hashlib

import pytest

from printer_app.gallery.files import GalleryFiles
from printer_app.gallery.policy import printed_phone, usable_phone
from printer_app.gallery.repository import GalleryRepository
from printer_app.gallery.service import GalleryService
from printer_app.mod_sheet_contract import ModSheetRecord


DAY = '2026-09-21'


@pytest.fixture
def gallery(tmp_path):
    root = tmp_path / 'gallery'
    service = GalleryService(GalleryRepository(root / 'gallery.db'), GalleryFiles(root))
    service.initialize()
    return service


def card(gallery, token, text='', day=DAY, work_order='00000011'):
    ident = hashlib.sha256(token.encode()).hexdigest()
    gallery.repository.enqueue(ident, token + '.pdf')
    gallery.repository.finish(ident, [dict(
        id=ident, import_id=ident, filename=token + '.pdf', page=1, part=1,
        text=f'Work Order Number: {work_order}\nLead Name: Customer Example\n{text}',
        lead_text='Lead Name: Customer Example', document_date=day, date_status='printed',
        bytes=5, created=100, recognition_revision=1,
    )])
    gallery.files.path('crops', ident).write_bytes(b'image')
    return ident


def reference(phone, work_order='00000011', source_id='source-one'):
    return ModSheetRecord(source_id=source_id, work_order_number=work_order, phone=phone)


@pytest.mark.parametrize(('value', 'expected'), [
    ('360-555-1212', ('360-555-1212', '3605551212')),
    (' (360) 555.1212 ', ('(360) 555.1212', '3605551212')),
    ('1 (360) 555-1212', ('1 (360) 555-1212', '13605551212')),
    ('+1 (360) 555-1212', ('+1 (360) 555-1212', '+13605551212')),
    ('+44 20 7946 0958', ('+44 20 7946 0958', '+442079460958')),
    ('', ('', '')),
    (None, ('', '')),
    ('unknown', ('', '')),
    ('555-1212', ('', '')),
    ('0000000000', ('', '')),
    ('360-555-1212 ext 42', ('', '')),
    ('360-555-1212 / 206-555-3434', ('', '')),
    ('3605551212,2065553434', ('', '')),
    ('3605551212\n2065553434', ('', '')),
    ('tel:3605551212', ('', '')),
    ('3605551212?body=hello', ('', '')),
    ('3605551212;123', ('', '')),
    ('*3605551212#', ('', '')),
    ('+00000000000', ('', '')),
    ('+1234567890123456', ('', '')),
    ('３６０５５５１２１２', ('', '')),
])
def test_phone_normalization_accepts_only_one_plain_dialable_number(value, expected):
    assert usable_phone(value) == expected


@pytest.mark.parametrize(('text', 'expected'), [
    ('Phone: (360) 555-1212\nScheduled Start: 9/21/2026 10:30 AM', '3605551212'),
    ('Address: 100 Main Street | Phone: 360.555.1212 | Set By: Someone', '3605551212'),
    ('PHONE: 3605551212\nPhone: (360) 555-1212', '3605551212'),
    ('Work Order Number: 3605551212\nAddress: 3605551212 Main Street', ''),
    ('Lead Description: Phone: 3605551212', ''),
    ('Call customer at 3605551212', ''),
    ('Phone 3605551212', ''),
    ('Phone: 3605551212 or 2065553434', ''),
    ('Phone: 3605551212\nPhone: 2065553434', ''),
    ('Phone: 3605551212\nPhone: unclear', ''),
])
def test_fallback_requires_one_unambiguous_labeled_phone_field(text, expected):
    assert printed_phone(text)[1] == expected


def test_existing_card_prefers_exact_normalized_reference_without_reprocessing(gallery):
    gallery.publish_reference_snapshot(DAY, 'final', [reference('+1 (360) 555-1212')], 100)
    ident = card(gallery, 'existing-card', 'Phone: 206-555-3434')

    item = gallery.item(ident)

    assert item['phone'] == '+1 (360) 555-1212'
    assert item['phone_dial'] == '+13605551212'
    assert 'Phone: 206-555-3434' in item['text']
    assert gallery.files.path('crops', ident).read_bytes() == b'image'


def test_phone_lookup_never_uses_same_work_order_from_another_date(gallery):
    gallery.publish_reference_snapshot(DAY, 'final', [reference('360-555-1212')], 100)
    older = card(gallery, 'older', day='2026-09-20')
    older_labeled = card(gallery, 'older-labeled', 'Phone: 206-555-3434', day='2026-09-20')

    assert gallery.item(older)['phone_dial'] == ''
    assert gallery.item(older_labeled)['phone_dial'] == '2065553434'


@pytest.mark.parametrize('value', ['unknown', '3605551212 / 2065553434'])
def test_invalid_source_phone_does_not_fall_back_to_an_older_number(gallery, value):
    gallery.publish_reference_snapshot(DAY, 'final', [reference(value)], 100)
    ident = card(gallery, 'stale-printed-number', 'Phone: 3605551212')

    assert gallery.item(ident)['phone'] == gallery.item(ident)['phone_dial'] == ''


@pytest.mark.parametrize('kind', ['morning', 'final'])
def test_ambiguous_reference_disables_contact_even_with_a_labeled_phone(gallery, kind):
    ident = card(gallery, 'ambiguous', 'Phone: 3605551212')
    gallery.publish_reference_snapshot(DAY, kind, [
        reference('3605551212'), reference('2065553434', source_id='source-two'),
    ], 100)

    assert gallery.item(ident)['phone'] == gallery.item(ident)['phone_dial'] == ''


def test_missing_phone_ignores_numbers_in_notes_and_other_fields(gallery):
    ident = card(gallery, 'missing-phone', 'Address: 3605551212 Main Street')
    gallery.note(ident, 'a' * 32, 'Reviewer', 'Phone: 2065553434')

    assert gallery.item(ident)['phone'] == gallery.item(ident)['phone_dial'] == ''


def test_blank_final_phone_can_use_unique_morning_reference(gallery):
    gallery.publish_reference_snapshot(DAY, 'morning', [reference('3605551212')], 100)
    gallery.publish_reference_snapshot(DAY, 'final', [reference('')], 101)
    ident = card(gallery, 'morning-fallback')

    assert gallery.item(ident)['phone_dial'] == '3605551212'


def test_changed_phone_updates_detail_and_offline_revision_without_changing_card(gallery):
    ident = card(gallery, 'updates')
    gallery.note(ident, 'b' * 32, 'Reviewer', 'Keep this note')
    gallery.publish_reference_snapshot(DAY, 'final', [reference('3605551212')], 100)
    before = gallery.item(ident)
    before_index = gallery.offline_index()['items'][0]

    gallery.publish_reference_snapshot(DAY, 'final', [reference('+1 206-555-3434')], 101)
    after = gallery.item(ident)
    index = gallery.offline_index()['items'][0]

    assert after['phone'] == '+1 206-555-3434'
    assert after['phone_dial'] == '+12065553434'
    assert index['search_revision'] == after['search_revision'] > before_index['search_revision']
    for field in ('id', 'notes', 'notes_text', 'document_date', 'image_revision'):
        assert after[field] == before[field]
    assert gallery.files.path('crops', ident).read_bytes() == b'image'


@pytest.mark.parametrize('captures', [(100, 101, 102), (100, 100, 100)])
def test_offline_revision_changes_when_phone_match_becomes_ambiguous_and_recovers(gallery, captures):
    ident = card(gallery, 'ambiguity-updates')
    older = card(gallery, 'unchanged-older-day', day='2026-09-20')
    gallery.publish_reference_snapshot(DAY, 'final', [reference('3605551212')], captures[0])
    before = gallery.item(ident)
    initial = {row['id']: row for row in gallery.offline_index()['items']}

    gallery.publish_reference_snapshot(DAY, 'final', [
        reference('3605551212'), reference('2065553434', source_id='source-two'),
    ], captures[1])
    ambiguous = gallery.item(ident)
    changed = {row['id']: row for row in gallery.offline_index()['items']}

    assert ambiguous['phone_dial'] == ''
    assert ambiguous['search_revision'] > before['search_revision']
    assert changed[ident]['search_revision'] == ambiguous['search_revision']
    assert changed[older] == initial[older]

    gallery.publish_reference_snapshot(DAY, 'final', [reference('3605551212')], captures[2])
    recovered = gallery.item(ident)
    latest = {row['id']: row for row in gallery.offline_index()['items']}
    assert recovered['phone_dial'] == '3605551212'
    assert recovered['search_revision'] > ambiguous['search_revision']
    assert latest[ident]['search_revision'] == recovered['search_revision']
    assert latest[older] == initial[older]


def test_detail_endpoint_exposes_phone_without_source_or_crop_changes(tmp_path):
    from printer_app.app import create_app
    from printer_app.config import Config
    from printer_app.tests.auth_helpers import gallery_client

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path / 'data', env_file=env,
                            secret_key='s' * 64, email_enabled=False))
    gallery = app.extensions['printer_gallery']
    gallery.initialize()
    ident = card(gallery, 'detail-api', 'Phone: (360) 555-1212')
    client = gallery_client(app)

    response = client.get('/gallery/api/items/' + ident)

    assert response.status_code == 200
    assert response.json['phone'] == '(360) 555-1212'
    assert response.json['phone_dial'] == '3605551212'
    assert not any('FSSK' in key for key in response.json)
    assert gallery.item('f' * 64) is None
