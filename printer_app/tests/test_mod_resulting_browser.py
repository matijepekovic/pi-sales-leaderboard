"""Native browser regression for the actual MOD sandbox, not DOM-source assertions."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.tests.auth_helpers import browser_login
from printer_app.mod_resulting.surface import BOXES, WIDTH, HEIGHT


pytestmark = pytest.mark.skipif(
    os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies'
)

MOD = '005000000000001AAA'


class FakeModSource:
    def __init__(self, records):
        self.records_data = records

    def records(self, **kwargs):
        return tuple(self.records_data)


class FakeModWriter:
    def __init__(self):
        self.applied = []

    def mod_users(self):
        return [{'id':MOD,'name':'Sample MOD'}]

    def dropdowns(self):
        return {'result_details':[{'value':'Price Objection','label':'Price Objection'}],
                'dnr_reasons':[{'value':'Roofing','label':'Roofing'}]}

    def prepare(self, payload):
        return [[('sample',)] for _ in payload]

    def apply(self, plan):
        self.applied.append(plan)


@pytest.fixture(params=['chromium','webkit'])
def mod_browser(tmp_path, request):
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path/'data', env_file=env,
                            secret_key='s'*64, email_enabled=False))
    app.testing = True
    source = FakeModSource([
        ModSheetRecord(source_id='0WO000000000001AAA',
            lead_name='Alex Example',work_order_number='00011111',product_interest='Roofing;Siding'),
        ModSheetRecord(source_id='0WO000000000002AAA',
            lead_name='Blair Sample',work_order_number='00022222',product_interest='Bath'),
    ])
    writer = FakeModWriter()
    service = app.extensions['mod_resulting']
    service.source = source
    service.writer = writer
    service.refresh(service.day())
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = getattr(pw, request.param).launch(headless=True)
            context = browser.new_context(viewport={'width':1200,'height':820})
            try:
                page = context.new_page()
                page.add_init_script("""
                    window.modCspViolations = [];
                    document.addEventListener('securitypolicyviolation', event => {
                        window.modCspViolations.push(event.violatedDirective);
                    });
                """)
                errors = []
                page.on('pageerror',lambda err:errors.append(str(err)))
                browser_login(page,app,origin)
                yield page,service,writer,origin
                assert not errors
                if '/mod-resulting' in page.url:
                    assert page.evaluate('window.modCspViolations') == []
                db = app.extensions['printer_db']
                for table in ('jobs','print_attempts','commands','print_queue_releases'):
                    assert db.rows('SELECT * FROM '+table)==[]
            finally:
                context.close()
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_mod_sheets_render_as_full_sheets_and_are_searchable_by_name_only(mod_browser):
    from playwright.sync_api import expect

    page,service,writer,origin = mod_browser
    assert page.goto(origin+'/mod-resulting').status==200
    expect(page.locator('.mod-sheet')).to_have_count(2)
    expect(page.locator('.mod-sheet.surface-ready')).to_have_count(2)
    assert page.locator('body > header,body > nav,body > footer').count()==0
    expect(page.locator('#nameSearch')).to_be_visible()
    first = page.locator('.mod-sheet').first
    expect(first.locator('[data-key=numbers]')).to_be_visible()
    expect(first.locator('[data-key=notes]')).to_be_visible()
    expect(first.locator('[data-key=redlines]')).to_be_visible()

    page.locator('#nameSearch').fill('alex')
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#nameSearch').fill('00022222')
    expect(page.locator('.mod-sheet:visible')).to_have_count(0)
    page.locator('#nameSearch').fill('')
    expect(page.locator('.mod-sheet:visible')).to_have_count(2)

    first.locator('[data-key=dispo]').select_option('cxl')
    expect(first.locator('.cxl-panel')).to_be_visible()
    first.locator('[data-key=cxl_at_lead]').check()
    first.locator('[data-key=notes]').fill('Black comment')
    first.locator('[data-key=redlines]').fill('REDLINE')
    first.locator('[data-key=numbers]').fill('20000\n17000')
    page.locator('#hideCompleted').check()
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#hideCompleted').uncheck()

    # Refresh flushes the changed draft to disk, then reloads Salesforce-owned data.
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(page.locator('.mod-sheet')).to_have_count(2)
    expect(page.locator('.mod-sheet').first.locator('[data-key=notes]')).to_have_value('Black comment')
    row = service.repository.sheets(service.day())[0]
    assert row['draft']['dispo']=='cxl'
    assert row['draft']['cxl_at_lead'] is True

    page.locator('#dailyMod').select_option(MOD)
    expect(page.locator('#notice')).to_contain_text('Sample MOD')
    assert service.repository.day(service.day())['mod_user_id']==MOD
    page.locator('#submitDay').click()
    expect(page.locator('#endConfirm')).to_be_visible()
    expect(page.locator('#reviewCount')).to_contain_text('1 resulted sheet(s)')
    page.locator('#cancelEnd').click()
    assert not writer.applied


def _evidence(page, label):
    directory = os.environ.get('MOD_RESULTING_QA_DIR')
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        browser = page.context.browser.browser_type.name
        page.screenshot(path=target / (browser + '-' + label + '.png'), full_page=False)


@pytest.mark.parametrize('viewport', [(1500, 1000), (1200, 820), (390, 844)])
def test_original_renderer_image_and_controls_align_under_real_csp(mod_browser, viewport):
    from playwright.sync_api import expect
    page,service,writer,origin = mod_browser
    page.set_viewport_size({'width':viewport[0],'height':viewport[1]})
    response = page.goto(origin + '/mod-resulting')
    assert response.status == 200
    assert "style-src 'self'" in response.headers['content-security-policy']
    assert "'unsafe-inline'" not in response.headers['content-security-policy']
    expect(page).to_have_title('MOD Sheets')
    first = page.locator('.mod-sheet').first
    expect(first).to_have_class('mod-sheet surface-ready')
    image = first.locator('.printer-sheet')
    assert image.evaluate('(img) => img.complete && img.naturalWidth > 0')
    image_response = page.request.get(origin + image.get_attribute('src'))
    assert image_response.ok and image_response.headers['content-type'].startswith('image/png')
    assert page.locator('[style]').count() == 0
    paper = first.bounding_box()
    assert abs(paper['width'] / paper['height'] - WIDTH / HEIGHT) < .002
    # Test every overlay, rather than only whether fields happen to exist.
    for name, original in BOXES.items():
        control = first.locator('.field-' + name)
        if not control.count():
            continue
        box = original.inset()
        actual = control.bounding_box()
        expected = {
            'x':paper['x'] + box.x / WIDTH * paper['width'],
            'y':paper['y'] + box.y / HEIGHT * paper['height'],
            'width':box.width / WIDTH * paper['width'],
            'height':box.height / HEIGHT * paper['height'],
        }
        for axis, value in expected.items():
            assert abs(actual[axis] - value) < 1.2, (name, axis, actual, expected)
    notes = first.locator('.field-notes').bounding_box()
    assert notes['width'] > paper['width'] * .59
    assert notes['height'] > paper['height'] * .54
    assert page.evaluate('window.modCspViolations') == []
    _evidence(page, 'layout-' + str(viewport[0]))


def test_notes_and_context_controls_remain_in_original_boxes(mod_browser):
    from playwright.sync_api import expect
    page,service,writer,origin = mod_browser
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    expect(first).to_have_class('mod-sheet surface-ready')
    bounds = first.locator('.field-notes').bounding_box()
    first.locator('[data-key=dispo]').select_option('sale')
    first.locator('[data-key=notes]').fill('Black comment above redlines.')
    first.locator('[data-key=redlines]').fill('REPLACE TRIM WITH FULL SCOPE.')
    first.locator('[data-key=numbers]').fill('25,000\n17,850')
    for key in ('power_questions','t_close','ninety_min','docs','bid_sheets',
                'promotion','one_leg','free_lead'):
        first.locator('[data-key=' + key + ']').check()
    first.locator('[data-key=dnr]').check()
    expect(first.locator('.dnr-panel')).to_be_visible()
    # The DNR picker must not be clipped inside the tiny checkbox cell.
    reason = first.locator('[data-key=dnr_reason]')
    reason.select_option('Roofing')
    expect(first.locator('.dnr-in-redline')).to_have_text('DNR - Roofing')
    first.locator('.dnr-panel .close-popover').click()
    first.locator('[data-key=additional_products]').check()
    expect(first.locator('.product-panel')).to_be_visible()
    for row in first.locator('[data-product]').all():
        row.locator('[data-product-result]').select_option('sale')
    first.locator('.product-panel .close-popover').click()
    first.locator('[data-key=call_1]').fill('10:15 AM')
    first.locator('[data-key=call_2]').fill('10:27 AM')
    assert first.locator('.field-notes').bounding_box() == bounds
    red = first.locator('[data-key=redlines]')
    assert red.evaluate('(el) => getComputedStyle(el).color') == 'rgb(176, 0, 0)'
    assert int(red.evaluate('(el) => getComputedStyle(el).fontWeight')) >= 700
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(page.locator('.mod-sheet').first).to_have_class('mod-sheet surface-ready')
    draft = service.repository.sheets(service.day())[0]['draft']
    assert draft['notes'] == 'Black comment above redlines.'
    assert draft['dnr_reason'] == 'Roofing'
    assert draft['call_1'] == '10:15 AM'
    _evidence(page, 'filled-sheet')
    assert service.allow_salesforce_writes is False and not writer.applied
