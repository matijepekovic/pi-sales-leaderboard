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
