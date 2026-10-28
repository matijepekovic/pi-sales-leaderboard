"""Presentation-only zoom cannot change draft data or lift the write guard."""
from pathlib import Path


def test_viewport_owns_only_display_state_and_keeps_native_zoom_available():
    root = Path(__file__).parents[1]
    js = (root / 'static/mod_resulting/viewport.js').read_text()
    html = (root / 'templates/mod_resulting.html').read_text()
    assert 'viewport.js' in html
    assert 'data-zoom="1"' in html
    for forbidden in ('fetch(', 'XMLHttpRequest', '/api/', 'data-key', 'preventDefault(', '.style.'):
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
