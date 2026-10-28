"""Exercise the actual sandbox; verify application behavior before diagnostic capture."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

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

    def mod_users(self, market_segment):
        assert market_segment == "Olympia"
        return [{'id': MOD, 'name': 'Sample MOD'}]

    def dropdowns(self):
        return {
            'result_details': [{'value':'Price Objection','label':'Price Objection'}],
            'dnr_reasons': [{'value':'Roofing','label':'Roofing'}],
            'lead_status': [
                {'value':value,'label':value}
                for value in ('Sale Pending','Nurturing','Canceled','Out of Scope','Do Not Call')
            ],
            'previous_results': [
                {'value':value,'label':value}
                for value in ('Pitch No Sale','No Pitch','No Rep Available')
            ],
            'products': [
                {'value':value,'label':value}
                for value in ('Roofing','Siding','Windows')
            ],
        }

    def prepare(self, payload):
        return [[('sample',)] for _ in payload]

    def apply(self, plan):
        self.applied.append(plan)


def _capture_evidence(page, name, application_audit):
    """Capture only after all application assertions, never during the test flow.

    Playwright's WebKit screenshot preparation appends an inline `body {}`
    stylesheet even with caret='initial' and animations='allow'. That diagnostic
    operation itself triggers strict CSP. Do not relax Printer CSP, filter its
    events, or disable WebKit coverage to accommodate screenshot instrumentation.
    https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/server/screenshotter.ts
    """
    directory = os.environ.get('MOD_RESULTING_QA_DIR')
    if not directory:
        return
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    browser = page.context.browser.browser_type.name
    prefix = target / (browser + '-' + name)
    prefix.with_suffix('.json').write_text(json.dumps(application_audit, indent=2))
    page.screenshot(path=prefix.with_suffix('.png'), full_page=False, caret='initial')


@pytest.fixture(params=['chromium', 'webkit'])
def mod_browser(tmp_path, request):
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path / 'data', env_file=env,
                            secret_key='s' * 64, email_enabled=False))
    app.testing = True
    source = FakeModSource([
        ModSheetRecord(source_id='0WO000000000001AAA',
            lead_name='Alex Example', work_order_number='00011111', product_interest='Roofing;Siding',
            assigned_service_resources=('Lama King','Isaiah North')),
        ModSheetRecord(source_id='0WO000000000002AAA',
            lead_name='Blair Sample', work_order_number='00022222', product_interest='Bath',
            assigned_service_resources=('Dan South',)),
    ])
    writer = FakeModWriter()
    service = app.extensions['mod_resulting']
    service.source = source
    service.writer = writer
    service.settings_repository = SimpleNamespace(
        settings=lambda: SimpleNamespace(market_segment='Olympia'))
    service.refresh(service.day())
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = getattr(pw, request.param).launch(headless=True)
            context = browser.new_context(viewport={'width': 1200, 'height': 820})
            try:
                page = context.new_page()
                # Keep every application's CSP event across Refresh/navigation;
                # a later successful page must not erase an earlier violation.
                violations = []
                page.expose_binding('recordModCspViolation',
                                    lambda source, event: violations.append(event))
                page.add_init_script("""
                    window.modCspViolations = [];
                    document.addEventListener('securitypolicyviolation', event => {
                        const detail = {
                            directive: event.violatedDirective,
                            blockedURI: event.blockedURI,
                            documentURI: event.documentURI,
                            sourceFile: event.sourceFile,
                            lineNumber: event.lineNumber,
                            disposition: event.disposition
                        };
                        window.modCspViolations.push(detail);
                        window.recordModCspViolation(detail);
                    });
                """)
                errors = []
                page.on('pageerror', lambda err: errors.append(str(err)))
                evidence = []
                browser_login(page, app, origin)
                yield page, service, writer, origin, evidence.append
                # Drain queued DOM/security events before checking the complete
                # interaction history. No screenshot has run on this page yet.
                page.evaluate('() => new Promise(resolve => setTimeout(resolve, 0))')
                assert not errors, errors
                assert not violations, violations
                if '/mod-resulting' in page.url:
                    assert page.evaluate('window.modCspViolations') == []
                assert service.allow_salesforce_writes is False
                assert not writer.applied
                db = app.extensions['printer_db']
                for table in ('jobs', 'print_attempts', 'commands', 'print_queue_releases'):
                    assert db.rows('SELECT * FROM ' + table) == []
                # Diagnostic screenshots are the last operation, after the
                # real page and all its interactions pass unchanged strict CSP.
                audit = {'application_csp_violations': list(violations),
                         'page_errors': list(errors), 'salesforce_writes': len(writer.applied),
                         'viewport': page.viewport_size,
                         'capture_phase': 'after all application assertions'}
                for label in evidence:
                    _capture_evidence(page, label, audit)
            finally:
                context.close()
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_mod_sheets_search_customers_and_assigned_reps_only(mod_browser):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    assert page.goto(origin + '/mod-resulting').status == 200
    expect(page.locator('.mod-sheet')).to_have_count(2)
    expect(page.locator('.mod-sheet.surface-ready')).to_have_count(2)
    assert page.locator('body > header,body > nav,body > footer').count() == 0
    expect(page.locator('#nameSearch')).to_be_visible()
    first = page.locator('.mod-sheet').first
    for key in ('numbers', 'notes'):
        expect(first.locator('[data-key=' + key + ']')).to_be_visible()
    expect(first.locator('[data-key=redlines]')).to_have_count(0)

    page.locator('#nameSearch').fill('alex')
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#nameSearch').fill('lama')
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#nameSearch').fill('NORTH')
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#nameSearch').fill('dan')
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    expect(page.locator('.mod-sheet:visible').first).to_have_attribute('data-reps', 'dan south')
    page.locator('#nameSearch').fill('00022222')
    expect(page.locator('.mod-sheet:visible')).to_have_count(0)
    page.locator('#nameSearch').fill('')
    expect(page.locator('.mod-sheet:visible')).to_have_count(2)

    first.locator('[data-key=notes]').fill('Black comment')
    first.locator('[data-key=dispo]').select_option('cxl')
    expect(first.locator('.cxl-panel')).to_be_visible()
    first.locator('[data-key=cxl_at_lead]').check()
    first.locator('.cxl-panel .editor-primary').click()
    expect(first.locator('[data-key=notes]')).to_be_visible()
    expect(first.locator('[data-key=notes]')).to_have_value('Black comment')
    first.locator('[data-key=notes]').fill('Black comment\nREDLINE')
    first.locator('[data-key=numbers]').fill('20000\n17000')
    page.locator('#hideCompleted').check()
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#hideCompleted').uncheck()

    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(page.locator('.mod-sheet')).to_have_count(2)
    expect(page.locator('.mod-sheet').first.locator('[data-key=notes]')).to_have_value('Black comment\nREDLINE')
    row = service.repository.sheets(service.day())[0]
    assert row['draft']['dispo'] == 'cxl'
    assert row['draft']['cxl_at_lead'] is True

    page.locator('#dailyMod').select_option(MOD)
    expect(page.locator('#notice')).to_contain_text('Sample MOD')
    assert service.repository.day(service.day())['mod_user_id'] == MOD
    page.locator('#submitDay').click()
    expect(page.locator('#endConfirm')).to_be_visible()
    expect(page.locator('#reviewCount')).to_contain_text('1 resulted sheet(s)')
    expect(page.locator('#confirmEnd')).to_be_disabled()
    page.locator('#cancelEnd').click()
    assert not writer.applied
    evidence('search-and-refresh')


@pytest.mark.parametrize('viewport', [(1500, 1000), (1200, 820), (390, 844)])
def test_original_renderer_image_and_controls_align_under_real_csp(mod_browser, viewport):
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
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
    for name, original in BOXES.items():
        control = first.locator('.field-' + name)
        if not control.count():
            continue
        box = original.inset()
        actual = control.bounding_box()
        expected = {
            'x': paper['x'] + box.x / WIDTH * paper['width'],
            'y': paper['y'] + box.y / HEIGHT * paper['height'],
            'width': box.width / WIDTH * paper['width'],
            'height': box.height / HEIGHT * paper['height'],
        }
        for axis, value in expected.items():
            assert abs(actual[axis] - value) < 1.2, (name, axis, actual, expected)
    notes = first.locator('.field-notes').bounding_box()
    assert notes['width'] > paper['width'] * .59
    assert notes['height'] > paper['height'] * .54
    checklist = first.locator('.field-bids')
    expect(checklist).to_have_count(1)
    parent = checklist.bounding_box()
    for key in ('bid_sheets', 'promotion', 'review'):
        checkbox = checklist.locator('[data-key=' + key + ']')
        expect(checkbox).to_be_visible()
        box = checkbox.bounding_box()
        assert box['x'] >= parent['x'] - 1
        assert box['y'] >= parent['y'] - 1
        assert box['x'] + box['width'] <= parent['x'] + parent['width'] + 1
        assert box['y'] + box['height'] <= parent['y'] + parent['height'] + 1
    assert page.evaluate('window.modCspViolations') == []
    evidence('layout-' + str(viewport[0]))


def test_notes_and_context_controls_remain_in_original_boxes(mod_browser):
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    expect(first).to_have_class('mod-sheet surface-ready')
    bounds = first.locator('.field-notes').bounding_box()
    first.locator('[data-key=notes]').fill('Black comment above redlines.')
    first.locator('[data-key=dispo]').select_option('sale')
    expect(first.locator('.sale-panel')).to_be_visible()
    roof = first.locator('[data-sale-product="Roofing"]')
    roof.locator('[data-sale-selected]').check()
    roof.locator('[data-sale-price]').fill('17850')
    roof.locator('[data-sale-deposit]').fill('0')
    roof.locator('[data-sale-payment]').fill('159')
    expect(first.locator('[data-price-display="deposit_override"]')).to_have_text('0 / 159')
    expect(first.locator('.sale-in-redline')).to_have_text(
        'SALE Roofing: $17,850 | Deposit: $0 | Payment: $159')
    # Zero-priced selected products are not treated as sold.
    siding = first.locator('[data-sale-product="Siding"]')
    siding.locator('[data-sale-selected]').check()
    siding.locator('[data-sale-price]').fill('0')
    first.locator('.sale-panel .sale-done').click()
    expect(first.locator('[data-key=notes]')).to_have_value('Black comment above redlines.')
    red_pen=first.locator('.redline-pen')
    expect(red_pen).to_have_attribute('aria-pressed','false')
    red_pen.click()
    expect(red_pen).to_have_attribute('aria-pressed','true')
    first.locator('[data-key=notes]').fill('Black comment above redlines.\nREPLACE TRIM WITH FULL SCOPE.')
    first.locator('[data-key=numbers]').fill('25,000\n17,850')
    for key in ('power_questions', 't_close', 'ninety_min', 'docs', 'bid_sheets',
                'promotion', 'review', 'one_leg', 'free_lead'):
        first.locator('[data-key=' + key + ']').check()
    first.locator('[data-key=dnr]').check()
    expect(first.locator('.dnr-panel')).to_be_visible()
    first.locator('.dnr-panel [data-reason-choice][value="Roofing"]').check()
    expect(first.locator('.dnr-in-redline')).to_have_text('DNR - Roofing')
    first.locator('.dnr-panel .editor-primary').click()
    first.locator('[data-key=call_1]').fill('10:15 AM')
    first.locator('[data-key=call_2]').fill('10:27 AM')
    assert first.locator('.field-notes').bounding_box() == bounds
    red = first.locator('.mod-notes-display .after-dispo')
    expect(red).to_have_text('\nREPLACE TRIM WITH FULL SCOPE.')
    expect(first.locator('.mod-notes-display span').first).to_have_text(
        'Black comment above redlines.')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(first).to_have_class('mod-sheet surface-ready')
    draft = service.repository.sheets(service.day())[0]['draft']
    assert draft['notes'] == 'Black comment above redlines.\nREPLACE TRIM WITH FULL SCOPE.'
    assert draft['redlines'] == ''
    assert draft['note_runs'] == [
        {'text':'Black comment above redlines.', 'red':False},
        {'text':'\nREPLACE TRIM WITH FULL SCOPE.', 'red':True},
    ]
    assert draft['dnr_reason'] == 'Roofing'
    assert draft['sale_products'] == {
        'Roofing':{'price':'17850','deposit':'0','payment':'159'},
        'Siding':{'price':'0','deposit':''},
    }
    assert draft['call_1'] == '10:15 AM'
    assert draft['call_2'] == '10:27 AM'
    assert draft['review'] is True
    first.locator('[data-key=review]').uncheck()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(first).to_have_class('mod-sheet surface-ready')
    updated = service.repository.sheets(service.day())[0]['draft']
    assert updated == dict(draft, review=False)
    evidence('filled-sheet')
    assert service.allow_salesforce_writes is False and not writer.applied


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_every_editor_is_centered_and_only_one_popup_can_be_open(mod_browser, viewport):
    """All editors must use the viewport top layer, even in the zoomable PDF."""
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':viewport[0], 'height':viewport[1]})
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first

    def visible_popup(selector):
        dialog = page.locator(selector)
        expect(dialog).to_be_visible()
        expect(page.locator('.editor-dialog[open]')).to_have_count(1)
        box = dialog.bounding_box()
        assert box is not None
        assert box['x'] >= 0 and box['y'] >= 0, box
        assert box['x'] + box['width'] <= viewport[0] + 1, box
        assert box['y'] + box['height'] <= viewport[1] + 1, box
        return dialog

    first.locator('[data-key="dnr"]').check()
    popup = visible_popup('.dnr-panel[open]')
    popup.locator('[data-reason-choice][value="Roofing"]').check()
    expect(first.locator('.dnr-in-redline')).to_have_text('DNR - Roofing')
    popup.locator('.editor-primary').click()
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)

    first.locator('[data-key="dispo"]').select_option('sale')
    popup = visible_popup('.sale-panel[open]')
    expect(popup.locator('.sale-product-filter')).to_have_count(0)
    expect(popup.locator('[data-sale-product="Roofing"]')).to_be_visible()
    expect(popup.locator('[data-sale-product="Windows"]')).to_be_visible()
    popup.locator('[data-sale-product="Roofing"] [data-sale-selected]').check()
    popup.locator('[data-sale-product="Roofing"] [data-sale-price]').fill('17000')
    popup.locator('[data-sale-product="Roofing"] [data-sale-deposit]').fill('0')
    popup.locator('[data-sale-product="Roofing"] [data-sale-payment]').fill('135')
    expect(first.locator('.sale-in-redline')).to_have_text(
        'SALE Roofing: $17,000 | Deposit: $0 | Payment: $135')
    popup.locator('.sale-done').click()
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)
    first.locator('.edit-sale-products').click()
    expect(page.locator('.editor-dialog[open]')).to_have_count(1)
    first.locator('.sale-panel .sale-done').click()

    first.locator('[data-key="dispo"]').select_option('cxl')
    popup = visible_popup('.cxl-panel[open]')
    popup.locator('[data-key="cxl_at_lead"]').check()
    page.keyboard.press('Escape')
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)

    first.locator('[data-key="dispo"]').select_option('pns')
    first.locator('[data-key="additional_products"]').check()
    popup = visible_popup('.product-panel[open]')
    popup.locator('[data-product="Roofing"] [data-product-result]').select_option('np')
    popup.locator('.editor-primary').click()
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)

    # On every screen, the existing Call 1 cell is the tappable control.
    expect(first.locator('.mobile-call-actions')).to_have_count(0)
    call_one = first.locator('.field-call1 [data-time-trigger="call_1"]')
    if viewport[0] <= 900:
        cell=first.locator('.field-call1').bounding_box()
        target=call_one.bounding_box()
        assert cell and target
        assert abs(cell['x'] - target['x']) <= 2
        assert abs(cell['y'] - target['y']) <= 2
    call_one.click()
    popup = visible_popup('#timeDialog[open]')
    expect(popup.locator('#timeTitle')).to_have_text('Call 1 time')
    popup.locator('#timeHour').select_option('10')
    popup.locator('#timeMinute').select_option('15')
    popup.locator('#timePeriod').select_option('AM')
    popup.locator('#timeApply').click()
    expect(first.locator('[data-key="call_1"]')).to_have_value('10:15 AM')
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)

    call_two = first.locator('.field-call2 [data-time-trigger="call_2"]')
    if viewport[0] <= 900:
        cell=first.locator('.field-call2').bounding_box()
        target=call_two.bounding_box()
        assert cell and target
        assert abs(cell['x'] - target['x']) <= 2
        assert abs(cell['y'] - target['y']) <= 2
    call_two.click()
    popup = visible_popup('#timeDialog[open]')
    popup.locator('#timeHour').select_option('1')
    popup.locator('#timeMinute').select_option('27')
    popup.locator('#timePeriod').select_option('PM')
    popup.locator('#timeApply').click()
    expect(first.locator('[data-key="call_2"]')).to_have_value('1:27 PM')
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)

    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    saved = service.repository.sheets(service.day())[0]['draft']
    assert saved['dnr_reason'] == 'Roofing'
    assert saved['sale_products'] == {
        'Roofing': {'price':'17000', 'deposit':'0', 'payment':'135'},
    }
    assert saved['cxl_at_lead'] is True
    assert saved['call_1'] == '10:15 AM'
    assert saved['call_2'] == '1:27 PM'
    assert saved['product_results']['Roofing']['result'] == 'np'
    assert not writer.applied
    evidence('editor-dialogs-' + str(viewport[0]))


def test_opening_another_sheet_dialog_closes_the_previous(mod_browser):
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    first, second = page.locator('.mod-sheet').all()
    first.locator('[data-key="dnr"]').check()
    expect(first.locator('.dnr-panel')).to_be_visible()
    # Background sheets cannot be clicked while a modal is open. Simulate a
    # second change event to assert that even programmatic open paths cannot
    # stack dialogs across multiple appointments.
    second.locator('[data-key="dnr"]').evaluate("""el => {
        el.checked = true;
        el.dispatchEvent(new Event('change', {bubbles:true}));
    }""")
    expect(page.locator('.editor-dialog[open]')).to_have_count(1)
    expect(first.locator('.dnr-panel')).to_be_hidden()
    expect(second.locator('.dnr-panel')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)


def test_existing_split_notes_are_preserved_when_migrated_to_one_textbox(mod_browser):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import clean_draft

    page, service, writer, origin, evidence = mod_browser
    day = service.day()
    ident = service.repository.sheets(day)[0]['work_order_id']
    service.save(day, ident, clean_draft({
        'dispo':'pns', 'notes':'Legacy first note',
        'redlines':'Legacy second note',
    }), 0)
    page.goto(origin + '/mod-resulting')
    note = page.locator('.mod-sheet').first.locator('[data-key=notes]')
    expect(note).to_have_value('Legacy first note\nLegacy second note')
    assert page.locator('.mod-sheet').first.locator('.notes-text textarea').count() == 1
    note.fill('Legacy first note\nLegacy second note\nAdditional note')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    saved = service.repository.sheets(day)[0]['draft']
    assert saved['notes'] == 'Legacy first note\nLegacy second note\nAdditional note'
    assert saved['redlines'] == ''
    assert saved['dispo'] == 'pns'
    assert not writer.applied


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_price_overrides_stay_in_original_sheet_cells(mod_browser, viewport):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import outcome_fields

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':viewport[0], 'height':viewport[1]})
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    expect(first.locator('.mobile-call-actions,.edit-lead-status,.lead-panel')).to_have_count(0)
    first.locator('[data-key="numbers"]').fill('25000\n17000')
    first.locator('[data-key="dispo"]').select_option('pns')

    for field in ('startprice', 'finalprice', 'depositpayment'):
        trigger = first.locator('.field-' + field + ' [data-price-trigger]')
        expect(trigger).to_be_visible()
        trigger.click()
        popup = first.locator('.price-panel')
        expect(popup).to_be_visible()
        popup.locator('[data-key="start_price_override"]').fill('27000')
        popup.locator('[data-key="final_price_override"]').fill('16000')
        popup.locator('[data-combined-amount]').fill('2500 / 120')
        expect(first.locator('[data-price-display="start_price_override"]')).to_have_text('$27000')
        expect(first.locator('[data-price-display="final_price_override"]')).to_have_text('$16000')
        expect(first.locator('[data-price-display="deposit_override"]')).to_have_text('2500 / 120')
        popup.locator('.editor-primary').click()
        expect(popup).to_be_hidden()

    for key in ('docs','review','ninety_min'):
        first.locator('[data-key="' + key + '"]').check()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    saved = service.repository.sheets(service.day())[0]['draft']
    assert saved['start_price_override'] == '27000'
    assert saved['final_price_override'] == '16000'
    assert saved['deposit_override'] == '2500'
    assert saved['payment_override'] == '120'
    assert outcome_fields(saved)['lead_status'] == 'Nurturing'
    assert all(saved[key] for key in ('docs','review','ninety_min'))
    assert not writer.applied
    assert page.evaluate('window.modCspViolations') == []


def test_dnr_automatically_overrides_dispo_status_without_lead_editor(mod_browser):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import outcome_fields

    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    expect(first.locator('.lead-panel,.edit-lead-status,[data-lead-trigger]')).to_have_count(0)
    first.locator('[data-key=dispo]').select_option('pns')
    first.locator('[data-key=dnr]').check()
    dnr = first.locator('.dnr-panel')
    dnr.locator('[data-reason-choice][value="Roofing"]').check()
    dnr.locator('.editor-primary').click()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    draft = service.repository.sheets(service.day())[0]['draft']
    assert outcome_fields(draft)['lead_status'] == 'Do Not Call'
    assert draft['dnr'] is True and draft['dnr_reason'] == 'Roofing'

    first.locator('[data-key=dnr]').uncheck()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    draft = service.repository.sheets(service.day())[0]['draft']
    assert outcome_fields(draft)['lead_status'] == 'Nurturing'
    assert draft['dnr'] is False
    assert not writer.applied



def test_dnr_unchecks_when_dialog_closes_without_a_reason(mod_browser):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import outcome_fields

    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    sheet = page.locator('.mod-sheet').first
    sheet.locator('[data-key=dispo]').select_option('pns')
    sheet.locator('[data-key=dnr]').check()
    popup = sheet.locator('.dnr-panel[open]')
    expect(popup).to_be_visible()
    popup.locator('.editor-primary').click()
    expect(sheet.locator('[data-key=dnr]')).not_to_be_checked()
    expect(sheet.locator('.dnr-in-redline')).to_be_hidden()

    sheet.locator('[data-key=dnr]').check()
    popup = sheet.locator('.dnr-panel[open]')
    popup.locator('[data-reason-choice][value="Roofing"]').check()
    popup.locator('.editor-primary').click()
    expect(sheet.locator('[data-key=dnr]')).to_be_checked()
    expect(sheet.locator('.dnr-in-redline')).to_have_text('DNR - Roofing')

    sheet.locator('.edit-dnr-reasons').click()
    popup = sheet.locator('.dnr-panel[open]')
    popup.locator('[data-reason-choice][value="Roofing"]').uncheck()
    page.keyboard.press('Escape')
    expect(sheet.locator('[data-key=dnr]')).not_to_be_checked()
    expect(sheet.locator('.dnr-in-redline')).to_be_hidden()

    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    saved = service.repository.sheets(service.day())[0]['draft']
    assert saved['dispo'] == 'pns'
    assert saved['dnr'] is False and saved['dnr_reason'] == ''
    assert outcome_fields(saved)['lead_status'] == 'Nurturing'
    assert not writer.applied

def test_refresh_keeps_edits_made_during_an_inflight_save(mod_browser):
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    expect(first).to_have_class('mod-sheet surface-ready')
    held = []

    def hold_first_save(route):
        if not held:
            held.append(route)
            # request events precede route dispatch. A DOM assertion waits for
            # the actual interception without eval-based polling under CSP.
            page.evaluate("() => { document.body.dataset.testSaveHeld = 'yes'; }")
        else:
            route.continue_()

    page.route('**/mod-resulting/api/save', hold_first_save)
    first.locator('[data-key=review]').check()
    first.locator('[data-key=numbers]').fill('0')
    expect(page.locator('body')).to_have_attribute('data-test-save-held', 'yes')
    assert held
    # The first snapshot is still in flight while the user finishes the sheet.
    first.locator('[data-key=review]').uncheck()
    first.locator('[data-key=numbers]').fill('')
    first.locator('[data-key=notes]').fill('Final black comment')
    first.locator('[data-key=call_1]').fill('10:15 AM')
    first.locator('[data-key=call_2]').fill('1:27 PM')
    first.locator('[data-key=dispo]').select_option('cxl')
    first.locator('[data-key=cxl_at_lead]').check()
    first.locator('.cxl-panel .editor-primary').click()
    first.locator('[data-key=notes]').fill('Final black comment\nFINAL REDLINE')
    held[0].continue_()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(first).to_have_class('mod-sheet surface-ready')
    saved = service.repository.sheets(service.day())[0]['draft']
    expected = {'review': False, 'numbers': '', 'notes': 'Final black comment\nFINAL REDLINE',
                'call_1': '10:15 AM',
                'call_2': '1:27 PM', 'dispo': 'cxl', 'cxl_at_lead': True}
    for key, value in expected.items():
        assert saved[key] == value, (key, saved[key])
        control = first.locator('[data-key=' + key + ']')
        if isinstance(value, bool):
            assert control.is_checked() is value
        else:
            expect(control).to_have_value(value)
    evidence('inflight-save-refresh')


def test_real_policy_rejects_an_inline_style_in_a_separate_probe_page(mod_browser):
    """A canary proves the zero-violation checks are not passing with CSP bypassed."""
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    probe = page.context.new_page()
    try:
        response = probe.goto(origin + '/mod-resulting')
        assert "style-src 'self'" in response.headers['content-security-policy']
        expect(probe.locator('.mod-sheet').first).to_have_class('mod-sheet surface-ready')
        probe.evaluate("""() => {
            window.probeViolations = [];
            document.addEventListener('securitypolicyviolation', event => {
                window.probeViolations.push(event.violatedDirective);
                document.body.dataset.probeViolation = event.violatedDirective;
            });
            const forbidden = document.createElement('style');
            forbidden.textContent = '.mod-sheet { display: none !important; }';
            document.head.appendChild(forbidden);
        }""")
        expect(probe.locator('body')).to_have_attribute('data-probe-violation', 'style-src-elem')
        assert probe.evaluate('window.probeViolations') == ['style-src-elem']
        expect(probe.locator('.mod-sheet').first).to_be_visible()
    finally:
        probe.close()


def test_red_pen_controls_manual_ink_independently_of_dispo(mod_browser):
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    first=page.locator('.mod-sheet').first
    notes=first.locator('[data-key=notes]')
    pen=first.locator('.redline-pen')
    expect(pen).to_have_attribute('aria-pressed','false')
    notes.fill('Before disposition')
    first.locator('[data-key=result_detail]').select_option('Price Objection')
    expect(first.locator('.result-detail-in-redline')).to_have_text('Price Objection')
    first.locator('[data-key=dispo]').select_option('pns')
    expect(pen).to_have_attribute('aria-pressed','false')
    notes.fill('Before disposition\nStill a black note')
    expect(first.locator('.mod-notes-display .after-dispo')).to_have_count(0)
    pen.click()
    expect(pen).to_have_attribute('aria-pressed','true')
    notes.fill('Before disposition\nStill a black note\nMANUAL REDLINE')
    expect(first.locator('.mod-notes-display .after-dispo')).to_have_text(
        '\nMANUAL REDLINE')
    first.locator('[data-key=dispo]').select_option('')
    expect(pen).to_have_attribute('aria-pressed','true')
    pen.click()
    notes.fill('Before disposition\nStill a black note\nMANUAL REDLINE\nBack to black')
    expect(first.locator('.mod-notes-display .after-dispo')).to_have_text(
        '\nMANUAL REDLINE')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(page.locator('.redline-pen').first).to_have_attribute('aria-pressed','false')
    expect(page.locator('.mod-notes-display .after-dispo').first).to_have_text(
        '\nMANUAL REDLINE')
    stored=service.repository.sheets(service.day())[0]['draft']
    assert stored['note_runs']==[
        {'text':'Before disposition\nStill a black note','red':False},
        {'text':'\nMANUAL REDLINE','red':True},
        {'text':'\nBack to black','red':False},
    ]
    assert stored['dispo']==''
    assert not writer.applied


def test_sale_combined_amounts_and_popup_footer_do_not_overlap(mod_browser):
    from playwright.sync_api import expect
    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':390,'height':760})
    page.goto(origin + '/mod-resulting')
    sheet=page.locator('.mod-sheet').first
    sheet.locator('[data-key=dispo]').select_option('sale')
    popup=sheet.locator('.sale-panel[open]')
    expect(popup).to_be_visible()

    def verify_layout(dialog):
        header=dialog.locator('.editor-heading').bounding_box()
        body=dialog.locator('.editor-body').bounding_box()
        footer=dialog.locator('.editor-footer').bounding_box()
        frame=dialog.bounding_box()
        assert header and body and footer and frame
        assert body['y']>=header['y']+header['height']-2
        assert footer['y']>=body['y']+body['height']-2
        assert footer['y']+footer['height']<=frame['y']+frame['height']+2

    verify_layout(popup)
    for product,price,deposit,payment in (
        ('Roofing','17000','500','200'),
        ('Windows','23000','300','100'),
    ):
        row=popup.locator('[data-sale-product="'+product+'"]')
        row.locator('[data-sale-selected]').check()
        row.locator('[data-sale-price]').fill(price)
        row.locator('[data-sale-deposit]').fill(deposit)
        row.locator('[data-sale-payment]').fill(payment)
    expect(sheet.locator('[data-price-display="deposit_override"]')).to_have_text('800 / 300')
    popup.locator('.editor-body').evaluate('(el) => el.scrollTop = el.scrollHeight')
    verify_layout(popup)
    popup.locator('.sale-done').click()
    sheet.locator('[data-price-trigger="deposit_override"]').click()
    amounts=sheet.locator('.price-panel[open]')
    expect(amounts.locator('[data-combined-amount]')).to_have_value('800 / 300')
    verify_layout(amounts)
    amounts.locator('[data-combined-amount]').fill('1000 / 375')
    expect(sheet.locator('[data-price-display="deposit_override"]')).to_have_text('1000 / 375')
    amounts.locator('.editor-primary').click()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    draft=service.repository.sheets(service.day())[0]['draft']
    assert draft['deposit_override']=='1000'
    assert draft['payment_override']=='375'
    assert draft['sale_products']['Roofing']['deposit']=='500'
    assert draft['sale_products']['Windows']['deposit']=='300'
    assert draft['sale_products']['Roofing']['payment']=='200'
    assert draft['sale_products']['Windows']['payment']=='100'
    assert not service.allow_salesforce_writes and not writer.applied
