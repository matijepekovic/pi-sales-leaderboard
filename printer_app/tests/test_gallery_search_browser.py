"""Real field-scoped Gallery searches and mobile history in Chromium/WebKit."""
import hashlib
import os
import threading
from urllib.parse import parse_qs, urlsplit

import pytest


DAY = '2026-09-21'


def _seed_gallery(service):
    from PIL import Image
    from printer_app.mod_sheet_contract import ModSheetRecord

    service.initialize()
    definitions = [
        ('rep', DAY, 'Lina Example', '100 Pine Lane', 'José Alvarez'),
        ('lead', DAY, 'José Moreno', '200 Cedar Road', 'Other Rep'),
        ('address', DAY, 'Taylor Example', '300 Jose Avenue', 'Third Rep'),
        ('notes', DAY, 'Noise Example', '400 Birch Road', 'Fourth Rep'),
        ('older', '2026-09-20', 'Older Example', '500 Elm Road', 'José Alvarez'),
    ] + [(f'page-{n}', DAY, f'Paging Customer {n}', f'{600 + n} Maple Street', f'José Paging {n}')
         for n in range(25)]
    ids, references = {}, {}
    for number, (key, day, name, address, rep) in enumerate(definitions, 1):
        ident = hashlib.sha256(key.encode()).hexdigest()
        import_id = hashlib.sha256(('import-' + key).encode()).hexdigest()
        order = f'WO-{number:04}'
        service.repository.enqueue(import_id, 'synthetic.pdf')
        service.repository.finish(import_id, [dict(
            id=ident, import_id=import_id, filename='synthetic.pdf', page=number, part=1,
            text=f'Work Order Number: {order}\nLead Name: {name}\nAddress: {address}\n'
                 'Lead Description: José appears in unrelated printed notes',
            lead_text='Lead Name: ' + name, document_date=day, date_status='printed',
            bytes=10, created=number, recognition_revision=1,
        )])
        Image.new('RGB', (1200, 420), 'white').save(service.files.path('crops', ident))
        references.setdefault(day, []).append(ModSheetRecord(
            source_id=key, work_order_number=order, lead_name=name, address=address,
            assigned_service_resources=(rep,),
        ))
        ids[key] = ident
    for day, records in references.items():
        service.publish_reference_snapshot(day, 'final', records, 100.0)
    service.note(ids['notes'], 'e' * 32, 'Office', 'José Alvarez appears only in this shared note')
    return ids


pytestmark = pytest.mark.skipif(
    os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')


@pytest.fixture(params=['chromium', 'webkit'])
def gallery_browser(tmp_path, request):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server
    from printer_app.app import create_app
    from printer_app.config import Config
    from printer_app.tests.auth_helpers import open_gallery

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False))
    service = app.extensions['printer_gallery']
    ids = _seed_gallery(service)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = getattr(pw, request.param).launch()
            try:
                page = browser.new_page(viewport={'width':320, 'height':720}, is_mobile=True, has_touch=True)
                errors, requests = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda incoming: requests.append(incoming.url))
                open_gallery(page, app, f'http://127.0.0.1:{server.server_port}')
                expect(page.locator('#galleryChooseDate')).to_have_text('September 21, 2026 ⌄')
                expect(page.locator('.gallery-card')).to_have_count(24)
                expect(page.locator('#galleryCards')).to_have_attribute('aria-busy', 'false')
                yield page, service, ids, requests
                assert not errors
                assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _open_search(page):
    from playwright.sync_api import expect

    page.locator('body > .gallery-dock [data-action="search"]').click()
    expect(page.locator('#gallerySearchSheet')).to_be_visible()
    expect(page.locator('.gallery-date-nav')).not_to_be_visible()
    expect(page.locator('#gallerySearchHint')).to_have_text('All dates · 30 cards')


def _choose_field(page, name):
    from playwright.sync_api import expect

    page.locator('#gallerySearchFields label').filter(has_text=name).click()
    expect(page.get_by_role('radio', name=name, exact=True)).to_be_checked()


def _expect_ids(page, expected):
    from playwright.sync_api import expect

    expect(page.locator('.gallery-card')).to_have_count(len(expected))
    # A field/query change may keep the same result count while loading new IDs.
    page.wait_for_function("""(expected) => {
      const actual = [...document.querySelectorAll('.gallery-card')].map(node => node.dataset.id).sort();
      return JSON.stringify(actual) === JSON.stringify([...expected].sort());
    }""", arg=list(expected))


