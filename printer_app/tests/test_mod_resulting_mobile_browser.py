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
def test_phone_native_pinch_and_refresh_keep_the_actual_sheet(mod_browser, viewport):
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
    for selector in ('#nameSearch', '#dailyMod', '#refresh', '#submitDay'):
        box = page.locator(selector).bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
        assert box['height'] >= 44
    expect(page.locator('#notice')).to_be_hidden()
    expect(page.locator('#sheetZoom,#zoomOut,#zoomFit,#zoomIn')).to_have_count(0)
    assert page.locator('meta[name=viewport]').get_attribute('content') == (
        'width=device-width,initial-scale=1'
    )
    assert first.bounding_box()['width'] == pytest.approx(width - 16, abs=1)
    _assert_overlay_positions(first)
    # The sheet still starts fit-to-width; users use browser-native pinch zoom.
    first.locator('[data-key=notes]').fill('Phone black notes')
    expect(first.locator('[data-key=redlines]')).to_have_count(0)
    first.locator('[data-key=review]').check()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(first).to_have_class('mod-sheet surface-ready')
    expect(page.locator('#sheets')).not_to_have_attribute('data-zoom', '3')
    expect(first.locator('[data-key=notes]')).to_have_value('Phone black notes')
    expect(first.locator('[data-key=redlines]')).to_have_count(0)
    expect(first.locator('[data-key=review]')).to_be_checked()
    saved = service.repository.sheets(service.day())[0]['draft']
    assert saved['notes'] == 'Phone black notes' and saved['review'] is True
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

    expect(first.locator('[data-key=notes]')).to_be_visible()
    expect(first.locator('[data-key=notes]')).to_have_value('Saved before metadata outage')
    first.locator('[data-key=notes]').fill('Saved before metadata outage\nEdited comment during metadata outage')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()

    draft = service.repository.sheets(day)[0]['draft']
    assert draft['sale_products'] == {
        'Windows': {'price': '18000', 'deposit': '0'},
    }
    assert draft['dnr_reason'] == 'Roofing'
    assert draft['notes'] == 'Saved before metadata outage\nEdited comment during metadata outage'
    assert draft['redlines'] == ''
    assert not service.allow_salesforce_writes and writer.applied == []


def test_popup_tracks_visible_viewport_when_zoomed_or_keyboard_opens(mod_browser):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':390,'height':844})
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    first.locator('[data-key=dispo]').select_option('sale')
    dialog = first.locator('.sale-panel[open]')
    expect(dialog).to_be_visible()
    assert dialog.evaluate('(el) => getComputedStyle(el).display') == 'flex'
    # Before any keyboard opens, ordinary 1x uses the browser's native dialog
    # geometry rather than a JS transform. This prevents the footer/Done row
    # from floating in a second synthetic viewport.
    expect(dialog).to_have_css('transform', 'none')
    assert dialog.locator('.editor-body').evaluate(
        '(el) => getComputedStyle(el).overflowY') == 'auto'
    def footer_inside():
        outer = dialog.bounding_box()
        footer = dialog.locator('.editor-footer').bounding_box()
        assert footer['y'] >= outer['y'] - 1
        assert footer['y'] + footer['height'] <= outer['y'] + outer['height'] + 1
    footer_inside()

    # Simulate the coordinates mobile Safari/Chromium report after a 2x pinch.
    # The viewport is read-only in production, so override the page's getter
    # in this browser regression and dispatch a normal window resize.
    page.evaluate("""() => {
      const fake = new EventTarget();
      Object.assign(fake, {
        width:180, height:220, scale:2, offsetLeft:50, offsetTop:60
      });
      Object.defineProperty(window, 'visualViewport', {
        configurable:true, value:fake
      });
      window.__testViewport = fake;
      window.dispatchEvent(new Event('resize'));
    }""")
    expect(dialog).to_have_css('transform', 'matrix(0.5, 0, 0, 0.5, 0, 0)')
    bounds = dialog.bounding_box()
    assert bounds['x'] >= 50-2 and bounds['x']+bounds['width'] <= 230+2
    assert bounds['y'] >= 60-2 and bounds['y']+bounds['height'] <= 280+2

    # Keyboard reduces only the visible viewport. The popup must shrink with
    # it, preserving its scrollable body and the Done action.
    page.evaluate("""() => {
      window.__testViewport.height=120;
      window.dispatchEvent(new Event('resize'));
    }""")
    expect(dialog).to_have_css('max-height', '224px')
    footer_inside()
    bounds=dialog.bounding_box()
    assert bounds['y'] >= 60-2 and bounds['y']+bounds['height'] <= 180+2

    # Strong pinch makes the visual viewport narrower than 120 CSS px.
    # Never clamp the dialog wider than what the phone can actually show.
    page.evaluate("""() => {
      window.__testViewport.width=75;
      window.__testViewport.scale=5;
      window.dispatchEvent(new Event('resize'));
    }""")
    expect(dialog).to_have_css('transform', 'matrix(0.2, 0, 0, 0.2, 0, 0)')
    footer_inside()
    bounds=dialog.bounding_box()
    assert bounds['x'] >= 50-2 and bounds['x']+bounds['width'] <= 125+2
    assert bounds['y'] >= 60-2 and bounds['y']+bounds['height'] <= 180+2
    assert dialog.locator('.editor-footer').count()==1
    assert dialog.locator('[data-sale-product="Roofing"]').count()==1
    assert page.locator('[style]').count()==0
    assert page.evaluate('window.modCspViolations') == []
    assert not service.allow_salesforce_writes and writer.applied == []


