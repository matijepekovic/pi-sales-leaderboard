"""Full-card phone gallery and related-name boundary. Only synthetic local fixtures."""
import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.gallery.bootstrap import build
from printer_app.gallery.policy import lead_key, printed_lead
from printer_app.gallery.repository import SCHEMA
from printer_app.tests.auth_helpers import gallery_client, open_gallery


def add(service, number, date, name, extra='', *, address=None):
    service.initialize()
    ident = hashlib.sha256(str(number).encode()).hexdigest()
    source = 'a' * 64
    address = f'{number} Example St' if address is None else address
    service.repository.enqueue(source, 'synthetic.pdf')
    service.repository.finish(source, [dict(id=ident, import_id=source, filename='synthetic.pdf',
        page=number, part=1, text=f'Work Order Number: {number:08}\nLead Name: {name}\nAddress: {address}\n{extra}',
        document_date=date, date_status='printed' if date else 'needs-date', bytes=10, created=time.time())])
    return ident


@pytest.mark.parametrize('value,expected', [
    ('Lead Name: Jordan Example Address: 1 Example St Phone: 123', 'Jordan Example'),
    (' | LEAD NAME:  Jordan   Example | Phone: 123', 'Jordan Example'),
    ('Lead Name: Alex O’Neil-Smith, Jr.\nScheduled Start: 2026.08.07', 'Alex O’Neil-Smith, Jr.'),
    ('Notes: Jordan Example called\nAssigned Service Resource: Jordan Example', ''),
    ('Lead Name: Jordan Example\nLead Name: Someone Else', ''),
    ('Lead Name: ??? Address: Example St', ''),
])
def test_lead_is_only_an_explicit_header(value, expected):
    assert printed_lead(value) == expected


def test_related_uses_name_or_address_and_ignores_mentions_in_other_text(tmp_path):
    service = build(tmp_path)
    older = add(service, 1, '2026-08-07', 'Jordan Example')
    newer = add(service, 2, '2026-08-10', 'JORDAN   EXAMPLE')
    mentioned = add(service, 3, '2026-08-11', 'Someone Else', 'Jordan Example called')
    add(service, 4, '2026-08-12', 'Jordan Exampleton')
    same_address = add(service, 5, '2026-08-13', 'Different Customer', address='1 Example St')
    assert [i['id'] for i in service.related(older)['items']] == [same_address, newer, older]
    assert mentioned not in {i['id'] for i in service.related(older)['items']}
    service.note(older, 'b'*32, 'Office', 'Unrelated names do not change grouping')
    assert service.related(older)['total'] == 3
    assert lead_key(' Alex  O’Neil ') == lead_key("alex o'neil")


def test_existing_ocr_backfills_without_new_files_and_corrections_survive_restart(tmp_path):
    service = build(tmp_path)
    service.files.initialize()
    with sqlite3.connect(service.repository.path) as c:
        c.executescript(SCHEMA)  # Pre-lead-index schema, as shipped before this change.
        c.execute("INSERT INTO imports(id,filename,state,created,updated) VALUES(?,?,'COMPLETE',1,1)", ('a'*64, 'old.pdf'))
        c.execute("""INSERT INTO items(id,import_id,page,part,filename,text,notes_text,date_status,bytes,created)
            VALUES(?,?,1,1,'old.pdf','Lead Name: Legacy Example','legacy note','needs-date',10,1)""", ('b'*64, 'a'*64))
        c.execute('INSERT INTO notes VALUES(?,?,?,?,?)', ('c'*32, 'b'*64, 'Office', 'legacy note', 1))
    path = service.files.path('crops', 'b'*64); path.write_bytes(b'unchanged-image')
    service.initialize()
    assert service.item('b'*64)['lead_name'] == 'Legacy Example'
    assert service.search('legacy note', 0)['total'] == 1
    service.lead('b'*64, 'Corrected Example')
    other = build(tmp_path)
    assert other.item('b'*64)['lead_name'] == 'Corrected Example'
    assert other.search('Corrected', 0)['total'] == 1
    assert len(other.item('b'*64)['notes']) == 1
    assert path.read_bytes() == b'unchanged-image'


def test_related_pagination_empty_names_and_unknown_dates(tmp_path):
    service = build(tmp_path)
    anchor = add(service, 1, '2026-08-07', 'Jordan Example')
    for n in range(2, 28): add(service, n, None, 'Jordan Example')
    first = service.related(anchor)
    second = service.related(anchor, 24)
    assert first['total'] == 27 and len(first['items']) == 24 and len(second['items']) == 3
    assert first['items'][0]['id'] == anchor
    assert not ({i['id'] for i in first['items']} & {i['id'] for i in second['items']})
    unknown = add(service, 30, None, '???', address='')
    assert service.item(unknown) is None
    assert service.import_item('a' * 64, unknown)['state'] == 'REVIEW'
    service.approve_import_item('a' * 64, unknown)
    with pytest.raises(ValueError): service.related(unknown)
    service.lead(unknown, 'Jordan Example')
    assert service.related(anchor)['total'] == 28
    with pytest.raises(LookupError): service.related('0'*64)


@pytest.fixture
def web(tmp_path):
    env = tmp_path / 'env'; env.write_text('EMAIL_ENABLED=0\n')
    cfg = Config(data_dir=tmp_path, env_file=env, secret_key='s'*64, email_enabled=False)
    app = create_app(cfg)
    service = build(tmp_path)
    ids = [add(service, 1, '2026-08-07', 'Jordan Example'),
           add(service, 2, '2026-08-10', 'JORDAN EXAMPLE'),
           add(service, 3, '2026-08-11', 'Someone Else')]
    return app, service, ids


