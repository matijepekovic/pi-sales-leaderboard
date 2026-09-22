"""Gallery refresh queues normalized reference work without admin access or printing."""
from datetime import datetime
import hashlib
import os
import re
import threading
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.tests.auth_helpers import gallery_client, open_gallery


DAY = '2026-09-21'
OLDER = '2026-09-20'
REFRESH = '/gallery/api/references/refresh'


class ReferenceSource:
    def __init__(self):
        self.calls = []
        self.error = None

    def lead_statuses(self, work_order_numbers):
        return ()

    def records(self, **filters):
        self.calls.append(filters)
        if self.error:
            raise RuntimeError(self.error)
        return (reference('00000001', 'Today Customer', 'Fresh Assigned Rep'),)


def reference(order, name, rep):
    return ModSheetRecord(source_id='source-' + order, work_order_number=order,
                          lead_name=name, address='100 Main Street',
                          assigned_service_resources=(rep,))


def seed_card(service, key, day, order, name, rep):
    from PIL import Image

    ident = hashlib.sha256(key.encode()).hexdigest()
    import_id = hashlib.sha256(('import-' + key).encode()).hexdigest()
    service.repository.enqueue(import_id, 'scanned-cards.pdf')
    service.repository.finish(import_id, [dict(
        id=ident, import_id=import_id, filename='scanned-cards.pdf', page=1, part=1,
        text=f'Work Order Number: {order}\nLead Name: {name}\nAddress: 100 Main Street',
        lead_text='Lead Name: ' + name, document_date=day, date_status='printed',
        bytes=100, created=100, recognition_revision=1,
    )])
    Image.new('RGB', (1200, 420), 'white').save(service.files.path('crops', ident))
    service.publish_reference_snapshot(day, 'final', [reference(order, name, rep)], 100)
    return ident


@pytest.fixture
def web(tmp_path):
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path / 'data', env_file=env,
                            secret_key='s' * 64, email_enabled=False))
    app.testing = True
    gallery = app.extensions['printer_gallery']
    gallery.initialize()
    ids = {
        'today': seed_card(gallery, 'today', DAY, '00000001', 'Today Customer', 'Old Assigned Rep'),
        'older': seed_card(gallery, 'older', OLDER, '00000002', 'Older Customer', 'Fresh Historical Rep'),
    }
    gallery.note(ids['today'], 'a' * 32, 'Office', 'Keep the existing shared note')
    source = ReferenceSource()
    with app.test_request_context():
        delivery = app.extensions['gallery_reference_refresh']()
    delivery.source = source
    delivery.clock = lambda: datetime(2026, 9, 21, 12, tzinfo=ZoneInfo('America/Los_Angeles')).timestamp()
    app.extensions['gallery_reference_refresh'] = lambda: delivery
    return app, gallery, delivery, source, ids


def csrf(client):
    with client.session_transaction() as session:
        return session['csrf']


def assert_no_printing(app):
    db = app.extensions['printer_db']
    for table in ('jobs', 'print_attempts', 'commands', 'print_queue_releases', 'outputs'):
        assert db.rows('SELECT * FROM ' + table) == []


def test_full_gallery_refresh_queues_worker_pull_without_printer_admin_or_printing(web):
    app, gallery, delivery, source, ids = web
    client = gallery_client(app)
    assert client.get('/settings').status_code == 302
    before = gallery.item(ids['today'])
    image = gallery.files.path('crops', ids['today']).read_bytes()

    response = client.post(REFRESH, data={'csrf': csrf(client)}, headers={'Origin': 'http://localhost'})

    assert response.status_code == 202
    assert response.json['status'] == 'queued'
    assert response.json['day'] == DAY
    assert source.calls == []  # HTTP never calls the external source.
    assert client.get(REFRESH).json['status'] == 'queued'
    assert gallery.item(ids['today']) == before
    assert_no_printing(app)

    result = delivery.run_requested()

    assert result['status'] == 'complete'
    assert client.get(REFRESH).json['status'] == 'complete'
    assert source.calls == [dict(start_date=DAY, end_date=DAY, market_segment='',
                                 product_category='', source_type='', remove_canceled=False,
                                 remove_unconfirmed=False, limit=None)]
    after = gallery.item(ids['today'])
    assert after['assigned_service_resource'] == 'Fresh Assigned Rep'
    assert after['notes'] == before['notes']
    assert after['document_date'] == before['document_date']
    assert after['image_revision'] == before['image_revision']
    assert gallery.files.path('crops', ids['today']).read_bytes() == image
    assert gallery.item(ids['older'])['assigned_service_resource'] == 'Fresh Historical Rep'
    results = client.get('/gallery/api/items?q=fresh&field=rep').json
    assert {item['id'] for item in results['items']} == set(ids.values())
    assert_no_printing(app)


