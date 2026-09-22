"""Contact launches require explicit confirmation and reuse shared-note persistence."""
import hashlib
import os
import threading
from urllib.parse import urlsplit

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.tests.auth_helpers import gallery_client, open_gallery


DAY = '2026-09-21'
FIRST_PHONE = '+13605550100'
SECOND_PHONE = '+12065550199'


@pytest.fixture
def web(tmp_path):
    from PIL import Image

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path / 'data', env_file=env,
                            secret_key='s' * 64, email_enabled=False))
    app.testing = True
    service = app.extensions['printer_gallery']
    service.initialize()
    ids, records = {}, []
    for number, (key, name, phone) in enumerate([
        ('first', 'First Customer', '+1 (360) 555-0100'),
        ('second', 'Second Customer', '+1 (206) 555-0199'),
        ('missing', 'No Phone Customer', ''),
    ], 1):
        ident = hashlib.sha256(key.encode()).hexdigest()
        import_id = hashlib.sha256(('contact-' + key).encode()).hexdigest()
        order = f'{number:08}'
        service.repository.enqueue(import_id, 'contact-fixture.pdf')
        service.repository.finish(import_id, [dict(
            id=ident, import_id=import_id, filename='contact-fixture.pdf', page=number, part=1,
            text=f'Work Order Number: {order}\nLead Name: {name}\nAddress: {number} Main Street',
            lead_text='Lead Name: ' + name, document_date=DAY, date_status='printed',
            bytes=100, created=number, recognition_revision=1,
        )])
        Image.new('RGB', (1200, 420), 'white').save(service.files.path('crops', ident))
        records.append(ModSheetRecord(source_id=key, work_order_number=order, lead_name=name,
                                      address=f'{number} Main Street', phone=phone))
        ids[key] = ident
    service.publish_reference_snapshot(DAY, 'final', records, 100)
    return app, service, ids


def assert_no_printing(app):
    db = app.extensions['printer_db']
    for table in ('jobs', 'print_attempts', 'commands', 'print_queue_releases'):
        assert db.rows('SELECT * FROM ' + table) == []


def test_contact_confirmation_uses_csrf_protected_idempotent_shared_notes(web):
    app, service, ids = web
    client = gallery_client(app)
    url = '/gallery/api/items/' + ids['first'] + '/notes'
    with client.session_transaction() as session:
        token = session['csrf']
    form = dict(note_id='c' * 32, author='Office', body='Called ' + FIRST_PHONE + '.')
    assert client.post(url, data=form).status_code == 400
    form['csrf'] = token
    assert client.post(url, data=form, headers={'Origin': 'https://other.example'}).status_code == 403
    assert service.item(ids['first'])['notes'] == []
    for _ in range(2):
        assert client.post(url, data=form).status_code == 200
    notes = service.item(ids['first'])['notes']
    assert len(notes) == 1
    assert notes[0]['author'] == 'Office'
    assert notes[0]['body'] == form['body']
    assert service.item(ids['second'])['notes'] == []
    assert_no_printing(app)


