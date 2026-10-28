"""Review is a local checklist checkbox. It must never become a Salesforce write."""
from dataclasses import asdict
from io import BytesIO

import pytest
from pypdf import PdfReader

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft, final_redline_text
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.repository import ResultingRepository


DAY = '2026-10-27'
WORK = '0WO000000000001AAA'
RECORD = ModSheetRecord(
    source_id=WORK,lead_name='Example Customer',
    work_order_number='00012345',product_interest='Roofing',
)


@pytest.mark.parametrize('invalid',['REDLINE','true',1,None])
def test_review_never_accepts_non_boolean_values(invalid):
    with pytest.raises(ValueError,match='review must be a checkbox'):
        clean_draft({'review':invalid})


def test_old_draft_defaults_review_unchecked_without_touching_notes():
    before={'notes':'Original black note','redlines':'Original redline'}
    draft=clean_draft(before)
    assert before=={'notes':'Original black note','redlines':'Original redline'}
    assert draft['review'] is False
    assert draft['notes']==before['notes']
    assert draft['redlines']==before['redlines']


@pytest.mark.parametrize('review,redlines',[
    (False,''),(True,''),(False,'REDLINE: trim'),(True,'REDLINE: trim'),
])
def test_review_checkbox_changes_neither_notes_nor_generated_redlines(review,redlines):
    draft=clean_draft({
        'review':review,'dispo':'pns','notes':'Black note',
        'redlines':redlines,
    })
    assert draft['notes']=='Black note'
    assert draft['redlines']==redlines
    assert final_redline_text(draft)==redlines


def test_review_check_uncheck_and_refresh_preserve_mod_notes(tmp_path):
    repo=ResultingRepository(Database(tmp_path/'printer.sqlite'))
    repo.refresh(DAY,[RECORD])
    original=clean_draft({'notes':'Black comment','redlines':'Redline'})
    revision=repo.save_draft(DAY,WORK,original,0)
    for selected in (True,False,True):
        draft=clean_draft(dict(original,review=selected))
        revision=repo.save_draft(DAY,WORK,draft,revision)
        repo.refresh(DAY,[RECORD])
        saved=repo.sheets(DAY)[0]['draft']
        assert saved['review'] is selected
        assert saved['notes']==original['notes']
        assert saved['redlines']==original['redlines']


@pytest.mark.parametrize('selected',[False,True])
def test_review_is_displayed_in_existing_pdf_checklist(selected):
    draft=clean_draft({
        'review':selected,'notes':'Black note',
        'redlines':'REDLINE: unchanged by Review.',
    })
    payload=render_resulting_pdf([{'snapshot':asdict(RECORD),'draft':draft}])
    text=PdfReader(BytesIO(payload)).pages[0].extract_text()
    for label in ('Docs','Bid Sheets','Promo','Review','Pictures'):
        assert label in text
    assert 'Black note' in text
    assert 'REDLINE: unchanged by Review.' in text
