"""MOD financing-payment and DNR behavior, independent of live Salesforce writes."""
from dataclasses import asdict
from io import BytesIO

import pytest
from pypdf import PdfReader

from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import (
    clean_draft, final_redline_text, outcome_fields,
    sale_redlines, sold_products, individual_product_sales,
    deposit_payment_text, deposit_payment_value,
)
from printer_app.mod_resulting.pdf_export import render_resulting_pdf
from printer_app.mod_resulting.service import ResultingService


DAY = '2026-10-28'
WORK = '0WO000000000001AAA'
LEAD = '00Q000000000001AAA'
MOD = '005000000000001AAA'
RECORD = ModSheetRecord(
    source_id=WORK, lead_source_id=LEAD,
    lead_name='Example Customer',
    work_order_number='00012345',
    product_interest='Roofing;Siding',
)


def _payload(draft):
    return ResultingService.submission_payload({
        'day': DAY, 'work_order_id': WORK,
        'snapshot': asdict(RECORD), 'draft': clean_draft(draft),
    }, MOD)


def test_monthly_payment_is_optional_per_product_and_in_combined_deposit_payment():
    draft = clean_draft({
        'dispo': 'sale',
        'numbers': '25000\n17000',
        'sale_products': {
            'Roofing': {'price': '17000', 'deposit': '0', 'payment': '159.50'},
            'Windows': {'price': '22000', 'deposit': '5000', 'payment': ''},
            'Bath': {'price': '0', 'deposit': '250', 'payment': '100'},
        },
    })
    assert [item['product'] for item in sold_products(draft)] == ['Roofing', 'Windows']
    expected = (
        'SALE Roofing: $17,000 | Deposit: $0 | Payment: $159.50',
        'SALE Windows: $22,000 | Deposit: $5,000',
    )
    assert sale_redlines(draft) == expected
    assert final_redline_text(draft) == '\n'.join(expected)
    payload = _payload(draft)
    assert payload['deposit_payment'] == '5000/159.50'
    assert deposit_payment_text(draft) == '5000/159.50'
    assert payload['fields']['price'] == {'highest': '25000', 'lowest': '17000'}
    assert [item['product'] for item in payload['product_results']] == [
        'Roofing', 'Windows'
    ]
    assert payload['product_results'][0]['price'] == '17000'
    assert payload['product_results'][1]['price'] == '22000'
    assert payload['final_redlines'] == '\n'.join(expected)


def test_independent_product_sale_payment_never_changes_main_disposition():
    draft = clean_draft({
        'dispo': 'pns', 'additional_products': True,
        'product_results': {
            'Roofing': {
                'result': 'sale', 'detail': '',
                'price': '14500', 'deposit': '500', 'payment': '138',
            },
        },
    })
    assert individual_product_sales(draft) == ({
        'product': 'Roofing', 'price': '14500',
        'deposit': '500', 'payment': '138',
    },)
    payload = _payload(draft)
    assert payload['dispo'] == 'pns'
    assert payload['fields']['lead_status'] == 'Nurturing'
    assert payload['deposit_payment'] == '500/138'
    assert deposit_payment_text(draft) == '500/138'
    assert payload['product_results'][0]['result'] == 'sale'
    assert payload['product_results'][0]['price'] == '14500'
    assert 'Payment: $138' in payload['final_redlines']


def test_old_sale_drafts_without_payment_remain_compatible():
    original = {
        'Roofing': {'price': '17000', 'deposit': '0'},
    }
    draft = clean_draft({'dispo': 'sale', 'sale_products': original})
    assert draft['sale_products'] == original
    assert sale_redlines(draft) == ('SALE Roofing: $17,000 | Deposit: $0',)
    assert _payload(draft)['deposit_payment'] == '0/'
    assert deposit_payment_text(draft) == '0/'


