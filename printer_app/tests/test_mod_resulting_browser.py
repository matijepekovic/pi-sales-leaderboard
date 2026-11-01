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


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_saved_product_colors_keep_multiselect_controls_in_same_sheet_cells(mod_browser, viewport):
    from playwright.sync_api import expect
    from printer_app.mod_sheets.policy import ModSheetAutomationSettings
    from printer_app.mod_sheets.repository import ModSheetAutomationRepository

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
    assert page.goto(origin + '/mod-resulting').status == 200
    field = page.locator('.mod-sheet').first.locator('.field-product')
    assert field.count() == 1
    expect(field).not_to_have_class('cell field-product replacement color-coded-product')
    original = field.locator('.separate-products').bounding_box()
    expect(field.locator('.product-summary')).to_be_visible()

    settings = ModSheetAutomationRepository(service.repository.db)
    settings.save_settings(ModSheetAutomationSettings(
        market_segment='Olympia', color_code=True
    ))
    page.reload(wait_until='domcontentloaded')
    field = page.locator('.mod-sheet').first.locator('.field-product')
    expect(field).to_have_class('cell field-product replacement color-coded-product')
    assert field.evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgba(0, 0, 0, 0)'
    assert field.locator('.product-summary').evaluate(
        '(el) => getComputedStyle(el).visibility'
    ) == 'hidden'
    updated = field.locator('.separate-products').bounding_box()
    assert abs(original['x'] - updated['x']) < 1
    assert abs(original['y'] - updated['y']) < 1
    expect(field.locator('[data-key=additional_products]')).to_be_enabled()
    field.locator('[data-key=additional_products]').check()
    expect(field.locator('.product-panel')).to_be_visible()
    field.locator('.product-panel .editor-primary').click()
    assert not writer.applied


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_long_press_reads_completed_checkmarks_and_edits_unresulted_source_values(mod_browser, viewport):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import clean_draft

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':viewport[0], 'height':viewport[1]})
    records = service.source.records_data
    writer.checkbox_fields = lambda: {
        'docs': {'kind':'string','editable':True,'nullable':True,
                 'length':100,'choices':[]},
        'ninety_min': {'kind':'picklist','editable':True,'nullable':True,
                       'length':100,'choices':[
                           {'label':'No','value':'No'},
                           {'label':'Scheduled','value':'Scheduled'},
                       ]},
        'promotion': {'kind':'boolean','editable':True,'nullable':False,
                      'length':1,'choices':[]},
    }
    remote = {
        records[0].source_id: clean_draft({
            'dispo':'pns', 'docs':True,
            'checkbox_values': {
                'docs':{'value':'Signed in Salesforce','edited':False},
            },
        }),
        records[1].source_id: clean_draft({
            'docs':True, 'ninety_min':False,
            'checkbox_values': {
                'docs':{'value':'Waiting for docs','edited':False},
                'ninety_min':{'value':'No','edited':False},
            },
        }),
    }
    writer.read_results = lambda records: remote
    service.refresh(service.day())
    page.goto(origin + '/mod-resulting')
    done = page.locator('.mod-sheet').first
    waiting = page.locator('.mod-sheet').nth(1)

    def hold(label):
        label.scroll_into_view_if_needed()
        bounds = label.bounding_box()
        assert bounds is not None
        page.mouse.move(bounds['x'] + bounds['width'] / 2,
                        bounds['y'] + bounds['height'] / 2)
        page.mouse.down()
        page.wait_for_timeout(720)
        page.mouse.up()

    expect(done.locator('[data-key=docs]')).to_be_disabled()
    expect(done.locator('[data-key=docs]')).to_be_checked()
    hold(done.locator('.field-docs label'))
    popup = page.locator('#checkboxDialog')
    expect(popup).to_be_visible()
    expect(popup.locator('#checkboxCurrent')).to_have_text('Signed in Salesforce')
    expect(popup.locator('#checkboxApply')).to_be_hidden()
    expect(popup.locator('.editor-heading,.editor-close,#checkboxReadOnly')).to_have_count(0)
    expect(popup.locator('button:visible')).to_have_count(1)
    expect(popup.locator('button:visible')).to_have_text('Close')
    assert [line.strip() for line in popup.inner_text().splitlines() if line.strip()] == [
        'Signed in Salesforce', 'Close'
    ]
    assert popup.bounding_box()['height'] < 160
    assert popup.bounding_box()['width'] < 340
    popup.locator('.editor-secondary').click()
    expect(done.locator('[data-key=docs]')).to_be_checked()
    assert service.repository.sheets(service.day())[0]['override_active'] == 0

    expect(waiting.locator('[data-key=docs]')).to_be_enabled()
    expect(waiting.locator('[data-key=docs]')).to_be_checked()
    hold(waiting.locator('.field-docs label'))
    expect(popup).to_be_visible()
    expect(popup.locator('#checkboxCurrent')).to_be_hidden()
    expect(popup.locator('#checkboxText')).to_have_value('Waiting for docs')
    expect(popup.locator('.close-popover')).to_have_count(1)
    popup.locator('#checkboxText').fill('Approved by MOD')
    popup.locator('#checkboxApply').click()
    expect(popup).to_be_hidden()
    expect(waiting.locator('[data-key=docs]')).to_be_checked()
    page.wait_for_function("""({key, value}) => {
        const sheet = document.querySelectorAll('.mod-sheet')[1];
        const saved = JSON.parse(sheet.dataset.initial || '{}').checkbox_values?.[key];
        return saved?.value === value && saved.edited === true && sheet.dataset.dirty === 'no';
    }""", arg={'key':'docs','value':'Approved by MOD'}, timeout=8000)
    draft = service.repository.sheets(service.day())[1]['draft']
    assert draft['checkbox_values']['docs'] == {
        'value':'Approved by MOD','edited':True,
    }
    assert draft['dispo'] == ''  # The popup alone never results a Work Order.

    hold(waiting.locator('.field-ninety label').first)
    expect(popup.locator('#checkboxCurrent')).to_be_hidden()
    expect(popup.locator('#checkboxChoice')).to_have_value('No')
    popup.locator('#checkboxChoice').select_option('Scheduled')
    popup.locator('#checkboxApply').click()
    expect(waiting.locator('[data-key=ninety_min]')).to_be_checked()
    page.wait_for_function("""({key, value}) => {
        const sheet = document.querySelectorAll('.mod-sheet')[1];
        const saved = JSON.parse(sheet.dataset.initial || '{}').checkbox_values?.[key];
        return saved?.value === value && saved.edited === true && sheet.dataset.dirty === 'no';
    }""", arg={'key':'ninety_min','value':'Scheduled'}, timeout=8000)
    draft = service.repository.sheets(service.day())[1]['draft']
    assert draft['checkbox_values']['ninety_min'] == {
        'value':'Scheduled','edited':True,
    }

    page.reload(wait_until='domcontentloaded')
    expect(page.locator('.mod-sheet').nth(1).locator('[data-key=docs]')).to_be_checked()
    assert writer.applied == []
    evidence('checkbox-long-press')