@pytest.mark.parametrize('form,headers,expected', [
    ({}, {}, 400),
    ({'csrf': 'invalid'}, {}, 400),
    (None, {'Origin': 'https://other.example'}, 403),
    (None, {'Origin': 'null'}, 403),
])
def test_refresh_preserves_csrf_and_origin_guards(web, form, headers, expected):
    app, _, delivery, source, _ = web
    client = gallery_client(app)
    response = client.post(REFRESH, data=form if form is not None else {'csrf': csrf(client)},
                           headers=headers)
    assert response.status_code == expected
    assert delivery.refresh_status() == {}
    assert source.calls == []
    assert_no_printing(app)


def test_missing_access_and_guest_cannot_request_reference_refresh(web):
    app, _, delivery, source, _ = web
    missing = app.test_client()
    assert missing.get(REFRESH).status_code == 401
    assert missing.post(REFRESH, data={'csrf': csrf(missing)}).status_code == 401
    full = gallery_client(app)
    identity = full.get('/gallery/api/access').json
    invite = app.extensions['gallery_access'].create_guest_share(identity['subject'], 'Guest')
    guest = app.test_client()
    assert guest.get('/gallery/access/' + invite['token'], follow_redirects=True).status_code == 200
    assert guest.get(REFRESH).status_code == 403
    assert guest.post(REFRESH, data={'csrf': csrf(guest)}).status_code == 403
    assert delivery.refresh_status() == {}
    assert source.calls == []
    assert_no_printing(app)


