"""MOD financing-payment and DNR behavior, independent of live Salesforce writes."""
from dataclasses import asdict
from io import BytesIO

import pytest
from pypdf import PdfReader

from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.mod_resulting.contract import (
    clean_draft, final_redline_text, outcome_fields,
    sale_redlines, sold_products, individual_product_sales,
    sale_amount_totals, deposit_payment_text,
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


def test_monthly_payment_is_optional_per_product_and_never_part_of_deposit_total():
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
    assert sale_amount_totals(draft) == {'deposit': '5000', 'payment': '159.5'}
    assert deposit_payment_text(draft) == '5000/159.5'
    assert payload['deposit_total'] == '5000'
    assert payload['fields']['price'] == {'highest': '25000', 'lowest': '17000'}
    assert [item['product'] for item in payload['product_results']] == [
        'Roofing', 'Windows'
    ]
    assert payload['product_results'][0]['price'] == '17000'
    assert payload['product_results'][1]['price'] == '22000'
    assert payload['final_redlines'] == '\n'.join(expected)


def test_deposit_payment_override_changes_only_deposit_side():
    draft = clean_draft({
        'dispo': 'sale',
        'deposit_override': '2500',
        'sale_products': {
            'Roofing': {'price': '17000', 'deposit': '500', 'payment': '159.50'},
            'Windows': {'price': '22000', 'deposit': '1000', 'payment': '140.50'},
        },
    })
    assert sale_amount_totals(draft) == {'deposit': '1500', 'payment': '300'}
    assert deposit_payment_text(draft) == '2500/300'
    assert _payload(draft)['deposit_total'] == '2500'


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
    assert payload['deposit_total'] == '500'
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
    assert sale_amount_totals(draft) == {'deposit': '0', 'payment': ''}
    assert deposit_payment_text(draft) == '0/'
    assert _payload(draft)['deposit_total'] == '0'


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
    flat = text.replace('\n', ' ')
    assert 'Payment: $159.50' in flat
    assert '0/159.5' in flat.replace(' ', '')
