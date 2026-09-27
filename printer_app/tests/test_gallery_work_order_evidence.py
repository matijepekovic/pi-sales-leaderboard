"""Exact corroboration among independently read, source-confirmed work orders."""
import pytest

from printer_app.gallery.policy import (
    normalize_work_order_evidence, select_work_order_candidate, work_order_schedule,
)


def reference(number, name='Shared Name', day='2026-05-15', clock='17:30', phone=''):
    return number, dict(
        work_order_number=number, lead_name=name, appointment_date=day,
        local_scheduled_start_time=f'{day}T{clock}', phone=phone,
    )


def test_evidence_normalization_preserves_all_distinct_literal_observations():
    evidence = normalize_work_order_evidence(dict(
        names=['  JORDAN   EXAMPLE ', 'Jordan Example', 'JORDANEXAMPLE', 'Straße', 'STRASSE',
               'Rene\u0301e Example', 'Renée Example', 'Renee Example'],
        dates=['2026-05-15', '2026-05-16', '2026-05-15', '2026-02-30', '5/15/2026'],
        times=['17:30', '17:30', '17:31', '5:30 PM', '24:00'],
        phones=['(360) 555-1200', '3605551200', '3605551201', '123', '3605551200 ext 1'],
        address=['irrelevant'],
    ))
    assert evidence == dict(
        names=('jordan example', 'jordanexample', 'strasse', 'renée example', 'renee example'),
        dates=('2026-05-15', '2026-05-16'), times=('17:30', '17:31'),
        phones=('3605551200', '3605551201'),
    )
    assert normalize_work_order_evidence(evidence) == evidence


@pytest.mark.parametrize('value', [None, 'name', [], 17, {'names': 'name', 'phones': [None, 3605551200]}])
def test_malformed_evidence_is_not_interpreted_as_observed_fields(value):
    assert normalize_work_order_evidence(value) == dict(names=(), dates=(), times=(), phones=())


@pytest.mark.parametrize(('raw', 'expected'), [
    ('5/15/2026 5:30 PM', ('2026-05-15', '17:30')),
    ('2026.05.15 ; 05:30:00 PM', ('2026-05-15', '17:30')),
    ('May 15 2026 05:30 PM', ('2026-05-15', '17:30')),
    ('Sep 11, 2026 03:00PM', ('2026-09-11', '15:00')),
    ('September 11 2026 12:00 AM', ('2026-09-11', '00:00')),
    ('2026-09-11T12:00', ('2026-09-11', '12:00')),
    ('12:00 PM', ('', '12:00')),
    ('00:00', ('', '00:00')),
    ('2026-05-15', ('2026-05-15', '')),
    ('May 15 2026', ('2026-05-15', '')),
])
def test_schedule_accepts_explicit_printed_formats(raw, expected):
    assert work_order_schedule(raw) == expected


@pytest.mark.parametrize('raw', [
    'May 15 2026 05 30 PM', 'May 15 2026 05:30',
    'May 15 2026 13:30 PM', '2/30/2026 5:30 PM', 'May 15 2026 5:60 PM',
    '2026-05-15T24:00', '2026-05-15T17:30Z', '2026-05-15T17:30:01',
    'May 15 2026 5:30 PM or 6:00 PM', 'Call on May 15 2026 5:30 PM',
    'May 15 2026 05:3O PM', '5/15/26 5:30 PM', None, 1730,
])
def test_schedule_does_not_guess_or_silently_discard_clock_information(raw):
    assert work_order_schedule(raw) == ('', '')


def test_changed_current_name_does_not_prevent_unique_exact_phone_match():
    correct = reference('02000001', 'Casey Current', phone='360-555-1200')
    other = reference('02000002', 'Morgan Example', phone='3605551202')
    assert select_work_order_candidate([other, correct], dict(
        names=('Casey Original',), dates=('2026-05-15',), phones=('(360) 555-1200',),
    )) is correct


def test_common_date_is_neutral_and_unique_literal_name_selects_correct_customer():
    correct = reference('02000001', 'JORDAN EXAMPLE')
    other = reference('02000002', 'AVERY & ROBIN EXAMPLE')
    assert select_work_order_candidate([correct, other], dict(
        names=('JORDANEXAMPLE', 'Jordan Example'), dates=('2026-05-15',),
    )) is correct
    assert select_work_order_candidate([correct, other], {'dates': ['2026-05-15']}) is None


