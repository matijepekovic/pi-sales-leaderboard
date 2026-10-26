"""Strict scan candidates stay separate from stored and manual work-order text."""
import pytest

from printer_app.gallery.policy import (
    checked_work_order_number, printed_work_order_number,
    scanned_work_order_candidates, work_order_key,
)


@pytest.mark.parametrize('text,expected', [
    ('Work Order Number: 02278850 1', '02278850'),
    ('Work Order Number: 1 02278850', '02278850'),
    ('Work Order Number: 00000001', '00000001'),
    ('work\torder\tnumber ; 02278850', '02278850'),
    ('Work Order Number 02278850', '02278850'),
    ('| Work Order Number: [02278850] | Lead Name: Jasmine', '02278850'),
    ('Work Order Number: —02278850—', '02278850'),
    ('Work Order Number: 02278850 Local Scheduled Start Time: 9:00 AM', '02278850'),
    ('Work Order Number: 02278850 Address: 12345678 Example Street', '02278850'),
    ('Work Order Number: 02278850\nPhone: 12345678', '02278850'),
    ('Work Order Number: 02278850 Work Order Number: 02278850', '02278850'),
    ('Work Order Number: 02278850\nWork Order Number: 02278850 1', '02278850'),
    ('Work Order Number: 022788501', '02278850'),
    ('Work Order Number: 102278850', '10227885'),
    ('Work Order Number: 0227885012345678', '02278850'),
    ('Work Order Number: O2278B5!', '02278851'),
])
def test_reads_a_complete_eight_digit_token_without_joining_ocr_noise(text, expected):
    assert printed_work_order_number(text) == expected


@pytest.mark.parametrize('value', [
    '', '1', '2278850',
    '0227 8850', '022 788 50', '0227-8850', '0227/8850',
    'WO02278850', '02278850A', 'A02278850B',
    '０２２７８８５０', '٠٢٢٧٨٨٥٠', '0227885０',
    'é02278850', '02278850é', '٢02278850', '02278850٢',
    'A\u030102278850', '02278850\u0301', '02278850\u200dA',
])
def test_does_not_invent_a_number_from_fragments_or_unicode(value):
    assert printed_work_order_number('Work Order Number: ' + value) == ''


@pytest.mark.parametrize('text,expected', [
    ('Work Order Number: 02278850 02345678', '02278850'),
    ('Work Order Number: 02278850\nWork Order Number: 02345678', '02278850'),
    ('Work Order Number: 02278850 Work Order Number: 02345678', '02278850'),
    ('Work Order Number: 02278850\nWork Order Number:', '02278850'),
    ('Work Order Number:\nWork Order Number: 02278850', '02278850'),
    ('Work Order Number: 02278850\nWork Order Number: 023456789', '02278850'),
    ('Work Order Number: 0227 8850\nWork Order Number: 02278850', '02278850'),
])
def test_first_complete_eight_digits_win_without_joining_fragments(text, expected):
    assert printed_work_order_number(text) == expected


@pytest.mark.parametrize('text', [
    None, '', '02278850', 'Notes: 02278850',
    'Work Order Number:\n02278850',
    'Work Order Number: 1\nAddress: 02278850 Example Street',
    'Work Order Number: 1 | Phone: 02278850',
    'Work Order Number: 1 Address: 02278850 Example Street',
    'Work Order Number: 1 Lead Description: 02278850',
    'Work Order Number: 1 Notes: 02278850',
    'Work Order Number: 1 Appointment Date: 20260921',
    'Work Order Number: 1 Scheduled Start: 20260921',
    'Address: 02278850 Example Street\nWork Order Number:',
])
def test_only_the_explicit_single_line_work_order_field_supplies_the_number(text):
    assert printed_work_order_number(text) == ''


def test_external_work_order_key_keeps_its_general_normalization_contract():
    assert work_order_key('WO-0042 / A') == 'wo0042a'
    assert work_order_key('02278850') == '02278850'


@pytest.mark.parametrize('value,expected', [
    ('02278850', '02278850'),
    ('022788501', '02278850'),
    ('  102278850  ', '10227885'),
    ('WO 02278850', '02278850'),
])
def test_manual_work_order_uses_same_first_eight_digit_rule(value, expected):
    assert checked_work_order_number(value) == expected


