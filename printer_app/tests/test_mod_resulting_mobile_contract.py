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

def test_popup_footer_and_red_pen_have_one_ui_owner():
    root=Path(__file__).parents[1]
    css=(root/'static/mod_resulting/sheet.css').read_text()
    js=(root/'static/mod_resulting/sheet.js').read_text()
    html=(root/'templates/mod_resulting.html').read_text()
    assert '.editor-dialog[open]{display:flex;flex-direction:column;overflow:hidden}' in css
    assert '.editor-dialog .editor-body{min-height:0;flex:0 1 auto;overflow-y:auto;' in css
    assert '.editor-dialog .editor-footer{position:relative;' in css
    assert 'data-combined-amount' in html and 'Deposit/Payment' in html
    assert 'Total Deposit' not in html
    assert 'class="redline-pen"' in html
    assert 'sheet._redPenActive = !sheet._redPenActive' in js
    assert 'sheet._noteRuns, input.value, sheet._redPenActive' in js
    assert js.count('function syncNoteMode()') == 1