def test_long_press_textarea_preserves_multiline_source_value_on_phone(mod_browser):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import clean_draft

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':390,'height':844})
    record = service.source.records_data[1]
    writer.checkbox_fields = lambda: {
        'docs': {'kind':'textarea','editable':True,'nullable':True,
                 'length':3000,'choices':[]},
    }
    writer.read_results = lambda rows: {
        r.source_id: (clean_draft({
            'docs':True,
            'checkbox_values': {
                'docs':{'value':'Reviewed\nPending upload','edited':False},
            },
        }) if r.source_id == record.source_id else clean_draft({}))
        for r in rows
    }
    service.refresh(service.day())
    page.goto(origin + '/mod-resulting')
    sheet = page.locator('.mod-sheet').nth(1)
    label = sheet.locator('.field-docs label')
    label.scroll_into_view_if_needed()
    bounds = label.bounding_box()
    page.mouse.move(bounds['x']+bounds['width']/2, bounds['y']+bounds['height']/2)
    page.mouse.down()
    page.wait_for_timeout(720)
    page.mouse.up()
    popup = page.locator('#checkboxDialog')
    expect(popup).to_be_visible()
    expect(popup.locator('#checkboxCurrent')).to_be_hidden()
    expect(popup.locator('#checkboxTextarea')).to_have_value('Reviewed\nPending upload')
    popup.locator('#checkboxTextarea').fill('Reviewed\nApproved\nFiled')
    popup.locator('#checkboxApply').click()
    page.wait_for_function("""() => {
        const sheet = document.querySelectorAll('.mod-sheet')[1];
        const saved = JSON.parse(sheet.dataset.initial || '{}').checkbox_values?.docs;
        return saved?.value === 'Reviewed\\nApproved\\nFiled' &&
            saved.edited === true && sheet.dataset.dirty === 'no';
    }""", timeout=8000)
    draft = service.repository.sheets(service.day())[1]['draft']
    assert draft['docs'] is True
    assert draft['checkbox_values']['docs'] == {
        'value':'Reviewed\nApproved\nFiled', 'edited': True,
    }
    assert writer.applied == []


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_completed_override_button_unlocks_one_sheet_and_refresh_restores_salesforce(mod_browser, viewport):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import clean_draft

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':viewport[0], 'height':viewport[1]})
    day = service.day()
    first_id = service.source.records_data[0].source_id
    authoritative = clean_draft({
        'dispo':'cxl', 'lead_status':'Canceled', 'notes':'Salesforce note'
    })
    writer.read_results = lambda records: {r.source_id:(authoritative if r.source_id == first_id else clean_draft({})) for r in records}
    service.refresh(day)

    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    second = page.locator('.mod-sheet').nth(1)
    expect(first).to_have_attribute('data-submitted','yes')
    expect(first.locator('[data-key=dispo]')).to_be_disabled()
    expect(second.locator('[data-key=dispo]')).to_be_enabled()
    expect(page.locator('.override-sheet')).to_have_count(1)
    override = first.locator('.override-sheet')
    expect(override).to_be_visible()
    expect(override).to_have_text('Override')
    assert override.evaluate('(el) => el.parentElement.classList.contains("field-notes")')
    assert first.evaluate('(el) => getComputedStyle(el).marginTop') == '0px'
    notes = first.locator('.field-notes').bounding_box()
    button = override.bounding_box()
    content = first.locator('.field-notes .notes-content').bounding_box()
    assert 22 <= button['height'] < 36
    assert notes['x'] <= button['x']
    assert notes['y'] + notes['height'] * .5 < button['y']
    assert button['x'] + button['width'] <= notes['x'] + notes['width']
    assert 0 <= notes['x'] + notes['width'] - (button['x'] + button['width']) < 10
    assert button['y'] + button['height'] <= notes['y'] + notes['height']
    assert 0 <= notes['y'] + notes['height'] - (button['y'] + button['height']) < 10
    assert content['y'] + content['height'] <= button['y'] + .6
    initial_notes_bounds = notes

    with page.expect_navigation(wait_until='domcontentloaded'):
        override.click()
    first = page.locator('.mod-sheet').first
    expect(first).to_have_attribute('data-submitted','no')
    expect(first.locator('.override-sheet')).to_have_count(0)
    expect(first.locator('[data-key=dispo]')).to_be_enabled()
    expect(first.locator('[data-key=dispo]')).to_have_value('cxl')
    # Neither Override nor the completed state changes the printed cell.
    restored_notes = first.locator('.field-notes').bounding_box()
    assert all(abs(restored_notes[k] - initial_notes_bounds[k]) < .8
               for k in ('x', 'y', 'width', 'height'))
    expect(second.locator('[data-key=dispo]')).to_be_enabled()
    sheet = service.repository.sheets(day)[0]
    assert sheet['override_active'] == 1
    assert sheet['draft'] == authoritative

    page.locator('#hideCompleted').check()
    # An explicitly overridden CXL is still editable/visible.
    expect(page.locator('.mod-sheet:visible')).to_have_count(2)
    page.locator('#hideCompleted').uncheck()
    first.locator('[data-key=dispo]').select_option('pns')
    first.locator('[data-key=notes]').fill('Local note survives refresh')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    first = page.locator('.mod-sheet').first
    expect(first).to_have_attribute('data-submitted','no')
    expect(first.locator('.override-sheet')).to_have_count(0)
    expect(first.locator('[data-key=dispo]')).to_have_value('pns')
    expect(first.locator('[data-key=notes]')).to_have_value(
        'Local note survives refresh')
    assert service.repository.sheets(day)[0]['override_active'] == 1
    assert writer.applied == []


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
    expect(first.locator('.redlines-panel [data-key=redlines]')).to_have_count(1)

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
    expect(first.locator('.detail-panel')).not_to_be_visible()
    first.locator('.edit-result-detail').click()
    expect(first.locator('.detail-panel')).to_be_visible()
    first.locator('[data-key=cxl_at_lead]').check()
    first.locator('.detail-panel .editor-primary').click()
    expect(first.locator('[data-cxl-indicator]')).to_be_visible()
    expect(first.locator('[data-key=notes]')).to_be_visible()
    expect(first.locator('[data-key=notes]')).to_have_value('Black comment')
    first.locator('.red-pen').click()
    expect(first.locator('.redlines-panel')).to_be_visible()
    first.locator('.redlines-panel [data-key=redlines]').fill('REDLINE')
    first.locator('.redlines-panel .editor-primary').click()
    expect(first.locator('[data-key=notes]')).to_have_value('Black comment')
    expect(first.locator('.manual-redlines')).to_have_text('REDLINE')
    first.locator('[data-key=numbers]').fill('20000\n17000')
    page.locator('#hideCompleted').check()
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#hideCompleted').uncheck()

    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(page.locator('.mod-sheet')).to_have_count(2)
    expect(page.locator('.mod-sheet').first.locator('[data-key=notes]')).to_have_value('Black comment')
    expect(page.locator('.mod-sheet').first.locator('[data-key=redlines]')).to_have_value('REDLINE')
    row = service.repository.sheets(service.day())[0]
    assert row['draft']['dispo'] == 'cxl'  # Remote was unchanged; local edit survives.
    assert row['draft']['cxl_at_lead'] is True

    with page.expect_response('**/mod-resulting/api/mod') as response:
        page.locator('#dailyMod').select_option(MOD)
    assert response.value.ok
    # The MOD choice itself is confirmation; no yellow banner overlays sheets.
    expect(page.locator('#notice')).to_be_hidden()
    assert page.locator('#notice').evaluate(
        "(el) => el.parentElement.classList.contains('floating-controls')")
    assert service.repository.day(service.day())['mod_user_id'] == MOD
    # The read-only remote fixture has no disposition. Enter a new local one
    # before testing End of Day's confirmation dialogs.
    first.locator('[data-key=dispo]').select_option('pns')
    page.locator('#submitDay').click()
    expect(page.locator('#endConfirm')).to_be_visible()
    expect(page.locator('#endMethod')).to_be_hidden()
    page.locator('#cancelEndSecondary').click()
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)
    page.locator('#submitDay').click()
    page.locator('#proceedEnd').click()
    expect(page.locator('#endConfirm')).to_be_hidden()
    expect(page.locator('#endMethod')).to_be_visible()
    expect(page.locator('#reviewCount')).to_contain_text('1 eligible Work Order(s)')
    expect(page.locator('#submitAll')).to_be_disabled()
    page.locator('#chooseSelected').click()
    expect(page.locator('#endMethod')).to_be_hidden()
    expect(page.locator('#endSelect')).to_be_visible()
    expect(page.locator('#endList .end-choice')).to_have_count(1)
    expect(page.locator('#submitSelected')).to_be_disabled()
    page.locator('#endSelect .editor-close').click()
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)
    assert not writer.applied
    evidence('search-and-refresh')


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_clear_button_resets_local_drafts_only_after_confirmation(mod_browser, viewport):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import clean_draft

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':viewport[0],'height':viewport[1]})
    page.goto(origin + '/mod-resulting')
    sheet = page.locator('.mod-sheet').first
    sheet.locator('[data-key=notes]').fill('Local notes to clear')
    sheet.locator('[data-key=numbers]').fill('98765')
    sheet.locator('[data-key=review]').check()
    sheet.locator('[data-key=dispo]').select_option('pns')
    sheet.locator('.red-pen').click()
    popup = sheet.locator('.redlines-panel')
    popup.locator('[data-key=redlines]').fill('Local redline to clear')
    popup.locator('.editor-primary').click()

    clear = page.locator('#clearLocal')
    expect(clear).to_be_visible()
    assert clear.evaluate(
        "(el) => el.previousElementSibling.id") == 'refresh'
    clear.click()
    confirm = page.locator('#clearConfirm')
    expect(confirm).to_be_visible()
    expect(confirm).to_contain_text('Salesforce will not be changed')
    expect(page.locator('.editor-dialog[open]')).to_have_count(1)
    page.locator('#cancelClear').click()
    expect(confirm).to_be_hidden()
    expect(sheet.locator('[data-key=notes]')).to_have_value('Local notes to clear')
    expect(sheet.locator('[data-key=dispo]')).to_have_value('pns')
    clear.click()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#confirmClear').click()
    current = service.repository.sheets(service.day())[0]
    assert current['draft'] == clean_draft({})
    assert current['submitted_at'] is None
    assert current['revision'] > 0
    expect(sheet.locator('[data-key=notes]')).to_have_value('')
    expect(sheet.locator('.manual-redlines')).to_be_hidden()
    expect(sheet.locator('[data-key=dispo]')).to_have_value('')
    assert not writer.applied


