"""Read-only date browsing; synthetic fixtures, no Gmail/CUPS or customer files."""
import os
import threading
from pathlib import Path

import pytest

from printer_app.gallery.bootstrap import build
from printer_app.gallery.policy import checked_date_filter
from printer_app.tests.test_gallery_mobile import add, web


def test_dates_cover_all_batches_and_reads_preserve_items(tmp_path):
    service = build(tmp_path)
    latest = add(service, 1, '2026-08-11', 'Jordan Example')
    older = add(service, 2, '2026-08-07', 'Jordan Example')
    unknown = add(service, 3, None, 'Other Example')
    for n in range(4, 32):
        add(service, n, '2026-08-11', 'Jordan Example')
    service.note(older, 'b'*32, 'Office', 'An unchanged note')
    before = service.item(older)
    expected = [dict(date='2026-08-11', count=29), dict(date='2026-08-07', count=1),
                dict(date=None, count=1)]
    first = service.search('', 0)
    assert first['total'] == 31 and len(first['items']) == 24
    assert first['dates'] == expected  # The oldest date is not on the first page.
    chosen = service.search('', 0, '2026-08-07')
    assert chosen['total'] == 1 and chosen['items'][0]['id'] == older
    assert chosen['dates'] == expected  # Not reduced to the selected day.
    tail = service.search('', 24, '2026-08-11')
    assert tail['total'] == 29 and len(tail['items']) == 5
    assert tail['dates'] == expected
    assert service.search('', 0, 'undated')['items'][0]['id'] == unknown
    empty = service.search('', 0, '2026-08-08')
    assert empty['items'] == [] and empty['dates'] == expected
    assert service.item(older) == before
    assert service.item(latest)['document_date'] == '2026-08-11'
    assert build(tmp_path).search('', 0, '2026-08-07')['items'][0]['id'] == older


def test_related_and_search_dates_stay_in_their_scope(tmp_path):
    service = build(tmp_path)
    anchor = add(service, 1, '2026-08-07', 'Jordan Example', 'roof')
    next_card = add(service, 2, '2026-08-10', 'JORDAN EXAMPLE', 'roof')
    add(service, 3, '2026-08-11', 'Other Example', 'bath')
    result = service.related(anchor, 0, '2026-08-10')
    assert [item['id'] for item in result['items']] == [next_card]
    assert result['dates'] == [dict(date='2026-08-10', count=1), dict(date='2026-08-07', count=1)]
    assert service.search('roof', 0, '2026-08-07')['dates'] == result['dates']
    assert service.search('bath', 0, '2026-08-07')['items'] == []
    assert service.search('unmatched', 0)['dates'] == []
    assert service.related(anchor)['total'] == 2  # Existing callers still get all dates.
    with service.repository.connect() as c:
        c.execute("UPDATE items SET state='DELETING' WHERE id=?", (next_card,))
    assert service.related(anchor)['dates'] == [dict(date='2026-08-07', count=1)]


@pytest.mark.parametrize('value', ['20260807', '2026-W32-5', '2026-8-7', '2026-02-30',
                                  '1999-01-01', '2101-01-01', '2026-08-07T12:00:00', "' OR 1=1 --"])
def test_date_filter_rejects_invalid_dates(web, value):
    app, _, ids = web
    with pytest.raises(ValueError):
        checked_date_filter(value)
    for url in ('/gallery/api/items', f'/gallery/api/items/{ids[0]}/related'):
        assert app.test_client().get(url, query_string={'date': value}).status_code == 400


def test_date_browse_is_a_get_not_a_document_edit(web):
    app, service, ids = web
    client = app.test_client()
    before = service.item(ids[0])
    response = client.get('/gallery/api/items', query_string={'date':'2026-08-07'})
    assert response.status_code == 200
    assert [item['id'] for item in response.json['items']] == [ids[0]]
    related = client.get(f'/gallery/api/items/{ids[0]}/related', query_string={'date':'2026-08-10'})
    assert [item['id'] for item in related.json['items']] == [ids[1]]
    assert client.get('/gallery/api/items?date=undated').json['total'] == 0
    assert service.item(ids[0]) == before
    assert client.post(f'/gallery/api/items/{ids[0]}/date', data={'date':'2026-08-10'}).status_code == 400
    assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []


