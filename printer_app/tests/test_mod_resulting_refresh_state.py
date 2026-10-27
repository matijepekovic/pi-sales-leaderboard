"""Lossless MOD draft round trips: blank numbers, explicit zero, and Review."""
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
import json

import pytest
from pypdf import PdfReader

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft, prices
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.repository import ResultingRepository


@pytest.mark.parametrize('numbers', ['', '0', '25,000\n17,850'])
def test_review_refresh_and_pdf_preserve_every_draft_field(tmp_path, numbers):
    day = '2026-10-27'
    record = ModSheetRecord(source_id='0WO000000000001AAA',
                            lead_name='Example Customer', work_order_number='00012345',
                            product_interest='Roofing')
    repo = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    repo.refresh(day, [record])
    assert repo.sheets(day)[0]['draft'] == {}
    base = clean_draft({'dispo': 'cxl', 'numbers': numbers,
                        'notes': 'Black comment', 'redlines': 'Redline content',
                        'call_1': '10:15 AM', 'call_2': '1:27 PM', 'cxl_at_lead': True})
    original = deepcopy(base)
    revision = 0
    for checked in (True, False, True):
        expected = dict(base, review=checked)
        # Exercise the same JSON boundary as HTTP and SQLite, including blanks.
        submitted = clean_draft(json.loads(json.dumps(expected)))
        revision = repo.save_draft(day, record.source_id, submitted, revision)
        repo.refresh(day, [record])
        saved = repo.sheets(day)[0]
        assert saved['revision'] == revision
        assert saved['draft'] == expected
        before_pdf = deepcopy(saved)
        data = render_resulting_pdf([saved])
        assert saved == before_pdf
        assert repo.sheets(day)[0]['draft'] == expected
        assert base == original
        text = PdfReader(BytesIO(data)).pages[0].extract_text()
        for label in ('Review', 'Black comment', 'Redline content'):
            assert label in text
        assert saved['draft']['numbers'] == numbers
    assert clean_draft({})['numbers'] == ''
    if numbers == '':
        assert prices(numbers) == {'highest': '', 'lowest': ''}
    elif numbers == '0':
        assert prices(numbers) == {'highest': '0', 'lowest': '0'}


def test_missing_review_in_an_existing_draft_does_not_reclassify_redlines():
    legacy = {'numbers': '', 'notes': 'Original comment', 'redlines': 'Original redline'}
    before = deepcopy(legacy)
    normalized = clean_draft(legacy)
    assert legacy == before
    assert normalized['review'] is False
    assert all(normalized[key] == value for key, value in legacy.items())