def test_clear_discards_local_notes_and_restores_salesforce_without_writes(mod_browser):
    from playwright.sync_api import expect
    from printer_app.mod_resulting.contract import clean_draft

    page, service, writer, origin, evidence = mod_browser
    day = service.day()
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    ident = first.get_attribute('data-id')
    first.locator('[data-key=notes]').fill('Local test gibberish')
    first.locator('[data-key=dispo]').select_option('sale')
    first.locator('.sale-panel .sale-done').click()
    # The next Clear reads the actual Salesforce adapter contract, not the
    # local draft or the previous unsubmitted sheet's user-selected Dispo.
    remote = clean_draft({
        'dispo':'pns',
        'notes':'Verified Salesforce MOD Notes',
        'numbers':'25000\\n17000', 'result_detail':'Price Objection',
    })
    calls = []
    def remote_results(records):
        calls.append(tuple(r.source_id for r in records))
        return {r.source_id: (remote if r.source_id == ident else clean_draft({}))
                for r in records}
    writer.read_results = remote_results

    page.locator('#clearLocal').click()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#confirmClear').click()
    assert calls and ident in calls[0]
    refreshed = service.repository.sheets(day)[0]
    assert refreshed['draft'] == remote
    assert refreshed['submitted_at'] == -1.0
    expect(first.locator('[data-key=notes]')).to_have_value(
        'Verified Salesforce MOD Notes')
    expect(first.locator('[data-key=dispo]')).to_have_value('pns')
    expect(first).to_have_attribute('data-submitted','yes')
    assert not writer.applied


