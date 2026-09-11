"""Real form submissions must work without weakening the printer-only web boundary."""
from __future__ import annotations

import os
import threading

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.settings import SettingsService
from printer_app.settings_repository import SettingsRepository


@pytest.fixture
def web(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    env = tmp_path / 'config' / 'env'
    env.parent.mkdir()
    env.write_text('EMAIL_ENABLED=0\nEMAIL_MAILBOX=INBOX\n')
    cfg = Config(data_dir=data, env_file=env, secret_key='s' * 64, email_enabled=False)
    probes = []
    def probe(config):
        probes.append(config.email_user)
        return True, 'Connection test passed.'
    service = SettingsService(SettingsRepository(env), cfg, probe)
    app = create_app(cfg, service)
    app.testing = True
    return app, cfg, env, probes


def form(app, client, origin):
    response = client.get('/settings', base_url=origin)
    assert response.status_code == 200
    # no-referrer makes browsers send Origin: null on native POST navigation.
    assert response.headers['Referrer-Policy'] == 'same-origin'
    current, revision = app.extensions['printer_settings'].read()
    with client.session_transaction(base_url=origin) as session:
        csrf = session['csrf']
    return dict(app.extensions['printer_settings'].public_values(current),
                csrf=csrf, revision=revision, PRINT_PAPER='tabloid', PRINT_COPIES='2')


def test_normal_lan_form_save_persists_without_login(web):
    app, cfg, env, _ = web
    origin = 'http://10.40.80.254:5055'
    client = app.test_client()
    response = client.post('/settings', base_url=origin, data=form(app, client, origin),
                           headers={'Origin': origin})
    assert response.status_code == 303
    # A new service instance must read the disk settings, not a session-only copy.
    current, _ = SettingsService(SettingsRepository(env), cfg).read()
    assert current.print_options.paper == 'tabloid'
    assert current.print_options.copies == 2
    assert not current.email_enabled
    assert env.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('headers', [
    {'Origin': 'null'},
    {'Origin': 'http://evil.example'},
    {'Origin': 'http://10.40.80.254:8765'},
    {'Origin': 'https://10.40.80.254:5055'},
    {'Origin': 'http://10.40.80.254:5055.evil.example'},
    {'Sec-Fetch-Site': 'cross-site'},
    {'Origin': 'http://10.40.80.254:5055', 'Sec-Fetch-Site': 'cross-site'},
])
def test_cross_origin_saves_stay_forbidden_even_with_valid_csrf(web, headers):
    app, _, env, _ = web
    origin = 'http://10.40.80.254:5055'
    client = app.test_client()
    values = form(app, client, origin)
    before = env.read_bytes()
    assert client.post('/settings', base_url=origin, data=values, headers=headers).status_code == 403
    assert env.read_bytes() == before


@pytest.mark.parametrize('csrf', [None, '', 'invalid'])
def test_same_origin_is_not_a_substitute_for_csrf(web, csrf):
    app, _, env, _ = web
    origin = 'http://10.40.80.254:5055'
    client = app.test_client()
    values = form(app, client, origin)
    values.pop('csrf')
    if csrf is not None:
        values['csrf'] = csrf
    before = env.read_bytes()
    response = client.post('/settings', base_url=origin, data=values, headers={'Origin': origin})
    assert response.status_code == 400
    assert env.read_bytes() == before


def test_read_only_navigation_is_not_blocked_as_a_cross_site_write(web):
    app, _, _, _ = web
    response = app.test_client().get('/settings', headers={'Sec-Fetch-Site': 'cross-site'})
    assert response.status_code == 200


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1',
                    reason='Enable the CI Chromium browser regression environment')
@pytest.mark.parametrize('javascript', [False, True])
def test_native_browser_save_and_controls(web, javascript):
    # Do not replace this with client.post or fetch: native form navigation is
    # exactly where the browser applies Referrer-Policy to the Origin header.
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    app, cfg, env, probes = web
    observed = []
    def application(environ, start_response):
        if environ['REQUEST_METHOD'] == 'POST':
            observed.append((environ['PATH_INFO'], environ.get('HTTP_ORIGIN')))
        return app(environ, start_response)
    server = make_server('127.0.0.1', 0, application, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # printer.test is deliberately not a secure localhost context, like a Pi
    # reached by its HTTP LAN address. Resolution stays inside this CI machine.
    origin = f'http://printer.test:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True,
                args=['--no-proxy-server', '--host-resolver-rules=MAP printer.test 127.0.0.1'])
            context = browser.new_context(java_script_enabled=javascript)
            page = context.new_page()
            assert page.goto(origin + '/settings').status == 200
            page.locator('[name="PRINT_PAPER"]').select_option('tabloid')
            page.locator('[name="PRINT_ORIENTATION"]').select_option('landscape')
            page.locator('[name="PRINT_COPIES"]').fill('2')
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url == origin + '/settings') as saved:
                page.get_by_role('button', name='Save Settings', exact=True).click()
            assert saved.value.status == 303
            page.wait_for_url(origin + '/settings?saved=1')
            assert page.locator('[name="PRINT_PAPER"]').input_value() == 'tabloid'
            assert ('/settings', origin) in observed
            current, _ = SettingsService(SettingsRepository(env), cfg).read()
            assert current.print_options.copies == 2
            assert current.print_options.orientation == 'landscape'
            assert not current.email_enabled

            if javascript:
                # The JS probe is a different browser request path. No real Gmail
                # is contacted; only the injected email boundary is substituted.
                before = env.read_bytes()
                page.locator('[name="EMAIL_USER"]').fill('fixture@example.test')
                page.locator('[name="EMAIL_APP_PASSWORD"]').fill('fixture-password')
                with page.expect_response(lambda r: r.url.endswith('/settings/test-email')) as tested:
                    page.get_by_role('button', name='Test Gmail', exact=True).click()
                assert tested.value.status == 200
                assert probes == ['fixture@example.test']
                assert env.read_bytes() == before

            page.goto(origin + '/system/print-control')
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/control/pause')) as paused:
                page.locator('form[action="/control/pause"] button').click()
            assert paused.value.status == 302
            assert app.extensions['printer_db'].get('paused') is True
            assert ('/control/pause', origin) in observed
            assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