def test_same_current_name_on_both_candidates_does_not_block_unique_phone():
    correct = reference('02000001', phone='3605551203')
    other = reference('02000002', phone='3605551204')
    assert select_work_order_candidate([correct, other], dict(
        names=('SHARED NAME', 'Unreadable Name'), phones=('3605551203',),
    )) is correct


def test_exact_unique_date_is_allowed_without_name_or_phone():
    correct = reference('02000001', day='2026-05-15')
    other = reference('02000002', day='2026-05-16')
    assert select_work_order_candidate([correct, other], {'dates': ['2026-05-15']}) is correct


def test_time_corroborates_only_an_exact_date_and_time_pair():
    correct = reference('02000001', clock='17:30')
    other = reference('02000002', clock='18:00')
    assert select_work_order_candidate([correct, other], {'times': ['17:30']}) is None
    assert select_work_order_candidate([correct, other], dict(
        dates=('2026-05-15',), times=('17:30',),
    )) is correct
    assert select_work_order_candidate([correct, other], dict(
        dates=('2026-05-15', '2026-05-16'), times=('17:30',),
    )) is None


@pytest.mark.parametrize('evidence', [
    dict(names=('First Customer',), phones=('3605551204',)),
    dict(names=('First Customer', 'Second Customer')),
    dict(phones=('3605551203', '3605551204')),
    dict(names=('First Customer',), dates=('2026-05-15',), times=('18:00',)),
    dict(names=('First Customer', 'First Customer'), phones=('3605551203', '3605551204')),
])
def test_conflicting_positive_fields_or_alternative_reads_never_use_majority_vote(evidence):
    first = reference('02000001', 'First Customer', clock='17:30', phone='3605551203')
    second = reference('02000002', 'Second Customer', clock='18:00', phone='3605551204')
    assert select_work_order_candidate([first, second], evidence) is None
    assert select_work_order_candidate([second, first], evidence) is None


@pytest.mark.parametrize('evidence', [
    {}, None, dict(names=('Alex Example',)), dict(names=('Renee Example',)),
    dict(phones=('3605551205',)), dict(names=('ALEX & SAM EXAMPLE',)),
])
def test_no_evidence_or_fuzzy_similarity_cannot_choose(evidence):
    first = reference('02000001', 'ALEX + SAM EXAMPLE', phone='3605551203')
    second = reference('02000002', 'Renée Example')
    assert select_work_order_candidate([first, second], evidence) is None


def test_source_local_field_owns_schedule_even_when_other_display_differs():
    first = reference('02000001', clock='17:30')
    first[1]['scheduled_start'] = '2026.05.15 ; 06:00:00 PM'
    second = reference('02000002', clock='18:00')
    evidence = dict(dates=('2026-05-15',), times=('18:00',))
    assert select_work_order_candidate([first, second], evidence) is second


def test_scheduled_start_fallback_is_only_used_when_local_field_is_absent():
    first = reference('02000001', clock='17:30')
    first[1].update(local_scheduled_start_time='', scheduled_start='2026.05.15 ; 05:30:00 PM')
    second = reference('02000002', clock='18:00')
    evidence = dict(dates=('2026-05-15',), times=('17:30',))
    assert select_work_order_candidate([first, second], evidence) is first
    first[1]['local_scheduled_start_time'] = 'Unreadable'
    assert select_work_order_candidate([first, second], evidence) is None


def test_source_local_date_takes_precedence_over_different_display_date():
    first = reference('02000001', day='2026-05-15')
    first[1]['appointment_date'] = '2026-05-16'
    second = reference('02000002', day='2026-05-16')
    assert select_work_order_candidate([first, second], {'dates': ['2026-05-15']}) is first


def test_single_complete_source_match_keeps_existing_number_contract():
    only = reference('00000001')
    assert select_work_order_candidate([only], {}) is only
    assert select_work_order_candidate([], {}) is None


def test_identical_duplicates_cannot_create_or_hide_competing_candidates():
    first = reference('02000001', 'First Customer')
    other = reference('02000002', 'Second Customer')
    assert select_work_order_candidate([first, first, other], {'names': ['First Customer']}) is first
    conflicting = reference('02000001', 'Different Customer')
    assert select_work_order_candidate([first, conflicting], {'names': ['First Customer']}) is None


def test_selection_cannot_validate_a_different_work_order_returned_by_source():
    source = reference('02000001', 'First Customer')
    assert select_work_order_candidate([('02000002', source[1])], {'names': ['First Customer']}) is None
