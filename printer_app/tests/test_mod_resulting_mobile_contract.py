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
    sheet_js = (root / 'static/mod_resulting/sheet.js').read_text()
    sheet_css = (root / 'static/mod_resulting/sheet.css').read_text()
    assert 'mod-dialog-opening' in sheet_js
    assert 'function depositPaymentSummary(draft)' in sheet_js
    assert "sheet._redInk ? 'red' : 'black'" in sheet_js
    assert "value ? 'red' : 'black'" not in sheet_js
    assert 'redline-pen' in html
    assert 'aria-pressed="false"' in html
    assert 'Total Deposit' not in html
    assert '.editor-dialog[open]{display:flex;flex-direction:column;overflow:hidden}' in sheet_css
    assert '.editor-dialog .editor-body{flex:1 1 auto;min-height:0;overflow-y:auto' in sheet_css
    assert '.editor-dialog[open]' in css
    for forbidden in ('fetch(', 'XMLHttpRequest', '/api/', 'data-key',
                      'preventDefault(', 'localStorage', 'sessionStorage',
                      'document.createElement'):
        assert forbidden not in js
    for forbidden in ('user-scalable=no', 'maximum-scale=1'):
        assert forbidden not in html
    assert 'style=' not in html and '<style' not in html
    assert 'disabled title="Salesforce writes disabled for sandbox testing"' in html


def test_pending_setup_notice_is_not_presented_as_a_page_banner():
    root = Path(__file__).parents[1]
    web = (root / 'mod_resulting/web.py').read_text()
    js = (root / 'static/mod_resulting/sheet.js').read_text()
    assert 'draft choices are unverified' not in web
    assert 'current_app.logger.warning' in web
    assert 'PREVIEW ONLY' not in js
    assert "message('Not saved: ' + error.message, sheet)" in js


def test_phone_scaling_does_not_override_print_layout():
    root = Path(__file__).parents[1]
    css = (root / 'static/mod_resulting/sheet.css').read_text()
    assert '@media screen and (max-width:900px)' in css
    assert '@media print{.floating-controls,' in css
    assert '.sheet-zoom' not in css and '[data-zoom' not in css