@pytest.fixture(params=['chromium', 'webkit'])
def browser(web, tmp_path, request):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server

    app, service, ids = web
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    origin = f'http://127.0.0.1:{port}'

    def stop_server():
        nonlocal server
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            server = None

    def start_server():
        nonlocal server, thread
        assert server is None
        server = make_server('127.0.0.1', port, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

    try:
        with sync_playwright() as pw:
            context = getattr(pw, request.param).launch_persistent_context(
                str(tmp_path / 'browser-profile'), headless=True,
                viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
            try:
                errors = []
                context.on('page', lambda opened: opened.on('pageerror', lambda error: errors.append(str(error))))
                context.add_init_script("""
                  window.contactLaunches = [];
                  document.addEventListener('click', event => {
                    const link = event.target.closest('a');
                    const href = link?.getAttribute('href') || '';
                    if (/^(tel|sms):/.test(href)) {
                      window.contactLaunches.push({href, trusted:event.isTrusted});
                      // Let the application's target handler run. Cancel only
                      // the native external-app default at the bubbling boundary.
                      event.preventDefault();
                    }
                  });
                """)
                page = context.new_page()
                open_gallery(page, app, origin)
                expect(page.locator('.gallery-card')).to_have_count(3)
                yield page, context, origin, service, ids, stop_server, start_server
                assert not errors
                assert_no_printing(app)
            finally:
                context.close()
    finally:
        stop_server()


def open_card(page, ident, name):
    from playwright.sync_api import expect

    page.locator(f'.gallery-card[data-id="{ident}"]').click()
    expect(page.locator('#galleryViewer')).to_be_visible()
    expect(page.locator('#galleryTitle')).to_have_text(name)


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')
def test_viewer_contact_links_cancel_and_confirm_once_without_removing_feed_search(browser):
    from playwright.sync_api import expect

    page, _, _, service, ids, _, _ = browser
    open_card(page, ids['first'], 'First Customer')
    viewer = page.locator('#galleryViewer')
    expect(viewer.locator('[data-action]')).to_have_count(4)
    expect(viewer.locator('[data-action="search"]')).to_have_count(0)
    expect(page.locator('body > .gallery-dock [data-action="search"]')).to_have_count(1)
    dial = viewer.locator('[data-action="dial"]')
    message = viewer.locator('[data-action="message"]')
    expect(dial).to_have_attribute('href', 'tel:' + FIRST_PHONE)
    expect(message).to_have_attribute('href', 'sms:' + FIRST_PHONE)
    dial.click()
    expect(page.locator('#galleryContactTitle')).to_have_text('Called?')
    expect(page.locator('#galleryContactContext')).to_contain_text('First Customer')
    assert service.item(ids['first'])['notes'] == []
    # Allow the real detail to render while holding the viewer's image decode.
    # This exposes the restoration window after detail's actions() call: a new
    # contact intent here must not skip its history entry and later close the feed.
    page.evaluate("""(id) => {
      const image = document.getElementById('galleryFull');
      const decode = image.decode.bind(image), actualFetch = window.fetch;
      const gate = window.contactRestoreGate = {entered:false, requested:0, consumed:0};
      let release;
      const waiting = new Promise(resolve => {release = resolve;});
      image.decode = () => {
        image.decode = decode;
        gate.entered = true;
        return Promise.all([decode().catch(() => {}), waiting]).then(() => undefined);
      };
      window.fetch = async (input, options) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        const detail = url.pathname === '/gallery/api/items/' + id;
        if (detail) gate.requested++;
        const response = await actualFetch.call(window, input, options);
        if (detail) {
          const json = response.json.bind(response);
          response.json = async () => {
            const data = await json();
            // Signal in the next task, after Gallery renders the real data.
            setTimeout(() => {gate.consumed++;}, 0);
            return data;
          };
        }
        return response;
      };
      window.releaseContactRestore = () => {
        image.decode = decode;
        window.fetch = actualFetch;
        release();
      };
    }""", ids['first'])
    try:
        page.locator('#galleryContactCancel').click()
        page.wait_for_function("""() => window.contactRestoreGate.entered &&
          window.contactRestoreGate.requested > 0 &&
          window.contactRestoreGate.consumed === window.contactRestoreGate.requested""")
        expect(page.locator('#galleryContactSheet')).not_to_be_visible()
        expect(viewer).to_be_visible()
        for link in (dial, message):
            expect(link).to_have_attribute('aria-disabled', 'true')
            assert not link.get_attribute('href')
        dial.click(force=True)
        expect(page.locator('#galleryContactSheet')).not_to_be_visible()
        assert page.evaluate('() => window.contactLaunches') == [
            {'href': 'tel:' + FIRST_PHONE, 'trusted': True},
        ]
    finally:
        page.evaluate('() => window.releaseContactRestore()')
    assert service.item(ids['first'])['notes'] == []

    # Both outcomes are recorded only after the user confirms. Opening the
    # dialer/composer is never treated as a completed customer interaction.
    for action, title, body in [(dial, 'Called?', 'Called'), (message, 'Text sent?', 'Text sent')]:
        before = len(service.item(ids['first'])['notes'])
        action.click()
        expect(page.locator('#galleryContactTitle')).to_have_text(title)
        assert len(service.item(ids['first'])['notes']) == before
        author = page.locator('#galleryContactForm [name="author"]')
        if before:
            expect(author).to_have_value('Office')
        else:
            assert author.evaluate('(input) => input.required')
            page.locator('#galleryContactConfirm').click()
            expect(page.locator('#galleryContactSheet')).to_be_visible()
            assert service.item(ids['first'])['notes'] == []
        author.fill('Office')
        with page.expect_response(lambda response: response.request.method == 'POST'
                                  and urlsplit(response.url).path == '/gallery/api/items/' + ids['first'] + '/notes') as saved:
            page.locator('#galleryContactConfirm').click()
        assert saved.value.status == 200
        expect(page.locator('#galleryContactSheet')).not_to_be_visible(timeout=15000)
        expect(viewer).to_be_visible()
        expect(page.locator('#galleryTitle')).to_have_text('First Customer')
        expect(message).to_have_attribute('href', 'sms:' + FIRST_PHONE)
        notes = service.item(ids['first'])['notes']
        assert len(notes) == before + 1
        assert notes[-1]['author'] == 'Office'
        assert notes[-1]['body'] == body
    assert page.evaluate('() => window.contactLaunches') == [
        {'href': 'tel:' + FIRST_PHONE, 'trusted': True},
        {'href': 'tel:' + FIRST_PHONE, 'trusted': True},
        {'href': 'sms:' + FIRST_PHONE, 'trusted': True},
    ]
    assert service.item(ids['second'])['notes'] == []
    assert len({note['id'] for note in service.item(ids['first'])['notes']}) == 2
    page.locator('[data-close="galleryViewer"]').click()
    open_card(page, ids['missing'], 'No Phone Customer')
    for action in ('dial', 'message'):
        link = page.locator(f'#galleryViewer [data-action="{action}"]')
        expect(link).to_have_attribute('aria-disabled', 'true')
        assert not link.get_attribute('href')


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')
def test_offline_contact_intent_and_confirmed_note_survive_reload_and_sync_to_original_card(browser):
    from playwright.sync_api import expect

    page, context, origin, service, ids, stop_server, start_server = browser
    page.locator('#galleryMenuButton').click()
    expect(page.locator('#galleryOfflineStatus')).to_contain_text('Offline ready · 3 cards', timeout=20000)
    page.wait_for_function('() => Boolean(navigator.serviceWorker.controller)')
    page.locator('[data-close="galleryMenuSheet"]').click()
    # Keep the browser online while the real Pi-equivalent origin disappears.
    # WebKit's offline emulation can reject navigation before its service worker.
    stop_server()
    open_card(page, ids['second'], 'Second Customer')
    message = page.locator('#galleryViewer [data-action="message"]')
    expect(message).to_have_attribute('href', 'sms:' + SECOND_PHONE)
    message.click()
    expect(page.locator('#galleryContactTitle')).to_have_text('Text sent?')
    assert page.evaluate('() => window.contactLaunches') == [
        {'href': 'sms:' + SECOND_PHONE, 'trusted': True},
    ]
    assert all(service.item(ident)['notes'] == [] for ident in ids.values())
    page.locator('#galleryContactForm [name="author"]').fill('Offline reviewer')

    # Reload the same tab while still offline: the pending action must remain
    # pinned to the second customer, even though another card heads the feed.
    assert page.reload().status == 200
    expect(page.locator('#galleryContactSheet')).to_be_visible(timeout=15000)
    expect(page.locator('#galleryContactTitle')).to_have_text('Text sent?')
    expect(page.locator('#galleryContactContext')).to_contain_text('Second Customer')
    expect(page.locator('#galleryContactForm [name="author"]')).to_have_value('Offline reviewer')
    page.locator('#galleryContactConfirm').click()
    expect(page.locator('#galleryContactSheet')).not_to_be_visible(timeout=15000)
    expect(page.locator('#galleryNotes')).to_contain_text('Text sent')
    assert all(service.item(ident)['notes'] == [] for ident in ids.values())
    # The intent was restored in the same tab above. After confirmation, use a
    # fresh tab to verify durable notes without restoring the old viewer history.
    page.close()
    page = context.new_page()
    assert page.goto(origin + '/gallery/').status == 200
    expect(page.locator('.gallery-card')).to_have_count(3)
    open_card(page, ids['second'], 'Second Customer')
    expect(page.locator('#galleryNotes')).to_contain_text('Text sent')
    expect(page.locator('#galleryNotes')).to_contain_text('Offline reviewer')

    page.close()
    start_server()
    page = context.new_page()
    with page.expect_response(lambda response: response.request.method == 'POST'
                              and urlsplit(response.url).path == '/gallery/api/items/' + ids['second'] + '/notes') as synced:
        assert page.goto(origin + '/gallery/').status == 200
    assert synced.value.status == 200
    expect(page.locator('#galleryOfflineStatus')).to_contain_text('Offline ready · 3 cards', timeout=20000)
    notes = service.item(ids['second'])['notes']
    assert len(notes) == 1
    assert notes[0]['author'] == 'Offline reviewer'
    assert notes[0]['body'] == 'Text sent'
    assert service.item(ids['first'])['notes'] == []
    page.reload()
    expect(page.locator('#galleryOfflineStatus')).to_contain_text('Offline ready · 3 cards', timeout=20000)
    assert service.item(ids['second'])['notes'] == notes
