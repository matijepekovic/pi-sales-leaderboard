"""Authored redlines have a product-comment destination without changing notes."""
import pytest

from printer_app.mod_resulting.contract import mod_note_text
from printer_app.tests.test_mod_resulting_salesforce_mapping import _payload
from printer_app.tests.test_mod_resulting_submission_failures import DAY, _service, _run


@pytest.mark.parametrize('manual', ['Manual scope correction', 'Line one\nLine two'])
def test_only_manual_redline_is_passed_to_the_product_comment(manual):
    payload = _payload(
        'sale', interest='Roofing', notes='Customer note', numbers='25000\n17000\n12',
        redlines=manual, result_detail='Price Objection', dnr=True, dnr_reason='Roofing',
        sale_products={'Roofing': {'price': '17000', 'deposit': '500', 'payment': '159'}},
    )
    assert payload['product_results'][0]['comment'] == manual
    assert payload['fields']['price'] == {'highest': '25000', 'lowest': '17000'}
    assert mod_note_text(payload['draft']) == '25000\n17000\n12\nCustomer note'
    assert payload['deposit_payment'] == '500/159'
    assert manual in payload['final_redlines']
    assert 'Price Objection' in payload['final_redlines']
    assert 'DNR - Roofing' in payload['final_redlines']
    assert 'SALE Roofing:' in payload['final_redlines']


def test_legacy_manual_red_ink_is_routed_without_copying_black_notes():
    payload = _payload(
        interest='Roofing', notes='Black note\nKnown red ink',
        note_runs=[{'text': 'Black note\n', 'red': False},
                   {'text': 'Known red ink', 'red': True}],
        redlines='New redline',
    )
    assert payload['product_results'][0]['comment'] == 'Known red ink\nNew redline'
    assert mod_note_text(payload['draft']) == 'Black note'


def test_generated_annotations_alone_do_not_populate_a_product_comment():
    payload = _payload(
        'sale', interest='Roofing', notes='Black note',
        result_detail='Price Objection', dnr=True, dnr_reason='Roofing',
        sale_products={'Roofing': {'price': '17000', 'deposit': '500'}},
    )
    assert not payload['product_results'][0].get('comment')
    assert mod_note_text(payload['draft']) == 'Black note'


def test_shared_manual_redline_goes_to_every_resulted_product():
    payload = _payload(
        interest='Roofing;Siding', redlines='Shared scope correction',
        additional_products=True, primary_product='Roofing',
        product_results={'Siding': {'result': 'np', 'detail': 'Not Home'}},
    )
    assert [entry['product'] for entry in payload['product_results']] == ['Roofing', 'Siding']
    assert {entry['comment'] for entry in payload['product_results']} == {'Shared scope correction'}
    assert [entry['result'] for entry in payload['product_results']] == ['pns', 'np']


def test_unresulted_zero_price_product_does_not_receive_a_manual_comment():
    payload = _payload('sale', redlines='Only the sold product is resulted', sale_products={
        'Roofing': {'price': '17000', 'deposit': '0'},
        'Siding': {'price': '0', 'deposit': ''},
    })
    assert [entry['product'] for entry in payload['product_results']] == ['Roofing']
    assert payload['product_results'][0]['comment'] == 'Only the sold product is resulted'


def test_manual_redline_cannot_be_lost_when_no_product_is_resulted():
    with pytest.raises(ValueError, match='manual redline needs a resulted product'):
        _payload('sale', redlines='Keep this note', sale_products={
            'Roofing': {'price': '0', 'deposit': ''},
        })


def test_zero_product_sale_without_a_manual_redline_keeps_existing_behavior():
    payload = _payload('sale', sale_products={'Roofing': {'price': '0', 'deposit': ''}})
    assert payload['product_results'] == []


def test_background_rejection_preserves_a_manual_redline_without_a_product_destination(tmp_path):
    service, repo, writer, records = _service(tmp_path, leads=(1,))
    before = repo.sheets(DAY)[0]
    draft = dict(before['draft'], dispo='sale', redlines='Do not lose this note',
                 sale_products={'Roofing': {'price': '0', 'deposit': ''}})
    repo.save_draft(DAY, records[0].source_id, draft, before['revision'])
    saved = repo.sheets(DAY)[0]['draft']
    result, status = _run(service, repo)
    assert result['ok'] is False
    assert status['items'][0]['state'] == 'rejected'
    assert 'manual redline needs a resulted product' in status['items'][0]['error']
    assert writer.attempted == []
    assert repo.sheets(DAY)[0]['draft'] == saved
