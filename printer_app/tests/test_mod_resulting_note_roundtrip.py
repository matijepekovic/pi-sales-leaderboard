"""Numbers occur once while source notes stay lossless through resulting."""
from datetime import timezone

import pytest

from printer_app.mod_resulting.contract import clean_draft, mod_note_text
from printer_app.mod_resulting.salesforce_drafts import project_salesforce_drafts
from printer_app.tests.test_mod_resulting_salesforce_mapping import (
    WORK, LEAD, _adapter, _operations, _payload, _single,
)


def _project(notes, *, prices=True, dnr=False, price_values=(25000, 17000)):
    work = {'Dispo__c': 'PNS', 'MOD_Notes__c': notes}
    if prices:
        work.update(Start_Price__c=price_values[0], Price__c=price_values[1])
    lead = {'DNR_Do_Not_Reset__c': dnr, 'DNR_Reason__c': 'Roofing' if dnr else ''}
    products = [{
        'Product_Interest__c': 'Roofing', 'Result__c': 'Pitch No Sale',
        'Result_Detail__c': 'Price Objection',
    }]
    return project_salesforce_drafts(
        timezone.utc, {WORK: LEAD}, {WORK: work}, {LEAD: lead}, {WORK: products},
    )[WORK]


@pytest.mark.parametrize('notes', [
    'Called<br><br>Customer answered',
    '<p>One &amp; two</p><div>Price &lt; 500</div>',
    'Offer < 500 and payment > 100',
    'Unknown <roof> note',
    'Price Objection',
    'Customer discussed\nPrice Objection',
])
def test_unproven_source_text_and_literal_markup_remain_lossless(notes):
    assert _project(notes)['notes'] == notes


@pytest.mark.parametrize('copies', [1, 2, 3])
def test_matching_source_numeric_prefix_is_represented_once(copies):
    note = 'Customer requested a call back.'
    numbers = '25000\n17000'
    recovered = _project((numbers + '\n') * copies + note)
    assert recovered['notes'] == note
    assert recovered['numbers'] == numbers
    assert recovered['redlines'] == ''


@pytest.mark.parametrize('notes', [
    '25000\nCustomer note',
    '25000\n18000\nCustomer note',
    'Other numbers 25000 / 17000\nCustomer note\nPrice Objection',
    'Estimate 25000\nOffer 17000\nCustomer note',
])
def test_partial_or_different_numeric_prefix_is_not_guessed_away(notes):
    assert _project(notes)['notes'] == notes


def test_numeric_prefix_never_removes_trailing_result_or_dnr_looking_user_text():
    note = 'Customer note\nPrice Objection\nDNR - Roofing'
    recovered = _project('25000\n17000\n' + note, dnr=True)
    assert recovered['notes'] == note
    assert recovered['numbers'] == '25000\n17000'


def test_separating_numeric_prefix_preserves_note_whitespace_and_line_endings():
    note = 'Customer note\r\n\r\n  Price Objection  \r\n'
    assert _project('25000\r\n17000\r\n' + note)['notes'] == note


def test_numeric_values_match_original_money_formatting_without_touching_note_numbers():
    remote = '$25,000\n17,000.00\nCustomer has 25000 saved.\nPrice Objection'
    recovered = _project(remote)
    assert recovered['notes'] == 'Customer has 25000 saved.\nPrice Objection'
    assert recovered['numbers'] == '25000\n17000'


def test_without_source_prices_a_numeric_or_result_prefix_remains_a_mod_note():
    note = '25000\n17000\nCustomer requested a call back.\nPrice Objection'
    assert _project(note, prices=False)['notes'] == note


def test_single_number_roundtrip_does_not_duplicate_equal_source_start_and_final_prices():
    remote = '100\nCustomer note'
    for _ in range(3):
        restored = clean_draft(_project(remote, price_values=(100, 100)))
        assert restored['numbers'] == '100'
        assert restored['notes'] == 'Customer note'
        adapter, _ = _adapter()
        plan = _operations(adapter, _payload(interest='Roofing', **{
            key: value for key, value in restored.items() if key != 'dispo'
        }))
        work_values = _single(plan, 'WorkOrder')[3]
        assert work_values['Start_Price__c'] == work_values['Price__c'] == '100'
        assert work_values['MOD_Notes__c'] == '100\nCustomer note'
        remote = work_values['MOD_Notes__c']