def test_per_card_result_confirmation_and_notification_bell(mod_browser):
    from playwright.sync_api import expect
    from urllib.parse import parse_qs

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':390, 'height':844})
    submitted = []
    state = {'job':None, 'notifications':[]}

    def fake_submit(route):
        fields = parse_qs(route.request.post_data)
        submitted.append(fields)
        job_id = 30 + len(submitted)
        selected_id = json.loads(fields['work_order_ids'][0])[0]
        number = '00011111' if selected_id.endswith('001AAA') else '00022222'
        state['job'] = {
            'id': job_id, 'day': service.day(), 'state': 'queued', 'total':1,
            'submitted':0, 'pending':1, 'processing':0, 'failed':0,
            'items':[{'state':'pending','work_order_number':number,'error':''}],
            'error':'',
        }
        route.fulfill(status=202, json={
            'ok':True, 'job_id':job_id, 'day':service.day(), 'total':1,
        })

    def fake_status(route):
        route.fulfill(status=200, json={
            'ok':True,
            'submission':state['job'],
            'notifications':state['notifications'],
        })

    page.route('**/mod-resulting/api/submit', fake_submit)
    page.route('**/mod-resulting/api/submission-status*', fake_status)
    page.goto(origin + '/mod-resulting')
    page.locator('#dailyMod').select_option(MOD)
    first, second = page.locator('.mod-sheet').all()
    first.locator('[data-key=dispo]').select_option('pns')
    second.locator('[data-key=dispo]').select_option('np')
    first_button = first.locator('.submit-sheet')
    expect(first_button).to_be_visible()
    expect(second.locator('.submit-sheet')).to_be_visible()
    box = first.bounding_box()
    action = first_button.bounding_box()
    assert box and action
    assert box['x'] + box['width'] - (action['x'] + action['width']) < 20
    assert abs(action['y'] - box['y']) < 20

    first_button.click()
    confirm = page.locator('#singleResultConfirm')
    expect(confirm).to_be_visible()
    expect(confirm.locator('.editor-body')).to_contain_text(
        'Are you sure you want to result this Work Order?')
    expect(confirm.locator('#singleResultWorkOrder')).to_have_text('Work Order 00011111')
    page.locator('#singleResultNo').click()
    expect(confirm).to_be_hidden()
    assert submitted == []

    first_button.click()
    page.locator('#singleResultYes').click()
    expect(confirm).to_be_hidden()
    expect(page.locator('#submissionProgress')).to_be_hidden()
    assert len(submitted) == 1
    assert submitted[0]['mode'] == ['selected']
    assert submitted[0]['work_order_ids'] == [
        json.dumps([first.get_attribute('data-id')])
    ]
    assert second.get_attribute('data-submitted') == 'no'

    state['job'] = {
        'id':31, 'day':service.day(), 'state':'completed', 'total':1,
        'submitted':1, 'pending':0, 'processing':0, 'failed':0,
        'items':[{'state':'submitted','work_order_number':'00011111','error':''}],
        'error':'',
    }
    state['notifications'] = [{
        'job_id':31, 'day':service.day(), 'job_state':'completed',
        'created_at':1761920000, 'finished_at':1761920001, 'job_error':'',
        'work_order_id':first.get_attribute('data-id'),
        'work_order_number':'00011111', 'state':'submitted', 'error':'',
    }]
    expect(page.locator('#submissionToast')).to_contain_text(
        'Work Order 00011111 — Submitted', timeout=9000)
    expect(first).to_have_attribute('data-submitted', 'yes')
    expect(first.locator('.override-sheet')).to_be_visible()
    expect(second).to_have_attribute('data-submitted', 'no')
    expect(page.locator('#submissionNotificationBadge')).to_have_text('1')
    page.locator('#viewSubmissionProgress').click()
    expect(page.locator('#submissionProgress')).to_be_visible()
    expect(page.locator('#submissionNotificationList li')).to_have_count(1)
    expect(page.locator('#submissionNotificationList li')).to_contain_text(
        'Work Order 00011111 — Submitted')
    expect(page.locator('#submissionNotificationBadge')).to_be_hidden()
    page.locator('#submissionProgress .close-popover').click()

    second.locator('.submit-sheet').click()
    page.locator('#singleResultYes').click()
    expect(page.locator('#submissionProgress')).to_be_hidden()
    assert len(submitted) == 2
    assert submitted[1]['work_order_ids'] == [
        json.dumps([second.get_attribute('data-id')])
    ]
    state['job'] = {
        'id':32, 'day':service.day(), 'state':'failed', 'total':1,
        'submitted':0, 'pending':0, 'processing':0, 'failed':1,
        'items':[{'state':'uncertain','work_order_number':'00022222',
                  'error':'Validation rule rejected'}],
        'error':'Validation rule rejected',
    }
    state['notifications'].insert(0, {
        'job_id':32, 'day':service.day(), 'job_state':'failed',
        'created_at':1761920002, 'finished_at':1761920003,
        'job_error':'Validation rule rejected',
        'work_order_id':second.get_attribute('data-id'),
        'work_order_number':'00022222', 'state':'uncertain',
        'error':'Validation rule rejected',
    })
    expect(page.locator('#submissionToast')).to_contain_text(
        'Work Order 00022222 — Failed: Validation rule rejected', timeout=9000)
    expect(second).to_have_attribute('data-submitted', 'no')
    expect(page.locator('#submissionNotificationBadge')).to_have_text('1')
    page.locator('#viewSubmissionProgress').click()
    expect(page.locator('#submissionNotificationList li')).to_have_count(2)
    expect(page.locator('#submissionNotificationList li').first).to_contain_text(
        'Work Order 00022222 — Failed')
    expect(page.locator('#submissionNotificationList li').first).to_contain_text(
        'Validation rule rejected')
    assert writer.applied == []
    evidence('per-card-result-bell')