def test_popup_fits_native_zoom_before_opening_and_allows_zoom_again(mod_browser):
    """Exercise a real zoomed Chromium page; WebKit geometry has its own test."""
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    if page.context.browser.browser_type.name != 'chromium':
        pytest.skip('CDP pinch-scale injection is specific to Chromium')
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.goto(origin + '/mod-resulting').status == 200
    page.evaluate("""() => {
      const dialog = document.querySelector('.sale-panel');
      window.modalScaleAtOpen = null;
      new MutationObserver(() => {
        if (dialog.open && window.modalScaleAtOpen === null)
          window.modalScaleAtOpen = window.visualViewport.scale;
      }).observe(dialog, {attributes:true, attributeFilter:['open']});
    }""")
    cdp = page.context.new_cdp_session(page)
    cdp.send('Emulation.setDeviceMetricsOverride', {
        'width':390, 'height':844, 'deviceScaleFactor':2, 'mobile':True,
    })
    cdp.send('Emulation.setPageScaleFactor', {'pageScaleFactor':2.5})
    assert page.evaluate('window.visualViewport.scale') > 2.4
    page.locator('#hideCompleted').check()

    # Trigger the same user-driven disposition change without Playwright
    # scrolling/focusing the field and interfering with the pinch simulation.
    page.evaluate("""() => {
      const dispo = document.querySelector('.mod-sheet [data-key=dispo]');
      dispo.value = 'sale';
      dispo.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    popup = page.locator('.sale-panel[open]').first
    expect(popup).to_be_visible()
    expect(page.locator('.mod-sheet').first).to_be_visible()
    assert page.evaluate('window.modalScaleAtOpen') == pytest.approx(1, abs=.02)
    assert page.evaluate('window.visualViewport.scale') == pytest.approx(1, abs=.02)
    expect(popup).to_have_css('transform', 'none')
    assert page.locator('meta[name=viewport]').get_attribute('content') == (
        'width=device-width,initial-scale=1'
    )
    assert page.locator('#sheets').get_attribute('data-zoom') == '1'
    assert page.locator('#zoomFit,#zoomIn,#zoomOut').count() == 0
    assert page.evaluate('window.modCspViolations') == []
    popup.locator('.sale-done').click()
    expect(popup).to_be_hidden()
    expect(page.locator('.mod-sheet').first).to_be_hidden()

    # The fit is automatic for popups, but pinch remains available afterward.
    cdp.send('Emulation.setPageScaleFactor', {'pageScaleFactor':2.5})
    assert page.evaluate('window.visualViewport.scale') > 2.4
    assert not service.allow_salesforce_writes and writer.applied == []