@pytest.mark.parametrize('note', [
    'Customer requested a call back.',
    'Customer requested a call back.\nPrice Objection',
    'Called<br><br>Customer answered',
])
def test_current_write_project_write_roundtrip_keeps_numbers_once_and_real_notes_intact(note):
    # The first write is a local draft with its explicit Numbers column.
    original = clean_draft({'notes': note, 'numbers': '25000\n17000', 'dispo': 'pns'})
    adapter, _ = _adapter()
    initial = _operations(adapter, _payload(interest='Roofing', **{
        key: value for key, value in original.items() if key != 'dispo'
    }))
    remote = _single(initial, 'WorkOrder')[3]['MOD_Notes__c']
    for _ in range(3):
        restored = clean_draft(_project(remote, dnr=True))
        adapter, calls = _adapter()
        plan = _operations(adapter, _payload(interest='Roofing', **{
            key: value for key, value in restored.items() if key != 'dispo'
        }))
        work_values = _single(plan, 'WorkOrder')[3]
        assert work_values['MOD_Notes__c'] == '25000\n17000\n' + note
        assert work_values['MOD_Notes__c'].count('25000') == 1
        assert work_values['MOD_Notes__c'].count('17000') == 1
        assert 'DNR - Roofing' not in work_values['MOD_Notes__c']
        assert all(command[1:3] in (['sobject', 'describe'], ['data', 'query'])
                   for command in calls)
        remote = work_values['MOD_Notes__c']


@pytest.mark.parametrize(('numbers', 'overrides'), [
    ('Start 25000\nFinal 17000', {}),
    ('25000\n21000\n17000', {}),
    ('$25,000\n17,000.00', {}),
    ('200', {'start_price_override': '100'}),
])
def test_source_provenance_preserves_full_numeric_column_serialization(numbers, overrides):
    note = 'Customer requested a call back.\nPrice Objection'
    draft = clean_draft(dict(numbers=numbers, notes=note, dispo='pns', **overrides))
    adapter, _ = _adapter()
    plan = _operations(adapter, _payload(interest='Roofing', **{
        key: value for key, value in draft.items() if key != 'dispo'
    }))
    source = _single(plan, 'WorkOrder')[3]
    expected = numbers + '\n' + note
    for _ in range(3):
        restored = clean_draft(_project(
            source['MOD_Notes__c'],
            price_values=(source['Start_Price__c'], source['Price__c']),
        ))
        assert mod_note_text(restored) == expected
        adapter, _ = _adapter()
        plan = _operations(adapter, _payload(interest='Roofing', **{
            key: value for key, value in restored.items() if key != 'dispo'
        }))
        source = _single(plan, 'WorkOrder')[3]
        assert source['MOD_Notes__c'] == expected


def test_notes_only_edit_does_not_prepend_reconstructed_source_prices():
    restored = clean_draft(_project('Existing source note'))
    assert restored['numbers'] == '25000\n17000'
    assert restored['note_origin'] == {'numbers': '25000\n17000', 'prefix': ''}
    restored['notes'] = 'Edited source note\nPrice Objection'
    assert mod_note_text(restored) == restored['notes']


def test_deliberate_numbers_edit_uses_entered_values_without_deleting_ambiguous_source_note():
    restored = clean_draft(_project('Start 25000\nFinal 17000\nCustomer note'))
    restored['numbers'] = '999\n888'
    assert mod_note_text(restored) == '999\n888\nStart 25000\nFinal 17000\nCustomer note'


def test_source_numeric_spelling_survives_an_unchanged_or_notes_only_write():
    source = '$25,000\n17,000.00\nCustomer note'
    restored = clean_draft(_project(source))
    assert restored['note_origin'] == {
        'numbers': '25000\n17000', 'prefix': '$25,000\n17,000.00',
    }
    assert mod_note_text(restored) == source
    restored['notes'] = 'Edited customer note'
    assert mod_note_text(restored) == '$25,000\n17,000.00\nEdited customer note'


def test_manual_source_prices_are_not_reversed_by_reconstructed_numbers():
    restored = clean_draft(_project('200\nCustomer note', price_values=(100, 200)))
    assert restored['start_price_override'] == '100'
    assert restored['final_price_override'] == '200'
    adapter, _ = _adapter()
    plan = _operations(adapter, _payload(interest='Roofing', **{
        key: value for key, value in restored.items() if key != 'dispo'
    }))
    work = _single(plan, 'WorkOrder')[3]
    assert work['Start_Price__c'] == '100'
    assert work['Price__c'] == '200'
    assert work['MOD_Notes__c'] == '200\nCustomer note'


def test_ordinary_source_prices_do_not_pin_new_numbers_edits_with_overrides():
    restored = clean_draft(_project('25000\n17000\nCustomer note'))
    assert restored['start_price_override'] == restored['final_price_override'] == ''
    restored['numbers'] = '30000\n15000'
    adapter, _ = _adapter()
    plan = _operations(adapter, _payload(interest='Roofing', **{
        key: value for key, value in restored.items() if key != 'dispo'
    }))
    work = _single(plan, 'WorkOrder')[3]
    assert work['Start_Price__c'] == '30000'
    assert work['Price__c'] == '15000'
    assert work['MOD_Notes__c'] == '30000\n15000\nCustomer note'


def test_unsupported_source_values_and_long_plain_notes_remain_lossless():
    notes = 'Existing source ' + 'x' * 9200
    draft = project_salesforce_drafts(
        timezone.utc, {WORK: ''},
        {WORK: {'Dispo__c': 'Custom source disposition', 'MOD_Notes__c': notes}},
        {}, {},
    )[WORK]
    assert draft['notes'] == notes
    assert draft['dispo'] == 'Custom source disposition'