def test_end_of_day_three_popups_submit_only_explicitly_selected_work_order(mod_browser):
    from playwright.sync_api import expect
    from urllib.parse import parse_qs

    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    first, second = page.locator('.mod-sheet').all()
    first.locator('[data-key=dispo]').select_option('pns')
    second.locator('[data-key=dispo]').select_option('np')
    page.locator('#dailyMod').select_option(MOD)

    # Only intercept this one browser request. No Salesforce write is enabled,
    # and the fixture still verifies that no writer ever ran.
    submitted = []
    def fake_submit(route):
        submitted.append(parse_qs(route.request.post_data))
        route.fulfill(status=202, json={'ok':True, 'job_id':1,
                                        'day':service.day(), 'total':1})
    page.route('**/mod-resulting/api/submit', fake_submit)
    page.route('**/mod-resulting/api/submission-status?job_id=1', lambda route:
        route.fulfill(status=200, json={'ok':True, 'submission':{
            'id':1, 'day':service.day(), 'state':'queued', 'total':1,
            'submitted':0, 'pending':1, 'processing':0, 'failed':0,
            'items':[{'state':'pending','work_order_number':'00011111','error':''}],
            'error':''
        }}))

    page.locator('#submitDay').click()
    expect(page.locator('#endConfirm')).to_be_visible()
    expect(page.locator('.editor-dialog[open]')).to_have_count(1)
    page.locator('#cancelEndSecondary').click()
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)
    page.locator('#submitDay').click()
    page.locator('#proceedEnd').click()
    expect(page.locator('#endConfirm')).to_be_hidden()
    expect(page.locator('#endMethod')).to_be_visible()
    expect(page.locator('#endSelect')).to_be_hidden()
    expect(page.locator('.editor-dialog[open]')).to_have_count(1)

    page.locator('#chooseSelected').click()
    expect(page.locator('#endMethod')).to_be_hidden()
    expect(page.locator('#endSelect')).to_be_visible()
    expect(page.locator('#endList .end-choice')).to_have_count(2)
    expect(page.locator('.editor-dialog[open]')).to_have_count(1)
    page.locator('#endSearch').fill('00011111')
    expect(page.locator('#endList .end-choice:visible')).to_have_count(1)
    page.locator('#endSearch').fill('')
    page.locator('#endList .end-choice input[type=checkbox]').first.check()
    # Simulate only the UI opt-in; POST is intercepted and fake writer unused.
    page.evaluate("""() => { document.querySelector('#submitDay').dataset.liveWrites = 'yes'; }""")
    page.locator('#endList .end-choice input[type=checkbox]').first.uncheck()
    page.locator('#endList .end-choice input[type=checkbox]').first.check()
    expect(page.locator('#submitSelected')).to_be_enabled()
    page.locator('#submitSelected').click()
    expect(page.locator('#submissionProgress')).to_be_visible()
    expect(page.locator('#submissionCompleted')).to_have_text('0 / 1')
    assert len(submitted) == 1
    assert submitted[0]['mode'] == ['selected']
    assert submitted[0]['work_order_ids'] == [json.dumps([first.get_attribute('data-id')])]
    assert writer.applied == []


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
    expect(first.locator('.sale-in-redline')).to_have_text(
        'SALE Roofing: $17,850 | Deposit: $0 | Payment: $159')
    # Zero-priced selected products are not treated as sold.
    siding = first.locator('[data-sale-product="Siding"]')
    siding.locator('[data-sale-selected]').check()
    siding.locator('[data-sale-price]').fill('0')
    first.locator('.sale-panel .sale-done').click()
    expect(first.locator('[data-price-display="deposit_override"]')).to_have_text('0/159')
    expect(first.locator('[data-key=notes]')).to_have_value('Black comment above redlines.')
    first.locator('.red-pen').click()
    expect(first.locator('.redlines-panel')).to_be_visible()
    first.locator('.redlines-panel [data-key=redlines]').fill('REPLACE TRIM WITH FULL SCOPE.')
    first.locator('.redlines-panel .editor-primary').click()
    expect(first.locator('[data-key=notes]')).to_have_value('Black comment above redlines.')
    expect(first.locator('.manual-redlines')).to_have_text('REPLACE TRIM WITH FULL SCOPE.')
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
    red = first.locator('.manual-redlines')
    expect(red).to_have_text('REPLACE TRIM WITH FULL SCOPE.')
    expect(first.locator('[data-key=notes]')).to_have_value('Black comment above redlines.')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(first).to_have_class('mod-sheet surface-ready')
    draft = service.repository.sheets(service.day())[0]['draft']
    assert draft['notes'] == 'Black comment above redlines.'
    assert draft['redlines'] == 'REPLACE TRIM WITH FULL SCOPE.'
    assert draft['note_runs'] == []
    assert draft['dnr_reason'] == 'Roofing'
    assert draft['sale_products']['Roofing']['price'] == '17850'
    assert draft['sale_products']['Siding']['price'] == '0'
    assert draft['call_1'] == '10:15 AM'
    assert draft['call_2'] == '10:27 AM'
    assert draft['review'] is True
    assert draft['dispo'] == 'sale'
    assert draft['numbers'] == '25,000\n17,850'
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
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)
    first.locator('.edit-result-detail').click()
    popup = visible_popup('.detail-panel[open]')
    popup.locator('[data-key="cxl_at_lead"]').check()
    expect(first.locator('[data-cxl-indicator]')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)

    first.locator('[data-key="dispo"]').select_option('pns')
    first.locator('[data-key="additional_products"]').check()
    popup = visible_popup('.product-panel[open]')
    popup.locator('[data-product="Roofing"] [data-product-result]').select_option('np')
    popup.locator('.editor-primary').click()
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)

    # The existing Call cells are the gesture targets on every screen.
    expect(first.locator('.mobile-call-actions')).to_have_count(0)
    def hold_call(button):
        cell = button.locator('xpath=..').bounding_box()
        target = button.bounding_box()
        assert cell and target
        assert abs(cell['x'] - target['x']) <= 2
        assert abs(cell['y'] - target['y']) <= 2
        page.mouse.move(target['x'] + target['width']/2,
                        target['y'] + target['height']/2)
        page.mouse.down()
        page.wait_for_timeout(700)
        page.mouse.up()

    call_one = first.locator('.field-call1 [data-time-trigger="call_1"]')
    hold_call(call_one)
    popup = visible_popup('#timeDialog[open]')
    expect(popup.locator('#timeTitle')).to_have_text('Call 1 time')
    popup.locator('#timeHour').select_option('10')
    popup.locator('#timeMinute').select_option('15')
    popup.locator('#timePeriod').select_option('AM')
    popup.locator('#timeApply').click()
    expect(first.locator('[data-key="call_1"]')).to_have_value('10:15 AM')
    expect(page.locator('.editor-dialog[open]')).to_have_count(0)

    call_two = first.locator('.field-call2 [data-time-trigger="call_2"]')
    hold_call(call_two)
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
    # A Refresh with unchanged Salesforce data must retain local editor work.
    assert saved['dnr_reason'] == 'Roofing'
    assert saved['call_1'] == '10:15 AM'
    assert saved['call_2'] == '1:27 PM'
    assert saved['product_results']['Roofing']['result'] == 'np'
    assert saved['dispo'] == 'pns'
    assert not writer.applied
    evidence('editor-dialogs-' + str(viewport[0]))