@pytest.mark.parametrize('value', ['', '1234567', '0227 8850', 'WO02278850A'])
def test_manual_work_order_requires_one_contiguous_eight_digit_token(value):
    with pytest.raises(ValueError):
        checked_work_order_number(value)


@pytest.mark.parametrize('value', [
    None, '', '0227885', '2278850', '022788501', '102278850', '0227885012345678',
    '00000001', '03456789', '32278850',
    '0227 8850', '0227-8850', '0227/8850',
    'WO02278850', '02278850A', 'A02278850B',
    '０２２７８８５０', '٠٢٢٧٨٨٥٠', '0227885０',
    'é02278850', '02278850é', '٢02278850', '02278850٢',
    'A\u030102278850', '02278850\u0301', '02278850\u200dA',
    'O2278850', '02278B50', '0227885!',
])
def test_scan_candidate_validation_never_repairs_an_invalid_number(value):
    assert scanned_work_order_candidates(value) == ()
    assert scanned_work_order_candidates('Work Order Number: ' + str(value or ''), labeled=True) == ()


@pytest.mark.parametrize('value,expected', [
    ('02278850', ('02278850',)),
    (' [02278850] ', ('02278850',)),
    ('—02278850—', ('02278850',)),
    ('02278850 02345678 02278850', ('02278850', '02345678')),
    ('00000001 02278850 02345678', ('02278850', '02345678')),
    ('022788501 02345678 0227885', ('02345678',)),
])
def test_scan_candidates_preserve_every_valid_unique_answer_without_reordering(value, expected):
    assert scanned_work_order_candidates(value) == expected


def test_labeled_scan_reads_every_work_order_field_without_crossing_other_fields():
    text = (
        'Work Order Number: 02278850 02345678 Address: 02999999 Main Street\n'
        'Work Order Number: 022788501 Phone: 02111111\n'
        'Work Order Number: 02456789\n'
        'Work Order Number: 02278850\n'
        'Work Order Number:\n02555555\n'
        'Notes: 02666666'
    )
    assert scanned_work_order_candidates(text, labeled=True) == ('02278850', '02345678', '02456789')


def test_scan_validation_does_not_change_stored_or_manual_identity_compatibility():
    for raw, expected in [('00000001', '00000001'), ('03456789', '03456789'),
                          ('102278850', '10227885'), ('022788501', '02278850')]:
        assert printed_work_order_number('Work Order Number: ' + raw) == expected
        assert checked_work_order_number(raw) == expected
        assert scanned_work_order_candidates(raw) == ()


def test_reader_glyph_normalization_must_preserve_positions_before_scan_validation():
    from printer_app.gallery.numeric_parser import normalize_numeric_token

    assert scanned_work_order_candidates('O2278B5!') == ()
    assert scanned_work_order_candidates(normalize_numeric_token('O2278B5!')) == ('02278851',)
    assert scanned_work_order_candidates(normalize_numeric_token('O2278B5!1')) == ()
    assert scanned_work_order_candidates(normalize_numeric_token('O2278B5')) == ()


def test_fallback_whole_card_recovers_wrapped_work_order_value_only_at_explicit_label():
    from printer_app.gallery.recognition import _work_order_candidates
    # search_text() preserves OCR line breaks; the Gallery Job diagnostic
    # collapses them into one line, masking the original parsing failure.
    raw = ('i|Work Order Number:\n02314464 Local Scheduled Start Time: Oct 20 2026 03:00 PM\n'
           'Lead Name: Example Customer Address: 727 West Ash Street')
    assert printed_work_order_number(raw) == ''  # Existing one-line contract unchanged.
    assert scanned_work_order_candidates(raw, labeled=True) == ()
    assert _work_order_candidates(raw, labeled=True) == ('02314464',)
    assert _work_order_candidates(raw.replace('\n', '\r\n'), labeled=True) == ('02314464',)


