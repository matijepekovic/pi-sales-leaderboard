"""Presentation-only zoom cannot change draft data or lift the write guard."""
from pathlib import Path


def test_dialog_viewport_owns_only_presentation_and_keeps_native_pinch():
    root = Path(__file__).parents[1]
    js = (root / 'static/mod_resulting/dialog_viewport.js').read_text()
    html = (root / 'templates/mod_resulting.html').read_text()
    css = (root / 'static/mod_resulting/dialog_viewport.css').read_text()
    assert 'dialog_viewport.js' in html
    assert 'dialog_viewport.css' in html
    assert "'mod_resulting/viewport.js'" not in html
    assert 'id="sheetZoom"' not in html
    assert 'data-zoom=' not in html
    assert 'visualViewport' in js and 'resize' in js and 'scroll' in js
    assert 'mod-dialog-open' in js
    assert 'mod-dialog-opening' in js
    assert 'initial-scale=1.001' in js
    assert "sheets.dataset.zoom = '1'" in js
    assert 'mod-dialog-opening' in (root / 'static/mod_resulting/sheet.js').read_text()
    assert '.editor-dialog[open]' in css
    for forbidden in ('fetch(', 'XMLHttpRequest', '/api/', 'data-key',
                      'preventDefault(', 'localStorage', 'sessionStorage',
                      'document.createElement'):
        assert forbidden not in js
    for forbidden in ('user-scalable=no', 'maximum-scale=1'):
        assert forbidden not in html
    assert 'style=' not in html and '<style' not in html
    assert 'disabled title="Salesforce writes disabled for sandbox testing"' in html
    sheet_js = (root / 'static/mod_resulting/sheet.js').read_text()
    assert 'class="red-pen"' in html
    assert 'aria-label="Redlines"' in html
    assert 'openDialog(redlineDialog' in sheet_js
    assert 'draft.note_runs = []' in sheet_js
    assert 'data-key="redlines"' in html
    assert 'redInk' not in sheet_js and 'syncNoteMode' not in sheet_js
    assert 'Total Deposit' not in html
    assert '<label>Deposit/Payment' in html
    assert 'inputmode="text" data-key="deposit_override"' in html
    assert 'Optional deposit override' not in html
    assert 'function numericExtremes(' in sheet_js
    assert 'input.placeholder = calculated[key]' in sheet_js
    assert 'data-clear="{{ url_for(\'mod_resulting.clear_local\') }}"' in html
    assert 'id="clearLocal"' in html
    assert 'id="clearConfirm"' in html
    assert "await post(root.dataset.clear);" in sheet_js
    assert 'async function flushAll()' in sheet_js
    for popup in ('endConfirm', 'endMethod', 'endSelect'):
        assert 'id="' + popup + '"' in html
    assert "selectedWorkOrders()" in sheet_js
    assert 'work_order_ids:JSON.stringify(selected)' in sheet_js


def test_pending_setup_notice_is_not_presented_as_a_page_banner():
    root = Path(__file__).parents[1]
    web = (root / 'mod_resulting/web.py').read_text()
    js = (root / 'static/mod_resulting/sheet.js').read_text()
    assert 'draft choices are unverified' not in web
    assert 'current_app.logger.warning' in web
    assert 'PREVIEW ONLY' not in js
    assert "message('Not saved: ' + error.message, sheet)" in js
    html = (root / 'templates/mod_resulting.html').read_text()
    css = (root / 'static/mod_resulting/sheet.css').read_text()
    assert 'MOD for today:' not in js
    assert '<span id="notice"' in html
    assert '.notification{position:static;' in css
    assert '#fffbdf' not in css


def test_phone_scaling_does_not_override_print_layout():
    root = Path(__file__).parents[1]
    css = (root / 'static/mod_resulting/sheet.css').read_text()
    assert '@media screen and (max-width:900px)' in css
    assert '@media print{.floating-controls,' in css
    assert '.sheet-zoom' not in css and '[data-zoom' not in css
    assert '.notes-content>.red-pen{position:absolute;left:' in css
    assert 'width:clamp(16px,1.55cqw,21px)' in css
    assert '.notes-text .sale-in-redline[data-sale-fit="7"]' in css
    assert 'overflow-wrap:anywhere' in css