@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_call_tap_records_local_time_without_picker_and_hold_does_not_overwrite(mod_browser, viewport):
    from datetime import datetime, timezone
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width': viewport[0], 'height': viewport[1]})
    page.goto(origin + '/mod-resulting')
    page.clock.set_fixed_time(datetime(2026, 10, 30, 17, 4, tzinfo=timezone.utc))
    first = page.locator('.mod-sheet').first
    expected = page.evaluate("""() => {
        const now = new Date();
        const hour = now.getHours();
        return (hour % 12 || 12) + ':' +
            String(now.getMinutes()).padStart(2, '0') + ' ' +
            (hour >= 12 ? 'PM' : 'AM');
    }""")
    for key, cell in [('call_1', 'field-call1'), ('call_2', 'field-call2')]:
        first.locator('.' + cell + ' [data-time-trigger]').click()
        expect(first.locator('[data-key="' + key + '"]')).to_have_value(expected)
        expect(page.locator('#timeDialog[open]')).to_have_count(0)

    trigger = first.locator('.field-call1 [data-time-trigger]')
    box = trigger.bounding_box()
    assert box
    page.mouse.move(box['x'] + box['width']/2, box['y'] + box['height']/2)
    page.mouse.down()
    page.wait_for_timeout(700)
    page.mouse.up()
    expect(page.locator('#timeDialog[open]')).to_be_visible()
    expect(first.locator('[data-key="call_1"]')).to_have_value(expected)
    page.locator('#timeClear').click()
    expect(first.locator('[data-key="call_1"]')).to_have_value('')
    expect(page.locator('#timeDialog[open]')).to_have_count(0)

    page.wait_for_timeout(650)
    draft = service.repository.sheets(service.day())[0]['draft']
    assert draft['call_1'] == ''
    assert draft['call_2'] == expected
    assert not writer.applied


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


def test_existing_split_notes_remain_in_separate_redlines_editor(mod_browser):
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
    first = page.locator('.mod-sheet').first
    note = first.locator('[data-key=notes]')
    expect(note).to_have_value('Legacy first note')
    expect(first.locator('.manual-redlines')).to_have_text('Legacy second note')
    assert first.locator('.notes-text textarea').count() == 1
    first.locator('.red-pen').click()
    popup = first.locator('.redlines-panel')
    expect(popup.locator('[data-key=redlines]')).to_have_value('Legacy second note')
    popup.locator('[data-key=redlines]').fill('Legacy second note\nAdditional redline')
    popup.locator('.editor-primary').click()
    note.fill('Legacy first note\nAdditional black note')
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    saved = service.repository.sheets(day)[0]['draft']
    assert saved['notes'] == 'Legacy first note\nAdditional black note'
    assert saved['redlines'] == 'Legacy second note\nAdditional redline'
    assert saved['note_runs'] == []
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
    expect(first.locator('[data-price-display="start_price_override"]')).to_have_text('$25000')
    expect(first.locator('[data-price-display="final_price_override"]')).to_have_text('$17000')

    for field in ('startprice', 'finalprice', 'depositpayment'):
        trigger = first.locator('.field-' + field + ' [data-price-trigger]')
        expect(trigger).to_be_visible()
        trigger.click()
        popup = first.locator('.price-panel')
        expect(popup).to_be_visible()
        expect(popup.locator('[data-key="start_price_override"]')).to_have_attribute('placeholder','25000')
        expect(popup.locator('[data-key="final_price_override"]')).to_have_attribute('placeholder','17000')
        expect(popup.locator('[data-key="deposit_override"]')).to_have_attribute('placeholder','')
        popup.locator('[data-key="start_price_override"]').fill('27000')
        popup.locator('[data-key="final_price_override"]').fill('16000')
        popup.locator('[data-key="deposit_override"]').fill('2500/159.50')
        expect(first.locator('[data-price-display="start_price_override"]')).to_have_text('$27000')
        expect(first.locator('[data-price-display="final_price_override"]')).to_have_text('$16000')
        expect(first.locator('[data-price-display="deposit_override"]')).to_have_text('2500/159.50')
        popup.locator('.editor-primary').click()
        expect(popup).to_be_hidden()

    for key in ('docs','review','ninety_min'):
        first.locator('[data-key="' + key + '"]').check()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    saved = service.repository.sheets(service.day())[0]['draft']
    assert saved['start_price_override'] == '27000'
    assert saved['final_price_override'] == '16000'
    assert saved['deposit_override'] == '2500/159.50'
    assert saved['dispo'] == 'pns'
    assert outcome_fields(saved) is not None
    assert all(saved[key] for key in ('docs','review','ninety_min'))
    assert not writer.applied
    assert page.evaluate('window.modCspViolations') == []