def test_source_failure_keeps_saved_cards_notes_and_images(web):
    app, gallery, delivery, source, ids = web
    source.error = 'Reference source unavailable'
    client = gallery_client(app)
    before = {key: gallery.item(ident) for key, ident in ids.items()}
    images = {key: gallery.files.path('crops', ident).read_bytes() for key, ident in ids.items()}
    assert client.post(REFRESH, data={'csrf': csrf(client)}).status_code == 202

    assert delivery.run_requested()['status'] == 'failed'

    result = client.get(REFRESH)
    assert result.status_code == 200
    assert result.json['status'] == 'failed'
    assert 'unavailable' in result.json['error']
    assert {key: gallery.item(ident) for key, ident in ids.items()} == before
    assert {key: gallery.files.path('crops', ident).read_bytes() for key, ident in ids.items()} == images
    assert_no_printing(app)


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')
@pytest.mark.parametrize('engine', ['chromium', 'webkit'])
def test_menu_refresh_updates_rep_search_and_keeps_failure_visible_without_losing_cards(web, engine):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server

    app, gallery, delivery, source, ids = web
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = getattr(pw, engine).launch()
            try:
                page = browser.new_page(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
                errors, requests = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append(request.url))
                open_gallery(page, app, f'http://127.0.0.1:{server.server_port}')
                expect(page.locator('.gallery-card')).to_have_count(1)
                page.locator('body > .gallery-dock [data-action="search"]').click()
                page.locator('#gallerySearchFields label').filter(has_text='Rep').click()
                page.locator('#query').fill('fresh')
                expect(page.locator('.gallery-card')).to_have_count(1)
                expect(page.locator('.gallery-card')).to_have_attribute('data-id', ids['older'])
                page.locator('#galleryMenuButton').click()
                expect(page.locator('#galleryMenuSheet')).to_be_visible()
                expect(page.locator('#galleryOfflineWrap')).not_to_be_visible()
                with page.expect_response(lambda response: urlsplit(response.url).path == REFRESH
                                          and response.request.method == 'POST') as queued:
                    page.locator('#galleryMenuRefresh').click()
                assert queued.value.status == 202
                expect(page.locator('#galleryRefreshMessage')).to_contain_text(re.compile('waiting|pull', re.I))
                expect(page.locator('#galleryMenuSheet')).to_be_visible()
                assert source.calls == []

                assert delivery.run_requested()['status'] == 'complete'
                expect(page.locator('#galleryRefreshMessage')).to_contain_text(
                    re.compile('updated|complete|refreshed', re.I), timeout=10000)
                expect(page.locator('.gallery-card')).to_have_count(2)
                expect(page.locator('#galleryMenuSheet')).to_be_visible()
                expect(page.locator('#gallerySearchFields input[value="rep"]')).to_be_checked()
                expect(page.locator('#query')).to_have_value('fresh')
                expect(page.locator('.gallery-date-nav')).not_to_be_visible()
                searches = [parse_qs(urlsplit(url).query, keep_blank_values=True) for url in requests
                            if urlsplit(url).path == '/gallery/api/items']
                assert searches[-1]['q'] == ['fresh']
                assert searches[-1]['field'] == ['rep']
                assert searches[-1]['date'] == ['']
                assert gallery.item(ids['today'])['assigned_service_resource'] == 'Fresh Assigned Rep'

                source.error = 'Reference source unavailable'
                with page.expect_response(lambda response: urlsplit(response.url).path == REFRESH
                                          and response.request.method == 'POST') as queued:
                    page.locator('#galleryMenuRefresh').click()
                assert queued.value.status == 202
                assert delivery.run_requested()['status'] == 'failed'
                expect(page.locator('#galleryRefreshMessage')).to_contain_text(
                    re.compile('failed|could not|unavailable', re.I), timeout=10000)
                expect(page.locator('#galleryMenuSheet')).to_be_visible()
                expect(page.locator('.gallery-card')).to_have_count(2)
                assert gallery.item(ids['today'])['assigned_service_resource'] == 'Fresh Assigned Rep'
                assert gallery.item(ids['today'])['notes'][0]['body'] == 'Keep the existing shared note'
                assert_no_printing(app)
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')
@pytest.mark.parametrize('engine', ['chromium', 'webkit'])
def test_fresh_full_device_automatically_caches_resumes_and_syncs_offline_notes(web, engine, tmp_path):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server

    app, gallery, _, source, ids = web
    before = gallery.item(ids['today'])
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            context = getattr(pw, engine).launch_persistent_context(
                str(tmp_path / 'browser-profile'), headless=True,
                viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
            try:
                # A fresh normal profile models saved phone storage. Private
                # browser contexts may discard Cache Storage when a tab closes.
                # Loopback is a browser-trusted secure context.
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                open_gallery(page, app, origin)
                assert page.evaluate('window.isSecureContext') is True
                expect(page.locator('.gallery-card')).to_have_attribute('data-id', ids['today'])
                page.locator('#galleryMenuButton').click()
                expect(page.locator('#galleryOfflineWrap')).not_to_be_visible()
                expect(page.locator('#galleryOfflineStatus')).to_contain_text(
                    'Offline ready · 2 cards', timeout=20000)
                expect(page.locator('#galleryOfflineStatus')).not_to_contain_text('waiting to retry')
                assert page.evaluate("async () => (await (await caches.open('stats-gallery-images-v1')).keys()).length") == 2
                page.wait_for_function('Boolean(navigator.serviceWorker.controller)')
                subject = page.evaluate("localStorage.getItem('stats.gallery.offlineSubject')")
                assert subject
                assert page.evaluate(
                    "subject => localStorage.getItem('stats.gallery.offlineEnabled.' + subject)",
                    subject) == '1'
                page.locator('[data-close="galleryMenuSheet"]').click()
                expect(page.locator('#galleryMenuSheet')).not_to_be_visible()

                # An unreachable Pi must still work when the phone has internet.
                # Stop the real origin; no request interception supplies cards.
                port = server.server_port
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                server = None
                page.close()
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                assert page.goto(origin + '/gallery/').status == 200
                expect(page.locator('.gallery-card')).to_have_attribute('data-id', ids['today'])
                expect(page.locator('#galleryOfflineStatus')).to_contain_text('stored on this phone')
                cache_state = page.evaluate('''async () => {
                    const cache = await caches.open('stats-gallery-images-v1');
                    return Promise.all((await cache.keys()).map(async request => ({
                        url:request.url,
                        matched:Boolean(await cache.match(request)),
                        matchedIgnoringVary:Boolean(await cache.match(request, {ignoreVary:true})),
                    })));
                }''')
                assert len(cache_state) == 2 and all(entry['matched'] for entry in cache_state), cache_state
                image = page.locator('.gallery-card img')
                expect(image).to_have_attribute('src', re.compile('/gallery/offline-image/'))
                image.evaluate('(img) => img.decode()')
                assert image.evaluate('(img) => img.naturalWidth') == 1200
                page.locator('.gallery-card').click()
                expect(page.locator('#galleryTitle')).to_have_text('Today Customer')
                expect(page.locator('#galleryNotes')).to_contain_text('Keep the existing shared note')
                page.locator('#galleryViewer [data-action="notes"]').click()
                page.locator('#galleryNote [name="author"]').fill('Offline reviewer')
                page.locator('#galleryNote [name="body"]').fill('Saved during the offline visit')
                page.locator('#galleryNote button').click()
                expect(page.locator('#galleryNoteMessage')).to_contain_text('Saved offline.')
                assert gallery.item(ids['today'])['notes'] == before['notes']

                # A fresh tab proves persistence without restoring the previous
                # tab's viewer/notes navigation stack over the card list.
                page.close()
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                assert page.goto(origin + '/gallery/').status == 200
                expect(page.locator('.gallery-card')).to_have_attribute('data-id', ids['today'])
                page.locator('.gallery-card').click()
                expect(page.locator('#galleryNotes')).to_contain_text('Saved during the offline visit')
                expect(page.locator('#galleryNotes')).to_contain_text('Keep the existing shared note')
                assert page.evaluate("localStorage.getItem('stats.gallery.offlineSubject')") == subject

                # Reconnecting uses the normal pending-note outbox and real
                # endpoint, preserving the original note and sending exactly once.
                server = make_server('127.0.0.1', port, app, threaded=True)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                page.close()
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                assert page.goto(origin + '/gallery/').status == 200
                expect(page.locator('#galleryOfflineStatus')).to_contain_text(
                    'Offline ready · 2 cards', timeout=20000)
                notes = gallery.item(ids['today'])['notes']
                assert [note['body'] for note in notes].count('Saved during the offline visit') == 1
                assert [note['body'] for note in notes].count('Keep the existing shared note') == 1
                assert len(notes) == 2
                assert source.calls == []
                assert_no_printing(app)
                assert not errors
            finally:
                context.close()
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
