"""Normalized reference details replace searchable fields without another OCR pass."""
import pytest

from printer_app.gallery.policy import authoritative_reference_text


DETAILS = {
    'work_order_number': ('Work Order Number', 'WO-12345'),
    'appointment_date': ('Appointment Date', '2026-09-21'),
    'local_scheduled_start_time': ('Local Scheduled Start Time', '2026-09-21 10:30 AM'),
    'canvass_set_by': ('Canvass Set By', 'Canvasser Example'),
    'lead_name': ('Lead Name', 'Customer Example'),
    'address': ('Address', '123 Main Street, Example City'),
    'phone': ('Phone', '555-010-2345'),
    'scheduled_start': ('Scheduled Start', '2026-09-21 17:30 UTC'),
    'assigned_resource': ('Assigned Service Resource', 'Rep One, Rep Two, Rep Three'),
    'set_by': ('Set By', 'Setter Example'),
    'work_type': ('Work Type', 'Consultation'),
    'product_interest': ('Product Interest', 'Windows and Siding'),
    'source': ('Source', 'Referral'),
    'sub_source': ('Sub Source', 'Customer Event'),
    'lead_description': ('Lead Description', 'Replace seven upstairs windows'),
}


def test_every_available_normalized_detail_is_appended_and_idempotent():
    values = {key: value for key, (_, value) in DETAILS.items()}

    text = authoritative_reference_text('', **values)

    assert set(text.splitlines()) == {label + ': ' + value for label, value in DETAILS.values()}
    assert authoritative_reference_text(text, **values) == text


@pytest.mark.parametrize('separator', ['\n', ' | ', ' '])
def test_existing_details_are_replaced_without_clobbering_adjacent_fields(separator):
    original = separator.join(label + ': stale-' + key for key, (label, _) in DETAILS.items())
    original += separator + 'MOD Notes: KEEP THE ORIGINAL HANDWRITING'

    text = authoritative_reference_text(original, **{key: value for key, (_, value) in DETAILS.items()})

    assert text == separator.join(label + ': ' + value for label, value in DETAILS.values()) \
        + separator + 'MOD Notes: KEEP THE ORIGINAL HANDWRITING'
    assert 'stale-' not in text


@pytest.mark.parametrize('field,values,expected', [
    ('source', {'source': 'New Parent'},
     'Source: New Parent\nSub Source: Old Child\nSet By: Old Setter\nCanvass Set By: Old Canvasser'),
    ('set_by', {'set_by': 'New Setter'},
     'Source: Old Parent\nSub Source: Old Child\nSet By: New Setter\nCanvass Set By: Old Canvasser'),
    ('sub_source', {'sub_source': 'New Child'},
     'Source: Old Parent\nSub Source: New Child\nSet By: Old Setter\nCanvass Set By: Old Canvasser'),
    ('canvass_set_by', {'canvass_set_by': 'New Canvasser'},
     'Source: Old Parent\nSub Source: Old Child\nSet By: Old Setter\nCanvass Set By: New Canvasser'),
])
def test_short_label_names_cannot_match_inside_longer_labels(field, values, expected):
    original = ('Source: Old Parent\nSub Source: Old Child\n'
                'Set By: Old Setter\nCanvass Set By: Old Canvasser')

    assert authoritative_reference_text(original, **values) == expected


def test_wrapped_colonless_legacy_fields_are_replaced_and_following_labels_remain():
    original = ('Phone 555-oldnumber\nProduct Interest Old windows\nand doors\n'
                'Work Type Old appointment\nSource Old campaign\nSub Source Old event\n'
                'Canvass Set By Old canvasser\nSet By Old setter\n'
                'Lead Description Old first line\nold continuation\n'
                'Scheduled Start 9/21/2026 10:30 AM\nMOD Notes KEEP NOTES')

    text = authoritative_reference_text(
        original, phone='555-0100', product_interest='Windows', work_type='Consultation',
        source='Referral', sub_source='Customer Event', canvass_set_by='New Canvasser',
        set_by='New Setter', lead_description='New complete description',
    )

    assert text == ('Phone: 555-0100\nProduct Interest: Windows\nWork Type: Consultation\n'
                    'Source: Referral\nSub Source: Customer Event\n'
                    'Canvass Set By: New Canvasser\nSet By: New Setter\n'
                    'Lead Description: New complete description\n'
                    'Scheduled Start 9/21/2026 10:30 AM\nMOD Notes KEEP NOTES')


def test_blank_source_details_leave_existing_fields_and_punctuation_unchanged():
    original = '\nLead Name: Known Customer | Phone 555-0100\nLead Description: Keep this\n'
    blanks = {key: ' \t\n ' for key in DETAILS}

    assert authoritative_reference_text(original, **blanks) == original


def test_field_words_inside_values_are_not_treated_as_colonless_labels():
    original = ('Address: 123 Sourcebook Street\n'
                'Lead Description: Need Phone consultation with Source partner\n'
                'Scheduled Start: 9/21/2026 10:30 AM')

    text = authoritative_reference_text(
        original, address='456 Rightstreet', lead_description='Correct complete description',
    )

    assert text == ('Address: 456 Rightstreet\n'
                    'Lead Description: Correct complete description\n'
                    'Scheduled Start: 9/21/2026 10:30 AM')


def test_original_three_argument_contract_stays_compatible():
    original = 'Lead Name: Wrong\nAddress: Wrong Road\nAssigned Service Resource: Old Rep'

    assert authoritative_reference_text(original, 'Right Name', 'Right Road', 'New Rep') == (
        'Lead Name: Right Name\nAddress: Right Road\nAssigned Service Resource: New Rep'
    )


def test_reference_values_are_literal_text_and_whitespace_is_normalized():
    text = authoritative_reference_text('', lead_description='  Literal \\1 text\nwith another line  ')

    assert text == 'Lead Description: Literal \\1 text with another line'
