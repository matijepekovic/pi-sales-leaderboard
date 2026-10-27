"""Review is a checkbox; black comments and redlines remain MOD Notes."""
from dataclasses import asdict
from io import BytesIO
import json
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from printer_app.db import Database
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import clean_draft
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.salesforce_adapter import (
    ResultingSalesforceAdapter, ResultingSalesforceError,
)
from printer_app.mod_resulting.service import ResultingService


DAY = '2026-10-27'
WORK = '0WO000000000001AAA'
LEAD = '00Q000000000001AAA'
MOD = '005000000000001AAA'
APPOINTMENT = '08p000000000001AAA'
RECORD = ModSheetRecord(source_id=WORK, lead_source_id=LEAD,
                        lead_name='Example Customer', work_order_number='00012345',
                        product_interest='Roofing')


def _field(name, label, kind='string', **extra):
    return dict(name=name, label=label, type=kind, updateable=True,
                createable=True, **extra)


def _runner(review_type='boolean'):
    """Synthetic org metadata only. Exercise real preflight, never a live write."""
    schemas = {
        'ServiceAppointment': {'name': 'ServiceAppointment', 'fields': [
            _field('FSSK__FSK_Work_Order__c', 'Work Order', 'reference',
                   referenceTo=['WorkOrder']),
            _field('Status', 'Status', 'picklist', picklistValues=[
                {'value': 'Completed', 'active': True}]),
        ]},
        'WorkOrder': {'name': 'WorkOrder', 'fields': [
            _field('Status', 'Status', 'picklist', picklistValues=[
                {'value': 'Completed', 'active': True}]),
            _field('MOD__c', 'MOD', 'reference', referenceTo=['User']),
            _field('MOD_Notes__c', 'MOD Notes', 'textarea'),
        ]},
        'Lead': {'name': 'Lead', 'fields': [
            _field('Status', 'Status', 'picklist', picklistValues=[
                {'value': 'Nurturing', 'active': True}]),
            _field('Previous_Result__c', 'Previous Result', 'picklist', picklistValues=[
                {'value': 'Pitch No Sale', 'active': True}]),
        ]},
        'Product_Result__c': {'name': 'Product_Result__c', 'label': 'Product Result',
                             'fields': [
            _field('Work_Order__c', 'Work Order', 'reference', referenceTo=['WorkOrder']),
            _field('Product__c', 'Product Interest', 'picklist', picklistValues=[
                {'value': 'Roofing', 'active': True}]),
            _field('Result__c', 'Result', 'picklist', picklistValues=[
                {'value': 'Pitch No Sale', 'active': True}]),
            _field('Comment__c', 'Comment', 'textarea'),
        ]},
    }
    if review_type is not None:
        schemas['WorkOrder']['fields'].append(_field('Review__c', 'Review', review_type))

    def run(command, **kwargs):
        if command[1:3] == ['sobject', 'describe']:
            result = schemas[command[command.index('--sobject') + 1]]
        elif command[1:3] == ['sobject', 'list']:
            result = ['Product_Result__c']
        elif command[1:3] == ['data', 'query']:
            query = command[command.index('--query') + 1]
            if ' FROM ServiceAppointment ' in query:
                records = [{'Id': APPOINTMENT}]
            elif ' FROM WorkOrder ' in query:
                records = [{'Id': WORK, 'Lead__c': LEAD}]
            elif ' FROM Product_Result__c ' in query:
                records = []
            else:
                raise AssertionError(query)
            result = {'records': records, 'done': True}
        else:
            raise AssertionError('Unexpected operation; no writes permitted in this test.')
        return SimpleNamespace(stdout=json.dumps({'status': 0, 'result': result}),
                               stderr='', returncode=0)
    return run


def _payload(review=False, redlines='REDLINE: replace trim.'):
    sheet = {'day': DAY, 'work_order_id': WORK, 'snapshot': asdict(RECORD),
             'draft': clean_draft({'dispo': 'pns', 'review': review,
                                   'notes': 'Black customer comment.', 'redlines': redlines})}
    return ResultingService.submission_payload(sheet, MOD)


@pytest.mark.parametrize('review', [False, True])
@pytest.mark.parametrize('redlines', ['', 'REDLINE: replace trim.'])
def test_review_is_boolean_and_redlines_are_only_in_mod_notes(review, redlines):
    adapter = ResultingSalesforceAdapter(runner=_runner())
    plan = adapter.prepare([_payload(review, redlines)])[0]
    work_order = next(fields for action, obj, ident, fields in plan if obj == 'WorkOrder')
    product = next(fields for action, obj, ident, fields in plan if obj == 'Product_Result__c')
    assert work_order['Review__c'] is review
    expected = 'Black customer comment.' + ('\n' + redlines if redlines else '')
    assert work_order['MOD_Notes__c'] == expected
    assert product['Comment__c'] == 'Black customer comment.'
    assert all(not isinstance(value, str) or 'REDLINE:' not in value
               for key, value in work_order.items() if key != 'MOD_Notes__c')


@pytest.mark.parametrize('invalid', ['REDLINE', 'true', 1, None])
def test_review_never_accepts_redline_text_or_coerced_values(invalid):
    with pytest.raises(ValueError, match='review must be a checkbox'):
        clean_draft({'review': invalid})


def test_old_draft_defaults_review_to_unchecked_without_changing_notes():
    draft = clean_draft({'notes': 'Existing black note', 'redlines': 'Existing redline'})
    assert draft['review'] is False
    assert draft['notes'] == 'Existing black note'
    assert draft['redlines'] == 'Existing redline'


def test_review_save_uncheck_and_refresh_preserve_notes(tmp_path):
    repository = ResultingRepository(Database(tmp_path / 'printer.sqlite'))
    repository.refresh(DAY, [RECORD])
    old = clean_draft({'notes': 'Black comment', 'redlines': 'Redline'})
    revision = repository.save_draft(DAY, WORK, old, 0)
    for selected in (True, False):
        draft = clean_draft(dict(old, review=selected))
        revision = repository.save_draft(DAY, WORK, draft, revision)
        repository.refresh(DAY, [RECORD])
        stored = repository.sheets(DAY)[0]['draft']
        assert stored['review'] is selected
        assert stored['notes'] == old['notes']
        assert stored['redlines'] == old['redlines']


@pytest.mark.parametrize('kind', ['textarea', 'string', None])
def test_checked_review_requires_a_real_writable_checkbox(kind):
    adapter = ResultingSalesforceAdapter(runner=_runner(kind))
    with pytest.raises(ResultingSalesforceError, match='checkbox|not mapped'):
        adapter.prepare([_payload(True)])


@pytest.mark.parametrize('selected', [False, True])
def test_pdf_contains_review_checklist_and_keeps_redline_text(selected):
    draft = clean_draft({'review': selected, 'notes': 'Black comment',
                         'redlines': 'REDLINE: unchanged by Review.'})
    data = render_resulting_pdf([{'snapshot': asdict(RECORD), 'draft': draft}])
    pdf = PdfReader(BytesIO(data))
    assert len(pdf.pages) == 1
    text = pdf.pages[0].extract_text()
    for label in ('Docs', 'Bid Sheets', 'Promo', 'Review', 'Pictures'):
        assert label in text
    assert 'Black comment' in text
    assert 'REDLINE: unchanged by Review.' in text