def _type_query(page, query):
    # Wait for the typed query itself, even when successive queries have the
    # same result IDs, so every assertion covers a completed live search.
    with page.expect_response(lambda response: urlsplit(response.url).path == '/gallery/api/items'
                              and parse_qs(urlsplit(response.url).query, keep_blank_values=True)
                              .get('q') == [query]) as response:
        page.locator('#query').fill(query)
    assert response.value.status == 200


def _item_queries(requests):
    return [parse_qs(urlsplit(url).query, keep_blank_values=True) for url in requests
            if urlsplit(url).path == '/gallery/api/items']


def test_live_search_all_dates_field_isolation_pagination_and_compact_mobile_bar(gallery_browser):
    from playwright.sync_api import expect

    page, _, ids, requests = gallery_browser
    before_search = len(requests)
    _open_search(page)
    panel = page.locator('#gallerySearchSheet')
    assert panel.evaluate('(node) => node.localName') == 'section'
    expect(page.locator('dialog[open]')).to_have_count(0)
    expect(page.get_by_role('radio', name='H/O', exact=True)).to_be_checked()
    expect(page.locator('#query')).to_have_attribute('placeholder', 'Enter H/O name…')
    box = panel.bounding_box()
    assert 0 < box['height'] <= 130
    labels = page.locator('#gallerySearchFields label').evaluate_all(
        '(nodes) => nodes.map(node => {const r=node.getBoundingClientRect();'
        'return {left:r.left,right:r.right,height:r.height};})')
    assert len(labels) == 3
    assert all(0 <= label['left'] < label['right'] <= 320 and label['height'] >= 44 for label in labels)
    assert panel.evaluate('(node) => node.scrollWidth <= node.clientWidth')
    assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')

    # Typing alone updates the real feed. Accent/case folding and multiword
    # prefixes apply only to the selected field, across both document dates.
    _choose_field(page, 'Rep')
    _type_query(page, 'jose ALV')
    _expect_ids(page, [ids['rep'], ids['older']])
    expect(panel).to_be_visible()
    expect(page.locator('#gallerySearchHint')).to_have_text('All dates · 2 cards')
    _choose_field(page, 'H/O')
    _type_query(page, 'jose')
    _expect_ids(page, [ids['lead']])
    _type_query(page, '"jose moreno"')
    _expect_ids(page, [ids['lead']])
    _type_query(page, '"jose mor"')
    _expect_ids(page, [])
    _choose_field(page, 'Address')
    _type_query(page, 'jose ave')
    _expect_ids(page, [ids['address']])

    # Clearing the input keeps the all-date search view, including older cards.
    _type_query(page, '')
    expect(page.locator('#gallerySearchHint')).to_have_text('All dates · 30 cards')
    expect(page.locator('.gallery-card')).to_have_count(24)
    expect(page.locator('.gallery-date-nav')).not_to_be_visible()
    page.locator('#galleryMore').click()
    _expect_ids(page, ids.values())

    _choose_field(page, 'Rep')
    _type_query(page, 'jose')
    expect(page.locator('#gallerySearchHint')).to_have_text('All dates · 27 cards')
    expect(page.locator('.gallery-card')).to_have_count(24)
    page.locator('#galleryMore').click()
    _expect_ids(page, [ids['rep'], ids['older']] + [ids[f'page-{n}'] for n in range(25)])
    queries = _item_queries(requests[before_search:])
    assert queries and all(params.get('date') == [''] for params in queries)
    assert any(params.get('q') == ['jose'] and params.get('field') == ['rep']
               and params.get('offset') == ['24'] for params in queries)
    expect(panel).to_be_visible()


