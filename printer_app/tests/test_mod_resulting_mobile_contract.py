"""Presentation-only zoom cannot change draft data or lift the write guard."""
from pathlib import Path


def test_dialog_viewport_owns_only_presentation_and_keeps_native_pinch():
    root = Path(__file__).parents[1]
    js = (root / 'static/mod_resulting/dialog_viewport.js').read_text()
    html = (root / 'templates/mod_resulting.html').read_text()
    css = (root / 'static/mod_resulting/dialog_viewport.css').read_text()
    assert 'dialog_viewport.js' in html
    assert 'dialog_viewport.css' in html
    assert 'viewport.js' not in html
    assert 'id="sheetZoom"' not in html
    assert 'data-zoom=' not in html
    assert 'visualViewport' in js and 'resize' in js and 'scroll' in js
    assert 'mod-dialog-open' in js
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