def test_web_related_and_work_order_edits_keep_write_protection(web):
    app, service, ids = web
    assert app.test_client().get(f'/gallery/api/items/{ids[0]}/related').status_code == 401
    client = gallery_client(app); response = client.get('/gallery/')
    assert response.status_code == 200
    assert b'Change lead name' not in response.data
    assert client.get(f'/gallery/api/items/{ids[0]}/related').json['total'] == 2
    assert client.get('/gallery/api/items/invalid/related').status_code == 404
    assert client.post(f'/gallery/api/items/{ids[0]}/lead-name',
                       data={'lead_name': 'Another Name'}).status_code == 404
    url = f'/gallery/api/items/{ids[0]}/work-order-number'
    assert client.post(url, data={'work_order_number': '00009999'}).status_code == 400
    with client.session_transaction() as session: csrf = session['csrf']
    form = dict(csrf=csrf, work_order_number='000099999')
    assert client.post(url, data=form, headers={'Origin':'http://elsewhere.test'}).status_code == 403
    assert client.post(url, data=form).status_code == 200
    item = service.item(ids[0])
    assert item['work_order_number'] == '00009999'
    assert item['lead_name'] == ''
    assert service.item(ids[1])['lead_name'] == 'JORDAN EXAMPLE'
    assert service.item(ids[2])['lead_name'] == 'Someone Else'
    assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI-only browser dependencies')
def test_phone_full_cards_related_and_shared_notes(web):
    from PIL import Image
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server
    app, service, ids = web
    for ident in ids:
        Image.new('RGB', (1200, 420), 'white').save(service.files.path('crops', ident))
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                context = browser.new_context(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
                page = context.new_page(); open_gallery(page, app, origin)
                expect(page.locator('#galleryChooseDate')).to_have_text('August 11, 2026 ⌄')
                expect(page.locator('.gallery-day')).to_have_count(1)
                page.wait_for_selector('.gallery-card img')
                image = page.locator('.gallery-card img').first
                image.evaluate('(img) => img.decode()')
                box = image.bounding_box()
                assert box['width'] >= 360 and box['height'] == pytest.approx(box['width'] * 420/1200, abs=1)
                assert image.evaluate('(img) => getComputedStyle(img).objectFit') == 'contain'
                assert page.locator('.gallery-day').count() == 1
                assert page.locator('.gallery-day').first.get_attribute('data-date') == '2026-08-11'
                page.locator('#galleryChooseDate').click()
                page.locator('#galleryCalendarDays [data-date="2026-08-07"]').click()
                expect(page.locator('.gallery-day')).to_have_attribute('data-date', '2026-08-07')
                page.locator(f'.gallery-card[data-id="{ids[0]}"]').click()
                page.locator('#galleryViewer [data-action="related"]').click()
                expect(page.locator('#galleryHeading')).to_have_text('Related cards')
                assert page.locator('.gallery-card').count() == 2
                assert page.locator('.gallery-card').first.get_attribute('data-id') == ids[1]
                assert page.locator('.gallery-card').all()[0].bounding_box()['x'] == page.locator('.gallery-card').all()[1].bounding_box()['x']
                page.locator('.gallery-card').first.evaluate('(node)=>window.scrollTo(0,scrollY+node.getBoundingClientRect().top-100)')
                expect(page.locator('.gallery-card').first).to_have_attribute('aria-pressed','true')
                page.locator('body > .gallery-dock [data-action="notes"]').click()
                page.locator('#galleryNote [name="body"]').fill('Shared follow-up note')
                page.locator('#galleryNote button').click()
                expect(page.locator('#galleryNoteMessage')).to_contain_text('Saved.')
                second = browser.new_context(viewport={'width':390, 'height':844})
                other = second.new_page(); open_gallery(other, app, origin)
                expect(other.locator('#galleryChooseDate')).to_have_text('August 11, 2026 ⌄')
                other.locator('#galleryChooseDate').click()
                other.locator('#galleryCalendarDays [data-date="2026-08-10"]').click()
                expect(other.locator('.gallery-day')).to_have_count(1)
                expect(other.locator('.gallery-day')).to_have_attribute('data-date', '2026-08-10')
                other.locator(f'.gallery-card[data-id="{ids[1]}"]').click()
                other.locator('#galleryViewer [data-action="notes"]').click()
                expect(other.locator('#galleryNotes')).to_contain_text('Shared follow-up note')
                service.note(ids[1], 'd'*32, 'Other device', 'Live update')
                expect(other.locator('#galleryNotes')).to_contain_text('Live update', timeout=10000)
                other.locator('[data-close="galleryNotesSheet"]').click()
                other.locator('[data-close="galleryViewer"]').click()
                expect(other.locator('#galleryViewer')).not_to_be_visible()
                other.locator('body > .gallery-dock [data-action="search"]').click()
                other.locator('#gallerySearch input[value="lead_name"]').check()
                other.locator('#query').fill('Jordan')
                other.locator('#query').press('Enter')
                expect(other.locator('#galleryHeading')).to_have_text('Search results')
                expect(other.locator('.gallery-card')).to_have_count(2)
                assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []
                second.close(); context.close()
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_mobile_view_ownership():
    root = Path(__file__).resolve().parents[1]
    css = (root / 'static/gallery.css').read_text()
    assert 'object-fit:contain' in css and 'object-fit:cover' not in css
    source = (root / 'static/gallery.js').read_text()
    assert '/thumbnail/' not in source and 'drawImage(' not in source
    assert '/gallery/api/items/' in source
    assert '/api/leaderboard' not in source and '/control/' not in source
    template = (root / 'templates/gallery.html').read_text()
    assert 'style.css' not in template and 'gallery.css' in template
