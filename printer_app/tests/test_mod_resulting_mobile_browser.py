"""Phone viewport behavior uses the real Printer page and unchanged sheet geometry."""
import os

import pytest

from printer_app.mod_resulting.surface import BOXES, WIDTH, HEIGHT
from printer_app.tests.test_mod_resulting_browser import mod_browser

pytestmark = pytest.mark.skipif(
    os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')


def _assert_overlay_positions(sheet):
    paper = sheet.bounding_box()
    for name, original in BOXES.items():
        control = sheet.locator('.field-' + name)
        if not control.count():
            continue
        expected = original.inset()
        actual = control.bounding_box()
        for axis, value in {
            'x': paper['x'] + expected.x / WIDTH * paper['width'],
            'y': paper['y'] + expected.y / HEIGHT * paper['height'],
            'width': expected.width / WIDTH * paper['width'],
            'height': expected.height / HEIGHT * paper['height'],
        }.items():
            assert abs(actual[axis] - value) < 1.2, (name, axis, actual, value)


@pytest.mark.parametrize('viewport', [(320, 740), (390, 844), (844, 390)])
def test_phone_fit_zoom_pan_and_refresh_keep_the_actual_sheet(mod_browser, viewport):
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    width, height = viewport
    page.set_viewport_size({'width': width, 'height': height})
    response = page.goto(origin + '/mod-resulting')
    assert response.status == 200
    assert "style-src 'self'" in response.headers['content-security-policy']
    expect(page).to_have_title('MOD Sheets')
    first = page.locator('.mod-sheet').first
    expect(first).to_have_class('mod-sheet surface-ready')
    assert page.evaluate('document.documentElement.scrollWidth') <= width + 1
    assert first.bounding_box()['width'] == pytest.approx(width - 16, abs=1)
    assert first.bounding_box()['y'] >= page.locator('.floating-controls').bounding_box()['height']
    _assert_overlay_positions(first)
    for selector in ('#nameSearch', '#dailyMod', '#refresh', '#submitDay', '#zoomIn', '#zoomFit'):
        box = page.locator(selector).bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
        assert box['height'] >= 44
    expect(page.locator('#notice')).to_be_hidden()
    for _ in range(3):
        page.locator('#zoomIn').click()
    expect(page.locator('#sheets')).to_have_attribute('data-zoom', '3')
    assert first.bounding_box()['width'] == pytest.approx(3 * (width - 16), abs=1)
    assert page.evaluate('document.documentElement.scrollWidth') <= width + 1
    _assert_overlay_positions(first)
    page.locator('#sheets').evaluate('(el) => el.scrollLeft = el.scrollWidth - el.clientWidth')
    assert page.locator('#sheets').evaluate('(el) => el.scrollLeft') > 0
    assert page.locator('#zoomIn').bounding_box()['x'] + page.locator('#zoomIn').bounding_box()['width'] <= width
    # Only presentation scales: the original controls and normal save path remain.
    first.locator('[data-key=notes]').fill('Phone black notes')
    expect(first.locator('[data-key=redlines]')).to_be_hidden()
    first.locator('[data-key=review]').check()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(first).to_have_class('mod-sheet surface-ready')
    expect(page.locator('#sheets')).to_have_attribute('data-zoom', '3')
    expect(first.locator('[data-key=notes]')).to_have_value('Phone black notes')
    expect(first.locator('[data-key=redlines]')).to_be_hidden()
    expect(first.locator('[data-key=review]')).to_be_checked()
    saved = service.repository.sheets(service.day())[0]['draft']
    assert saved['notes'] == 'Phone black notes' and saved['review'] is True
    page.locator('#zoomFit').click()
    expect(page.locator('#sheets')).to_have_attribute('data-zoom', '1')
    assert page.locator('#sheets').evaluate('(el) => el.scrollLeft') == 0
    assert first.bounding_box()['width'] == pytest.approx(width - 16, abs=1)
    _assert_overlay_positions(first)
    page.locator('#nameSearch').fill('Alex')
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#nameSearch').fill('00011111')
    expect(page.locator('.mod-sheet:visible')).to_have_count(0)
    page.locator('#nameSearch').fill('')
    expect(page.locator('.mod-sheet:visible')).to_have_count(2)
    assert page.locator('[style]').count() == 0
    assert page.evaluate('window.modCspViolations') == []
    assert not service.allow_salesforce_writes and writer.applied == []
    evidence('phone-fit-' + str(width))


def test_setup_notice_is_absent_but_failed_saves_still_show(mod_browser, monkeypatch):
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    def unavailable():
        raise RuntimeError('Unfinished dropdown mapping')
    monkeypatch.setattr(writer, 'dropdowns', unavailable)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.goto(origin + '/mod-resulting').status == 200
    first = page.locator('.mod-sheet').first
    expect(first).to_have_class('mod-sheet surface-ready')
    expect(page.locator('#notice')).to_be_hidden()
    expect(page.get_by_text('draft choices are unverified', exact=False)).to_have_count(0)
    # Preserve real failure visibility rather than hiding every notification.
    page.route('**/mod-resulting/api/save', lambda route: route.fulfill(
        status=409, content_type='application/json',
        body='{"ok":false,"error":"Save rejected for test"}'))
    first.locator('[data-key=notes]').fill('Unsaved phone note')
    expect(first.locator('.sheet-message')).to_contain_text('Not saved: Save rejected for test')
    expect(first.locator('[data-key=notes]')).to_have_value('Unsaved phone note')
    assert not service.allow_salesforce_writes and writer.applied == []
    assert page.evaluate('window.modCspViolations') == []


def test_saved_sale_and_dnr_choices_survive_missing_salesforce_metadata(mod_browser, monkeypatch):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import clean_draft

    page, service, writer, origin, evidence = mod_browser
    day = service.day()
    first_id = service.repository.sheets(day)[0]['work_order_id']
    service.save(day, first_id, clean_draft({
        'dispo': 'sale',
        'dnr': True,
        'dnr_reason': 'Roofing',
        'sale_products': {
            'Windows': {'price': '18000', 'deposit': '0'},
        },
        'notes': 'Saved before metadata outage',
    }), 0)

    def unavailable():
        raise RuntimeError('Salesforce picklists are not available')
    monkeypatch.setattr(writer, 'dropdowns', unavailable)

    assert page.goto(origin + '/mod-resulting').status == 200
    first = page.locator('.mod-sheet').first
    expect(first).to_have_class('mod-sheet surface-ready')
    expect(page.locator('#notice')).to_be_hidden()
    selected = first.locator('[data-sale-product="Windows"]')
    expect(selected).to_have_count(1)
    expect(selected.locator('[data-sale-selected]')).to_be_checked()
    expect(selected.locator('[data-sale-price]')).to_have_value('18000')
    expect(selected.locator('[data-sale-deposit]')).to_have_value('0')
    values = first.locator('[data-key=dnr_reason]').evaluate(
        '(el) => [...el.selectedOptions].map(opt => opt.value)'
    )
    assert values == ['Roofing']

    expect(first.locator('[data-key=notes]')).to_be_hidden()
    first.locator('[data-key=redlines]').fill('Edited redline during metadata outage')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()

    draft = service.repository.sheets(day)[0]['draft']
    assert draft['sale_products'] == {
        'Windows': {'price': '18000', 'deposit': '0'},
    }
    assert draft['dnr_reason'] == 'Roofing'
    assert draft['notes'] == 'Saved before metadata outage'
    assert draft['redlines'] == 'Edited redline during metadata outage'
    assert not service.allow_salesforce_writes and writer.applied == []