@pytest.mark.parametrize('raw', [
    'Work Order Number:\nLead Name: Example Customer\nPhone: 02314464',
    'Work Order Number:\n\n02314464',
    'Work Order Number:\n023144649',
    'Work Order Number:\n0231 4464',
    'Work Order Number:\nAddress: 02314464 Main St',
    'Notes: 02314464\nWork Order Number:',
])
def test_fallback_wrapped_field_does_not_steal_other_numbers(raw):
    from printer_app.gallery.recognition import _work_order_candidates
    assert _work_order_candidates(raw, labeled=True) == ()


def test_saved_fallback_diagnostics_recover_existing_card_without_rescanning(tmp_path):
    from printer_app.gallery.bootstrap import build
    from printer_app.gallery.recognition import saved_fallback_candidates
    from printer_app.tests.test_gallery_scan_identity import _record
    from printer_app.tests.test_gallery_reference import DAY

    gallery = build(tmp_path)
    gallery.initialize()
    source = 'a' * 64
    item_id = 'b' * 64
    gallery.repository.enqueue(source, 'scan.pdf')
    retained_reads = [
        {'label': 'Numerical parser', 'psm': None, 'text': '', 'candidate': '', 'ok': False},
        {'label': 'Fallback whole card', 'psm': 6,
         'text': 'i|Work Order Number: 02314464 Local Scheduled Start Time: Oct 20 2026',
         'candidate': '', 'ok': True},
        {'label': 'Fallback whole card', 'psm': 11,
         'text': 'i|Work Order Number: 02314464 Lead Name: Example Customer',
         'candidate': '', 'ok': True},
    ]
    assert saved_fallback_candidates(retained_reads) == ('02314464',)
    gallery.repository.finish(source, [dict(
        id=item_id, import_id=source, page=1, part=1,
        filename='scan.pdf', text='Lead Name: Example Customer', origin='scan',
        work_order_candidates=(), work_order_reads=retained_reads,
        mod_notes_status='present', document_date=DAY, date_status='printed',
        bytes=21, created=12345,
    )])
    gallery.files.path('crops', item_id).write_bytes(b'original-card')
    before = gallery.repository.import_item(source, item_id)
    assert before['work_order_candidates'] == ()
    assert before['state'] == 'REVIEW'
    assert gallery.item(item_id) is None

    assert gallery.recover_saved_fallback_candidates() == 1
    assert gallery.recover_saved_fallback_candidates() == 0
    recovered = gallery.repository.import_item(source, item_id)
    assert recovered['state'] == 'REVIEW'
    assert recovered['work_order_number'] == ''
    assert recovered['work_order_candidates'] == ('02314464',)
    assert gallery.files.path('crops', item_id).read_bytes() == b'original-card'
    assert gallery.work_order_lookup_numbers() == ['02314464']

    # A candidate is not an accepted work order until the independent source
    # validates that exact number. No false Gallery publication.
    assert gallery.publish_work_order_records(['02314464'], [], 100)['enriched'] == 0
    assert gallery.item(item_id) is None
    assert gallery.publish_work_order_records(['02314464'],
                                              [_record('02314464')], 101)['enriched'] == 1
    assert gallery.item(item_id)['work_order_number'] == '02314464'


def test_saved_diagnostics_never_promote_phone_or_unlabeled_number(tmp_path):
    from printer_app.gallery.bootstrap import build
    from printer_app.gallery.recognition import saved_fallback_candidates

    reads = [{'label': 'Fallback whole card', 'psm': 6,
              'text': 'Phone: 02314464 Notes: 02314464', 'candidate': '', 'ok': True},
             {'label': 'Whole field', 'psm': 7, 'text': '02314464',
              'candidate': '', 'ok': True}]
    assert saved_fallback_candidates(reads) == ()
    gallery = build(tmp_path)
    gallery.initialize()
    source, item_id = 'a' * 64, 'b' * 64
    gallery.repository.enqueue(source, 'scan.pdf')
    gallery.repository.finish(source, [dict(
        id=item_id, import_id=source, page=1, part=1, filename='scan.pdf',
        text='Lead Name: Example Customer', origin='scan', work_order_candidates=(),
        work_order_reads=reads, mod_notes_status='present',
        document_date='2026-10-20', date_status='printed', bytes=1, created=1,
    )])
    assert gallery.recover_saved_fallback_candidates() == 0
    assert gallery.work_order_lookup_numbers() == []