def test_combined_display_uses_actual_sales_and_manual_whole_field_override():
    draft = clean_draft({'dispo': 'sale', 'sale_products': {
        'Roofing': {'price': '17000', 'deposit': '0'},
        'Windows': {'price': '25000', 'deposit': '300', 'payment': '120.50'},
        'Siding': {'price': '18500', 'deposit': '200', 'payment': '80'},
        'Bath': {'price': '0', 'deposit': '999', 'payment': '900'},
    }})
    assert deposit_payment_text(draft) == '500/200.50'
    overridden = clean_draft(dict(draft, deposit_override='750'))
    assert deposit_payment_text(overridden) == '750'
    assert _payload(overridden)['deposit_payment'] == '750'
    with_slash = clean_draft(dict(draft, deposit_override='750/188.50'))
    assert deposit_payment_text(with_slash) == '750/188.50'
    assert _payload(with_slash)['deposit_payment'] == '750/188.50'
    assert deposit_payment_text(clean_draft({'deposit_override': '2500'})) == '2500'
    assert deposit_payment_text(clean_draft({'dispo': 'sale'})) == ''


@pytest.mark.parametrize('value', ['500/159', '500/159.50', '0/159.50', '500/', '2500', '1,000/100'])
def test_manual_deposit_payment_roundtrips_without_rounding(value):
    normalized = clean_draft({'deposit_override': value})['deposit_override']
    assert deposit_payment_value(normalized) == value.replace(',', '')
    assert deposit_payment_text(clean_draft({'deposit_override':value})) == normalized


@pytest.mark.parametrize('invalid', ['100//20', '/159', '$500/159', '100/abc', '100/-20', '100/159.123'])
def test_manual_deposit_payment_rejects_unsafe_values(invalid):
    with pytest.raises(ValueError):
        clean_draft({'deposit_override':invalid})


@pytest.mark.parametrize('payment', ['not a price', '-20', '12.345', '1,0,0'])
def test_payment_rejects_unsafe_money_values(payment):
    with pytest.raises(ValueError, match='Money values'):
        clean_draft({'sale_products': {
            'Roofing': {'price': '17000', 'deposit': '0', 'payment': payment},
        }})


@pytest.mark.parametrize('dispo,expected', [
    ('sale', 'Sale Pending'),
    ('pns', 'Nurturing'),
    ('np', 'Nurturing'),
    ('cxl', 'Canceled'),
    ('nra', 'Nurturing'),
    ('oos', 'Out of Scope'),
])
def test_dnr_without_reasons_is_unchecked_and_preserves_main_dispo(dispo, expected):
    draft = clean_draft({'dispo': dispo, 'dnr': True, 'dnr_reason': ''})
    assert draft['dispo'] == dispo
    assert draft['dnr'] is False
    assert draft['dnr_reason'] == ''
    assert outcome_fields(draft)['lead_status'] == expected
    selected = clean_draft({
        'dispo': dispo, 'dnr': True, 'dnr_reason': 'Roofing;Bath',
    })
    assert outcome_fields(selected)['lead_status'] == 'Do Not Call'
    assert selected['dispo'] == dispo


def test_payment_printed_in_red_generated_notes_without_recoloring_old_notes():
    draft = clean_draft({
        'dispo': 'sale',
        'notes': 'Customer asked for scope details',
        'note_runs': [{'text': 'Customer asked for scope details', 'red': False}],
        'sale_products': {
            'Roofing': {'price': '17000', 'deposit': '0', 'payment': '159.50'},
        },
    })
    pdf = PdfReader(BytesIO(render_resulting_pdf([{
        'snapshot': asdict(RECORD), 'draft': draft,
    }])))
    text = pdf.pages[0].extract_text()
    assert 'Customer asked for scope details' in text
    assert 'SALE Roofing:' in text
    assert 'Deposit: $0' in text
    assert 'Payment: $159.50' in text.replace('\n', ' ')
    assert '0/159.50' in text.replace('\n', ' ')
