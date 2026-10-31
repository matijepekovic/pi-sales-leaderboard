"""Result Detail and CXL At Lead share one independent, mobile-safe editor."""
import os

import pytest

from printer_app.tests.test_mod_resulting_browser import mod_browser

pytestmark = pytest.mark.skipif(
    os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_result_detail_and_cxl_at_lead_survive_every_disposition_and_refresh(
        mod_browser, viewport):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
    assert page.goto(origin + '/mod-resulting').status == 200
    sheet = page.locator('.mod-sheet').first
    expect(sheet).to_have_class('mod-sheet surface-ready')
    assert sheet.locator('[data-key="cxl_at_lead"]').count() == 1
    assert sheet.locator('[data-key="result_detail"]').count() == 1
    assert sheet.locator('.cxl-panel,.edit-cxl-details').count() == 0
    assert sheet.locator('[data-cxl-indicator]').is_hidden()
    original_detail = sheet.locator('.field-detail').bounding_box()
    original_notes = sheet.locator('.field-notes').bounding_box()

    sheet.locator('[data-key="notes"]').fill('Keep this local MOD note')
    sheet.locator('[data-key="dispo"]').select_option('pns')
    sheet.locator('.edit-result-detail').click()
    popup = sheet.locator('.detail-panel[open]')
    expect(popup).to_be_visible()
    expect(page.locator('.editor-dialog[open]')).to_have_count(1)
    popup.locator('[data-key="result_detail"]').select_option('Price Objection')
    popup.locator('[data-key="cxl_at_lead"]').check()
    popup.locator('.editor-primary').click()
    expect(popup).not_to_be_visible()
    expect(sheet.locator('[data-detail-display]')).to_have_text('Price Objection')
    expect(sheet.locator('[data-cxl-indicator]')).to_be_visible()
    expect(sheet.locator('[data-cxl-indicator]')).to_have_text('CXL')
    expect(sheet.locator('.result-detail-in-redline')).to_have_text('Price Objection')

    for disposition in ('np', 'cxl', 'nra', 'oos', 'sale', 'pns'):
        sheet.locator('[data-key="dispo"]').select_option(disposition)
        if disposition == 'sale':
            expect(sheet.locator('.sale-panel')).to_be_visible()
            sheet.locator('.sale-panel .editor-primary').click()
        # Selecting CXL does not force a cancellation popup, and its checkbox
        # cannot overwrite the selected disposition.
        expect(page.locator('.editor-dialog[open]')).to_have_count(0)
        expect(sheet.locator('[data-cxl-indicator]')).to_be_visible()
        sheet.locator('.edit-result-detail').click()
        expect(popup.locator('[data-key="cxl_at_lead"]')).to_be_checked()
        expect(popup.locator('[data-key="result_detail"]')).to_have_value('Price Objection')
        popup.locator('.editor-primary').click()
        expect(sheet.locator('[data-key="dispo"]')).to_have_value(disposition)

    assert sheet.locator('.field-detail').bounding_box() == pytest.approx(original_detail, abs=1)
    assert sheet.locator('.field-notes').bounding_box() == pytest.approx(original_notes, abs=1)
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    sheet = page.locator('.mod-sheet').first
    expect(sheet.locator('[data-detail-display]')).to_have_text('Price Objection')
    expect(sheet.locator('[data-cxl-indicator]')).to_be_visible()
    expect(sheet.locator('[data-key="notes"]')).to_have_value('Keep this local MOD note')
    saved = service.repository.sheets(service.day())[0]['draft']
    assert (saved['dispo'], saved['result_detail'], saved['cxl_at_lead']) == (
        'pns', 'Price Objection', True)
    assert saved['notes'] == 'Keep this local MOD note'

    # CXL at Lead can be cleared without changing the result or notes.
    sheet.locator('.edit-result-detail').click()
    sheet.locator('[data-key="cxl_at_lead"]').uncheck()
    sheet.locator('.detail-panel .editor-primary').click()
    expect(sheet.locator('[data-cxl-indicator]')).to_be_hidden()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    saved = service.repository.sheets(service.day())[0]['draft']
    assert saved['cxl_at_lead'] is False
    assert saved['dispo'] == 'pns'
    assert saved['result_detail'] == 'Price Objection'
    assert saved['notes'] == 'Keep this local MOD note'
    assert not writer.applied
    evidence('result-detail-popup-' + str(viewport[0]))