@pytest.fixture
def phone(web):
    from PIL import Image
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server
    app, service, ids = web
    for ident in ids:
        Image.new('RGB', (1200, 420), 'white').save(service.files.path('crops', ident))
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                context = browser.new_context(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
                page = context.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/gallery/')
                from playwright.sync_api import expect
                expect(page.locator('#galleryCards')).to_have_attribute('aria-busy', 'false')
                page.locator('#galleryChooseDate').click(); page.locator('#galleryAllDates').click()
                expect(page.locator('.gallery-day')).to_have_count(3)
                yield page, context, service, ids
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def choose(page, day):
    from playwright.sync_api import expect
    page.locator('#galleryChooseDate').click()
    page.locator(f'#galleryCalendarDays button[data-date="{day}"]').click()
    expect(page.locator('.gallery-day')).to_have_count(1)
    expect(page.locator('.gallery-day')).to_have_attribute('data-date', day)
    expect(page.locator('#galleryCards')).to_have_attribute('aria-busy', 'false')


def touch_swipe(page, context, direction, vertical=False):
    # Real Chromium touch input (not a mouse drag or JS click) traverses Pointer
    # Events and touch-action exactly as the phone feed does.
    image = page.locator('.gallery-card img').first
    image.scroll_into_view_if_needed()
    image.evaluate('(img) => img.decode()')
    box = image.bounding_box()
    x = box['x'] + (box['width'] * (.8 if direction == 'left' else .2))
    y = box['y'] + box['height'] / 2
    dx = box['width'] * (-.6 if direction == 'left' else .6)
    cdp = context.new_cdp_session(page)
    try:
        cdp.send('Input.dispatchTouchEvent', {'type':'touchStart', 'touchPoints':[dict(x=x, y=y)]})
        for step in range(1, 7):
            point = dict(x=x if vertical else x + dx*step/6, y=y - 90*step/6 if vertical else y)
            cdp.send('Input.dispatchTouchEvent', {'type':'touchMove', 'touchPoints':[point]})
        cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd', 'touchPoints':[]})
    finally:
        cdp.detach()


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI-only browser dependencies')
def test_phone_tappable_dates_swipes_and_full_cards(phone):
    from playwright.sync_api import expect
    page, context, service, ids = phone
    expect(page.locator('.gallery-day')).to_have_count(3)
    page.locator('.gallery-day-heading button').first.click()
    expect(page.locator('#galleryDateSheet')).to_be_visible()
    expect(page.locator('#galleryCalendarDays button[data-date="2026-08-08"]')).to_be_disabled()
    page.locator('#galleryCalendarDays button[data-date="2026-08-07"]').click()
    expect(page.locator('.gallery-day')).to_have_count(1)
    expect(page.locator('#galleryCards')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('#galleryPreviousDate')).to_be_disabled()
    touch_swipe(page, context, 'left')
    expect(page.locator('.gallery-day')).to_have_attribute('data-date', '2026-08-10')
    expect(page.locator('#galleryCards')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('#galleryViewer')).not_to_be_visible()  # No accidental tap after a swipe.
    touch_swipe(page, context, 'right')
    expect(page.locator('.gallery-day')).to_have_attribute('data-date', '2026-08-07')
    expect(page.locator('#galleryCards')).to_have_attribute('aria-busy', 'false')
    touch_swipe(page, context, 'left', vertical=True)
    expect(page.locator('.gallery-day')).to_have_attribute('data-date', '2026-08-07')
    page.locator('#galleryNextDate').focus(); page.keyboard.press('Enter')
    expect(page.locator('.gallery-day')).to_have_attribute('data-date', '2026-08-10')
    expect(page.locator('#galleryCards')).to_have_attribute('aria-busy', 'false')
    page.locator('#galleryNextDate').click()
    expect(page.locator('.gallery-day')).to_have_attribute('data-date', '2026-08-11')
    expect(page.locator('#galleryNextDate')).to_be_disabled()
    image = page.locator('.gallery-card img').first
    image.evaluate('(img) => img.decode()'); box = image.bounding_box()
    assert box['width'] >= 360 and box['height'] == pytest.approx(box['width'] * 420/1200, abs=1)
    assert image.evaluate('(img) => getComputedStyle(img).objectFit') == 'contain'
    assert service.item(ids[0])['document_date'] == '2026-08-07'


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI-only browser dependencies')
def test_related_and_search_reset_date_then_offer_scoped_calendar(phone):
    from playwright.sync_api import expect
    page, _, _, ids = phone
    expect(page.locator('.gallery-day')).to_have_count(3)
    choose(page, '2026-08-07')
    page.locator('.gallery-card').click()
    page.locator('#galleryViewerDate').click()
    expect(page.locator('#galleryDateSheet')).to_be_visible()
    page.locator('[data-close="galleryDateSheet"]').click()
    page.locator('#galleryViewer [data-action="related"]').click()
    expect(page.locator('#galleryHeading')).to_have_text('Related cards')
    expect(page.locator('.gallery-card')).to_have_count(2)
    expect(page.locator('#galleryChooseDate')).to_have_text('All dates ⌄')
    page.locator('#galleryChooseDate').click()
    expect(page.locator('#galleryCalendarDays button[data-date="2026-08-11"]')).to_be_disabled()
    page.locator('#galleryCalendarDays button[data-date="2026-08-07"]').click()
    expect(page.locator('.gallery-card')).to_have_count(1)
    page.locator('body > .gallery-dock [data-action="search"]').click()
    page.locator('#query').fill('Jordan')
    page.locator('#gallerySearch button').click()
    expect(page.locator('#galleryCards')).to_have_attribute('aria-busy', 'false')
    expect(page.locator('#galleryHeading')).to_have_text('Search results')
    expect(page.locator('.gallery-card')).to_have_count(2)
    expect(page.locator('#galleryChooseDate')).to_have_text('All dates ⌄')
    page.locator('#galleryChooseDate').click(); page.locator('#galleryAllDates').click()
    expect(page.locator('#galleryHeading')).to_have_text('Search results')
    expect(page.locator('.gallery-card')).to_have_count(2)


def test_date_navigation_owner_boundaries():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'static/gallery_dates.js').read_text()
    assert 'fetch(' not in source and 'method:' not in source  # UI never writes a date/queue itself.
    assert 'pointercancel' in source and 'visualViewport' in source and 'touches.size' in source
    for path in ('gallery/service.py', 'gallery/web.py', 'static/gallery.js', 'static/gallery_dates.js'):
        assert 'SELECT ' not in (root / path).read_text()
    assert 'touch-action:pan-y pinch-zoom' in (root / 'static/gallery.css').read_text()
    assert 'type="module"' in (root / 'templates/gallery.html').read_text()
    assert 'object-fit:cover' not in (root / 'static/gallery.css').read_text()
