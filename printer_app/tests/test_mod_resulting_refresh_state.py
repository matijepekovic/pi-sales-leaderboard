"""Lossless MOD draft round trips: blank numbers, explicit zero, and Review."""
from copy import deepcopy
from dataclasses import asdict
from datetime import timezone
from io import BytesIO
import json

import pytest
from pypdf import PdfReader

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft, prices, outcome_fields
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.salesforce_drafts import project_salesforce_drafts


@pytest.mark.parametrize(('numbers', 'derived_prices'), [
    ('', {'highest': '', 'lowest': ''}),
    ('0', {'highest': '', 'lowest': ''}),
    ('99.99', {'highest': '', 'lowest': ''}),
    ('099', {'highest': '', 'lowest': ''}),
    ('25,000\n17,850', {'highest': '25000', 'lowest': '17850'}),
    ('2 visits\n25,000\n17,850\n99.99', {'highest': '25000', 'lowest': '17850'}),
])
def test_review_refresh_and_pdf_preserve_every_draft_field(tmp_path, numbers, derived_prices):
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
    assert prices(numbers) == derived_prices


def test_missing_review_in_an_existing_draft_does_not_reclassify_redlines():
    legacy = {'numbers': '', 'notes': 'Original comment', 'redlines': 'Original redline'}
    before = deepcopy(legacy)
    normalized = clean_draft(legacy)
    assert legacy == before
    assert normalized['review'] is False
    assert all(normalized[key] == value for key, value in legacy.items())


@pytest.mark.parametrize(('start', 'final'), [
    ('0', '0'), ('25', '0'), ('99.99', '25'), ('25000', '99.99'),
])
def test_explicit_source_prices_below_the_automatic_minimum_survive_projection(start, final):
    ident = '0WO000000000001AAA'
    source = {'Dispo__c': 'PNS', 'MOD_Notes__c': 'Original source note',
              'Start_Price__c': start, 'Price__c': final}
    projected = project_salesforce_drafts(
        timezone.utc, {ident: ''}, {ident: source}, {}, {},
    )[ident]
    draft = clean_draft(projected)
    assert outcome_fields(draft)['price'] == {'highest': start, 'lowest': final}
    assert draft['notes'] == 'Original source note'
    # Filtering automatic calculations must not delete the stored Numbers.
    assert start in draft['numbers'].splitlines()
    assert final in draft['numbers'].splitlines()
