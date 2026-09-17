"""Focused regression coverage for OCR lead-name boundaries."""
import pytest

from printer_app.gallery.policy import printed_lead


@pytest.mark.parametrize('text,expected', [
    ('Lead Name: STEVE & CRYSTAL WYANT Address: 401 Brandywine Avenue, DuPont, WA, 98327',
     'STEVE & CRYSTAL WYANT'),
    ('Lead Name: Unit 7 / Smith + Jones #2 Address 55 Main St',
     'Unit 7 / Smith + Jones #2'),
    ("Lead Name: O'Neil & Sons (2nd) @ Home Address: 1 Example St",
     "O'Neil & Sons (2nd) @ Home"),
    ('Lead Name: ACME [North] #12 / A+B Address: Example St',
     'ACME [North] #12 / A+B'),
    ('Lead Name: 007 Address: Example St', '007'),
    ('Lead Name: M&J / Unit #5 - 24/7 | Phone: 5551234',
     'M&J / Unit #5 - 24/7'),
])
def test_printed_lead_accepts_numbers_symbols_and_stops_at_address(text, expected):
    assert printed_lead(text) == expected


def test_printed_lead_still_requires_an_explicit_non_garbage_value():
    assert printed_lead('Notes: STEVE & CRYSTAL WYANT Address: Example St') == ''
    assert printed_lead('Lead Name: ??? Address: Example St') == ''


def test_printed_lead_still_rejects_conflicting_headers():
    text = 'Lead Name: A&B #1\nLead Name: C/D #2'
    assert printed_lead(text) == ''