def test_dnr_editor_respects_refresh_from_salesforce(mod_browser):
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
    assert draft['dispo'] == 'pns'
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
    first.locator('.edit-result-detail').click()
    first.locator('[data-key=cxl_at_lead]').check()
    first.locator('.detail-panel .editor-primary').click()
    first.locator('.red-pen').click()
    first.locator('.redlines-panel [data-key=redlines]').fill('FINAL REDLINE')
    first.locator('.redlines-panel .editor-primary').click()
    held[0].continue_()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    expect(first).to_have_class('mod-sheet surface-ready')
    saved = service.repository.sheets(service.day())[0]['draft']
    expected = {'review': False, 'numbers': '', 'notes': 'Final black comment',
                'redlines': 'FINAL REDLINE',
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

def test_red_pen_opens_separate_redlines_popup_and_never_recolors_notes(mod_browser):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    notes = first.locator('[data-key=notes]')
    pen = first.locator('.red-pen')
    notes.fill('Black notes remain black')
    first.locator('.edit-result-detail').click()
    first.locator('[data-key=result_detail]').select_option('Price Objection')
    first.locator('.detail-panel .editor-primary').click()
    expect(first.locator('[data-detail-display]')).to_have_text('Price Objection')
    expect(first.locator('.result-detail-in-redline')).to_have_text('Price Objection')
    first.locator('[data-key=dispo]').select_option('pns')
    expect(notes).to_have_value('Black notes remain black')
    expect(pen).to_be_visible()
    assert pen.evaluate('(el) => el.parentElement.classList.contains("notes-content")')
    pen.click()
    popup = first.locator('.redlines-panel')
    expect(popup).to_be_visible()
    expect(popup.locator('.editor-heading h2')).to_have_text('Redlines')
    expect(page.locator('.editor-dialog[open]')).to_have_count(1)
    popup.locator('[data-key=redlines]').fill('Scope changed')
    popup.locator('.editor-primary').click()
    expect(notes).to_have_value('Black notes remain black')
    expect(first.locator('.manual-redlines')).to_have_text('Scope changed')
    first.locator('[data-key=dispo]').select_option('')
    pen.click()
    expect(popup.locator('[data-key=redlines]')).to_have_value('Scope changed')
    popup.locator('[data-key=redlines]').fill('Scope changed\nNew redline')
    popup.locator('.editor-primary').click()
    with page.expect_navigation(wait_until='domcontentloaded'):
        page.locator('#refresh').click()
    stored = service.repository.sheets(service.day())[0]['draft']
    assert stored['dispo'] == ''
    assert stored['notes'] == 'Black notes remain black'
    assert stored['redlines'] == 'Scope changed\nNew redline'
    assert stored['note_runs'] == []
    assert not writer.applied


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_sale_preview_stays_bottom_anchored_and_wraps_within_notes(mod_browser, viewport):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':viewport[0],'height':viewport[1]})
    page.goto(origin + '/mod-resulting')
    sheet = page.locator('.mod-sheet').first
    sheet.locator('[data-key=dispo]').select_option('sale')
    popup = sheet.locator('.sale-panel')
    for product in ('Roofing', 'Siding', 'Windows'):
        item = popup.locator('[data-sale-product="' + product + '"]')
        item.locator('[data-sale-selected]').check()
        item.locator('[data-sale-price]').fill('123456789.50')
        item.locator('[data-sale-deposit]').fill('123456.75')
        item.locator('[data-sale-payment]').fill('159.50')
    popup.locator('.sale-done').click()
    sale = sheet.locator('.sale-in-redline')
    expect(sale).to_be_visible()
    expect(sale).to_contain_text('SALE Roofing:')
    expect(sale).to_contain_text('SALE Siding:')
    expect(sale).to_contain_text('SALE Windows:')
    assert sale.get_attribute('data-sale-fit') is not None
    area = sheet.locator('.notes-text').bounding_box()
    text = sale.bounding_box()
    assert text['x'] >= area['x'] - 1
    assert text['x'] + text['width'] <= area['x'] + area['width'] + 1
    assert text['y'] >= area['y'] - 1
    assert text['y'] + text['height'] <= area['y'] + area['height'] + 1
    assert sale.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
    # The sale details keep the lower edge, rather than following the first
    # black-note line at the top of the box.
    assert area['y'] + area['height'] - (text['y'] + text['height']) <= 12
    assert not writer.applied


def test_mod_selection_has_no_banner_and_errors_stay_inline(mod_browser):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    notice = page.locator('#notice')
    expect(notice).to_be_hidden()
    assert notice.evaluate(
        "(el) => getComputedStyle(el).position") == 'static'
    assert notice.evaluate(
        "(el) => getComputedStyle(el).backgroundColor") == 'rgba(0, 0, 0, 0)'
    assert notice.evaluate(
        "(el) => el.parentElement.classList.contains('floating-controls')")
    with page.expect_response('**/mod-resulting/api/mod') as response:
        page.locator('#dailyMod').select_option(MOD)
    assert response.value.ok
    expect(notice).to_be_hidden()
    assert not writer.applied


def test_calculated_amount_placeholders_update_and_clear_to_automatic(mod_browser):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.goto(origin + '/mod-resulting')
    sheet = page.locator('.mod-sheet').first
    sheet.locator('[data-key=numbers]').fill('Sale 17000\nStarting price 25000\nAdjustment 21000')
    expect(sheet.locator('[data-price-display=start_price_override]')).to_have_text('$25000')
    expect(sheet.locator('[data-price-display=final_price_override]')).to_have_text('$17000')

    sheet.locator('[data-key=dispo]').select_option('sale')
    sale = sheet.locator('.sale-panel')
    roofing = sale.locator('[data-sale-product="Roofing"]')
    windows = sale.locator('[data-sale-product="Windows"]')
    roofing.locator('[data-sale-selected]').check()
    roofing.locator('[data-sale-price]').fill('18000')
    roofing.locator('[data-sale-deposit]').fill('300')
    roofing.locator('[data-sale-payment]').fill('159.50')
    windows.locator('[data-sale-selected]').check()
    windows.locator('[data-sale-price]').fill('20000')
    windows.locator('[data-sale-deposit]').fill('200')
    windows.locator('[data-sale-payment]').fill('80')
    sale.locator('.sale-done').click()
    expect(sheet.locator('[data-price-display=deposit_override]')).to_have_text('500/239.50')
    sheet.locator('[data-price-trigger=deposit_override]').click()
    popup = sheet.locator('.price-panel')
    expect(popup.locator('[data-key=start_price_override]')).to_have_attribute('placeholder','25000')
    expect(popup.locator('[data-key=final_price_override]')).to_have_attribute('placeholder','17000')
    deposit = popup.locator('[data-key=deposit_override]')
    expect(deposit).to_have_attribute('placeholder','500/239.50')
    deposit.fill('750/250')
    expect(sheet.locator('[data-price-display=deposit_override]')).to_have_text('750/250')
    deposit.fill('')
    expect(sheet.locator('[data-price-display=deposit_override]')).to_have_text('500/239.50')
    popup.locator('.editor-primary').click()
    assert not writer.applied


@pytest.mark.parametrize('viewport', [(1200, 820), (390, 844)])
def test_phase3_primary_is_manual_only_when_individual_and_sale_order_is_saved(mod_browser, viewport):
    from playwright.sync_api import expect

    page, service, writer, origin, evidence = mod_browser
    page.set_viewport_size({'width':viewport[0], 'height':viewport[1]})
    page.goto(origin + '/mod-resulting')
    first = page.locator('.mod-sheet').first
    original = first.bounding_box()
    first.locator('[data-key="dispo"]').select_option('pns')
    expect(first.locator('.edit-product-results')).to_be_visible()
    first.locator('.edit-product-results').click()
    popup = first.locator('.product-panel')
    expect(popup).to_be_visible()
    expect(popup.locator('.primary-product-choice')).to_be_hidden()
    popup.locator('.editor-primary').click()

    # Explicit individual resulting is the only path to a manual primary.
    first.locator('[data-key="additional_products"]').check()
    expect(popup).to_be_visible()
    expect(popup.locator('.primary-product-choice')).to_be_visible()
    popup.locator('[data-primary-selection]').select_option('Siding')
    popup.locator('.editor-primary').click()
    page.wait_for_function("""() => {
        const sheet = document.querySelector('.mod-sheet');
        return JSON.parse(sheet.dataset.initial || '{}').primary_product === 'Siding'
            && sheet.dataset.dirty === 'no';
    }""", timeout=8000)

    # Sale does not expose manual primary selection. The first checked Sold
    # product is persisted independently of the fixed product popup order.
    first.locator('[data-key="dispo"]').select_option('sale')
    sold = first.locator('.sale-panel')
    expect(sold).to_be_visible()
    expect(sold.locator('[data-primary-selection]')).to_have_count(0)
    sold.locator('[data-sale-product="Siding"] [data-sale-selected]').check()
    sold.locator('[data-sale-product="Siding"] [data-sale-price]').fill('17000')
    sold.locator('[data-sale-product="Siding"] [data-sale-deposit]').fill('0')
    sold.locator('[data-sale-product="Roofing"] [data-sale-selected]').check()
    sold.locator('[data-sale-product="Roofing"] [data-sale-price]').fill('10000')
    sold.locator('[data-sale-product="Roofing"] [data-sale-deposit]').fill('0')
    sold.locator('.sale-done').click()
    page.wait_for_function("""() => {
        const sheet = document.querySelector('.mod-sheet');
        const draft = JSON.parse(sheet.dataset.initial || '{}');
        return draft.dispo === 'sale'
            && JSON.stringify(draft.sale_selection_order) === '["Siding","Roofing"]'
            && sheet.dataset.dirty === 'no';
    }""", timeout=8000)
    record = service.repository.sheets(service.day())[0]
    assert record['draft']['sale_selection_order'] == ['Siding', 'Roofing']
    payload = service.submission_payload(
        dict(record, day=service.day()), '005000000000001AAA',
        lead_appointment_date=service.day())
    assert payload['product_result_context']['Siding']['role'] == 'primary'
    assert payload['product_result_context']['Roofing']['role'] == 'additional'
    assert first.bounding_box()['width'] == original['width']
    assert writer.applied == []


def test_pdfs_gate_and_cover_editor_without_salesforce_submission(mod_browser):
    from playwright.sync_api import expect
    page, service, writer, origin, capture = mod_browser
    page.goto(origin + '/mod-resulting')
    button = page.locator('#pdfsButton')
    expect(button).to_be_disabled()

    # The MOD Resulting edits are the source. Submission is not needed.
    dispos = page.locator('.mod-sheet select[data-key="dispo"]')
    assert dispos.count() == 2
    dispos.nth(0).select_option('np')
    expect(button).to_be_disabled()
    dispos.nth(1).select_option('pns')
    expect(button).to_be_enabled()

    button.click()
    popup = page.locator('#pdfChoice')
    expect(popup).to_be_visible()
    expect(popup.locator('#pdfRedlines')).to_be_enabled()
    expect(popup.locator('#pdfCalc')).to_be_disabled()
    popup.locator('#pdfRedlines').click()
    page.wait_for_url('**/mod-resulting/pdfs/cover/*')
    expect(page.locator('h1')).to_have_text('OLY MOD Cover')
    assert page.locator('section.division').count() == 5
    assert page.locator('section.division[data-division="gutters"]').count() == 1
    # Fully editable daily report does not mutate Salesforce or re-submit any
    # MOD card, even if the background worker has not yet processed the PDF.
    page.locator('input[data-total="mod"]').fill('Edited MOD')
    page.locator('#confirmCover').click()
    expect(page.locator('#coverStatus')).to_contain_text('confirmed')
    assert writer.applied == []
    assert service.repository.sheets(service.day())[0]['draft']['dispo'] == 'np'
    assert service.repository.sheets(service.day())[1]['draft']['dispo'] == 'pns'
