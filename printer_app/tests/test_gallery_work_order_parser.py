"""Work order OCR must preserve the fixed-length identifier and token boundaries."""
import pytest

from printer_app.gallery.policy import printed_work_order_number, work_order_key


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
])
def test_reads_a_complete_eight_digit_token_without_joining_ocr_noise(text, expected):
    assert printed_work_order_number(text) == expected


@pytest.mark.parametrize('value', [
    '', '1', '2278850', '022788501', '102278850', '0227885012345678',
    '0227 8850', '022 788 50', '0227-8850', '0227/8850',
    'WO02278850', '02278850A', 'A02278850B',
    '０２２７８８５０', '٠٢٢٧٨٨٥٠', '0227885０',
    'é02278850', '02278850é', '٢02278850', '02278850٢',
    'A\u030102278850', '02278850\u0301', '02278850\u200dA',
])
def test_does_not_invent_a_number_from_fragments_long_tokens_or_unicode(value):
    assert printed_work_order_number('Work Order Number: ' + value) == ''


@pytest.mark.parametrize('text', [
    'Work Order Number: 02278850 02278851',
    'Work Order Number: 02278850\nWork Order Number: 02278851',
    'Work Order Number: 02278850 Work Order Number: 02278851',
    'Work Order Number: 02278850\nWork Order Number:',
    'Work Order Number:\nWork Order Number: 02278850',
    'Work Order Number: 02278850\nWork Order Number: 022788501',
    'Work Order Number: 0227 8850\nWork Order Number: 02278850',
])
def test_conflicting_or_unreadable_repeated_fields_do_not_choose_one(text):
    assert printed_work_order_number(text) == ''


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
