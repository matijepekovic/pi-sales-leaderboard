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


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')
@pytest.mark.parametrize('engine', ['chromium', 'webkit'])
def test_search_field_isolation_date_pagination_and_dialog_history(tmp_path, engine):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server
    from printer_app.app import create_app
    from printer_app.config import Config

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False))
    ids = _seed_gallery(app.extensions['printer_gallery'])
    token = app.extensions['gallery_access'].issue_full_invite()
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = getattr(pw, engine).launch()
            try:
                page = browser.new_page(viewport={'width':320, 'height':720}, is_mobile=True, has_touch=True)
                errors, requests = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: requests.append(request.url))
                page.goto(f'http://127.0.0.1:{server.server_port}/gallery/access/{token}')
                expect(page.locator('#galleryChooseDate')).to_have_text('September 21, 2026 ⌄')
                expect(page.locator('.gallery-card')).to_have_count(24)

                def open_search():
                    page.locator('body > .gallery-dock [data-action="search"]').click()
                    expect(page.locator('#gallerySearchSheet')).to_be_visible()

                def choose_field(label):
                    page.locator('#gallerySearchFields label').filter(has_text=label).click()
                    expect(page.get_by_role('radio', name=label, exact=True)).to_be_checked()

                def submit(query):
                    page.locator('#query').fill(query)
                    page.locator('#gallerySearchSubmit').click()
                    expect(page.locator('#gallerySearchSheet')).not_to_be_visible()
                    expect(page.locator('#galleryChooseDate')).to_have_text('September 21, 2026 ⌄')

                def expect_only(key):
                    expect(page.locator('.gallery-card')).to_have_count(1)
                    expect(page.locator('.gallery-card')).to_have_attribute('data-id', ids[key])

                open_search()
                expect(page.get_by_role('radio', name='Lead name', exact=True)).to_be_checked()
                expect(page.locator('#galleryQueryLabel')).to_have_text('Lead name')
                expect(page.locator('#query')).to_have_attribute('placeholder', 'Enter a lead name…')
                expect(page.locator('#gallerySearchSubmit')).to_have_text('Search this date')
                boxes = page.locator('#gallerySearchFields label').evaluate_all(
                    '(labels) => labels.map(label => {const r=label.getBoundingClientRect();'
                    'return {left:r.left,right:r.right,height:r.height};})'
                )
                assert len(boxes) == 3
                assert all(0 <= box['left'] < box['right'] <= 320 and box['height'] >= 44 for box in boxes)
                assert page.locator('#gallerySearchSheet').evaluate('(node)=>node.scrollWidth<=node.clientWidth')

                # Word-prefix AND, accent/case folding, and field isolation all
                # run against the real repository, including misleading notes.
                choose_field('Rep')
                expect(page.locator('#galleryQueryLabel')).to_have_text('Rep')
                expect(page.locator('#gallerySearchHint')).to_contain_text('rep names only')
                submit('jose ALV')
                expect_only('rep')
                expect(page.locator('#galleryFilterHint')).to_have_text('Matching rep names only')
                open_search()
                choose_field('Lead name')
                submit('jose')
                expect_only('lead')
                open_search()
                submit('"jose moreno"')
                expect_only('lead')
                open_search()
                submit('"jose mor"')
                expect(page.locator('.gallery-card')).to_have_count(0)
                open_search()
                choose_field('Address')
                submit('jose ave')
                expect_only('address')

                # The same mode and date accompany Load more, so the older
                # matching rep and other-field matches never leak into results.
                open_search()
                choose_field('Rep')
                submit('jose')
                expect(page.locator('.gallery-card')).to_have_count(24)
                page.locator('#galleryMore').click()
                expect(page.locator('.gallery-card')).to_have_count(26)
                assert ids['older'] not in page.locator('.gallery-card').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.id)')
                paginated = [parse_qs(urlsplit(url).query) for url in requests
                             if urlsplit(url).path == '/gallery/api/items'
                             and parse_qs(urlsplit(url).query).get('offset') == ['24']]
                assert any(params.get('field') == ['rep'] and params.get('date') == [DAY] for params in paginated)

                # Browser Back/Forward restore the active search separately
                # from an unsubmitted field and query draft in the dialog.
                open_search()
                submit('jose alv')
                expect_only('rep')
                page.locator('.gallery-card').click()
                expect(page.locator('#galleryViewer')).to_be_visible()
                page.locator('#galleryViewer [data-action="search"]').click()
                choose_field('Address')
                page.locator('#query').fill('cedar road draft')
                page.go_back()
                expect(page.locator('#gallerySearchSheet')).not_to_be_visible()
                expect(page.locator('#galleryViewer')).to_be_visible()
                expect(page.locator('.gallery-card')).to_have_attribute('data-id', ids['rep'])
                page.go_forward()
                expect(page.locator('#gallerySearchSheet')).to_be_visible()
                expect(page.get_by_role('radio', name='Address', exact=True)).to_be_checked()
                expect(page.locator('#query')).to_have_value('cedar road draft')
                expect(page.locator('#galleryQueryLabel')).to_have_text('Address')
                assert page.evaluate('history.state.gallery.view.searchField') == 'rep'
                assert page.evaluate('history.state.gallery.view.searchDraftField') == 'address'
                assert page.evaluate('history.state.gallery.view.dateFilter') == DAY
                submit('cedar road')
                expect_only('lead')
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