def test_delayed_real_search_response_cannot_replace_newer_query(gallery_browser):
    from playwright.sync_api import expect

    page, _, ids, _ = gallery_browser
    _open_search(page)
    _choose_field(page, 'Address')
    # Both queries reach Flask. Hold only delivery of the first real response;
    # no fabricated card data or intercepted endpoint substitutes are involved.
    page.evaluate("""() => {
      const actualFetch = window.fetch.bind(window);
      window.searchRace = {held:false, consumed:false};
      window.fetch = async (...args) => {
        const url = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href);
        const response = await actualFetch(...args);
        if (url.pathname === '/gallery/api/items' && url.searchParams.get('q') === 'pine') {
          await response.clone().arrayBuffer();
          window.searchRace.held = true;
          await new Promise(resolve => {window.releaseSearchResponse = resolve;});
          const actualJson = response.json.bind(response);
          response.json = async () => {
            const body = await actualJson();
            setTimeout(() => {window.searchRace.consumed = true;}, 0);
            return body;
          };
        }
        return response;
      };
    }""")
    page.locator('#query').fill('pine')
    page.wait_for_function('() => window.searchRace.held')
    page.locator('#query').fill('cedar')
    page.locator('#query').press('Enter')
    _expect_ids(page, [ids['lead']])
    page.evaluate('() => window.releaseSearchResponse()')
    page.wait_for_function('() => window.searchRace.consumed')
    _expect_ids(page, [ids['lead']])
    expect(page.locator('#query')).to_have_value('cedar')
    expect(page.locator('#gallerySearchSheet')).to_be_visible()
    expect(page.locator('#gallerySearchHint')).to_have_text('All dates · 1 card')


def test_pending_live_query_keeps_viewer_and_note_target_and_restores_day(gallery_browser):
    from playwright.sync_api import expect

    page, service, ids, requests = gallery_browser
    _open_search(page)
    _choose_field(page, 'Rep')
    _type_query(page, 'jose alv')
    _expect_ids(page, [ids['rep'], ids['older']])
    # Dispatch the input and card click in the same browser task so the action
    # is deterministically inside the debounce window, even on a slow CI host.
    page.evaluate("""(id) => {
      const input = document.getElementById('query');
      input.value = 'jose paging';
      input.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertText'}));
      window.searchInputAt = performance.now();
      document.querySelector('.gallery-card[data-id="' + id + '"]').click();
    }""", ids['rep'])
    expect(page.locator('#galleryViewer')).to_be_visible()
    expect(page.locator('#galleryTitle')).to_have_text('Lina Example')
    page.wait_for_function('() => performance.now() - window.searchInputAt >= 300')
    assert not any(params.get('q') == ['jose paging'] for params in _item_queries(requests))
    expect(page.locator('#galleryFull')).to_have_attribute(
        'src', '/gallery/image/' + ids['rep'] + '?v=' + service.item(ids['rep'])['image_revision'])
    page.locator('#galleryViewer [data-action="notes"]').click()
    expect(page.locator('#galleryNote')).to_have_attribute('data-item-id', ids['rep'])
    expect(page.locator('#galleryNotesContext')).to_contain_text('Lina Example')
    page.locator('#galleryNote [name="author"]').fill('Office')
    page.locator('#galleryNote [name="body"]').fill('Pinned while search changes')
    page.locator('#galleryNote button').click()
    expect(page.locator('#galleryNoteMessage')).to_contain_text('Saved.')
    assert [note['body'] for note in service.item(ids['rep'])['notes']] == ['Pinned while search changes']
    assert service.item(ids['older'])['notes'] == []
    assert all(service.item(ids[f'page-{n}'])['notes'] == [] for n in range(25))

    page.go_back()
    expect(page.locator('#galleryNotesSheet')).not_to_be_visible()
    expect(page.locator('#galleryViewer')).to_be_visible()
    expect(page.locator('#galleryTitle')).to_have_text('Lina Example')
    page.go_back()
    expect(page.locator('#galleryViewer')).not_to_be_visible()
    expect(page.locator('#gallerySearchSheet')).to_be_visible()
    expect(page.get_by_role('radio', name='Rep', exact=True)).to_be_checked()
    expect(page.locator('#query')).to_have_value('jose paging')
    expect(page.locator('#gallerySearchHint')).to_have_text('All dates · 25 cards')
    expect(page.locator('.gallery-card')).to_have_count(24)
    page.locator('#gallerySearchClose').click()
    expect(page.locator('#gallerySearchSheet')).not_to_be_visible()
    expect(page.locator('#galleryChooseDate')).to_have_text('September 21, 2026 ⌄')
    expect(page.locator('.gallery-card')).to_have_count(24)
    expect(page.locator('.gallery-date-nav')).to_be_visible()
    page.go_forward()
    expect(page.locator('#gallerySearchSheet')).to_be_visible()
    expect(page.get_by_role('radio', name='Rep', exact=True)).to_be_checked()
    expect(page.locator('#query')).to_have_value('jose paging')
    expect(page.locator('#gallerySearchHint')).to_have_text('All dates · 25 cards')
