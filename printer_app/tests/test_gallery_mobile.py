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


def add(service, number, date, name, extra=''):
    service.initialize()
    ident = hashlib.sha256(str(number).encode()).hexdigest()
    source = 'a' * 64
    service.repository.enqueue(source, 'synthetic.pdf')
    service.repository.finish(source, [dict(id=ident, import_id=source, filename='synthetic.pdf',
        page=number, part=1, text=f'Lead Name: {name} Address: 1 Example St\n{extra}',
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


def test_related_uses_exact_normalized_lead_not_notes_or_other_people(tmp_path):
    service = build(tmp_path)
    older = add(service, 1, '2026-08-07', 'Jordan Example')
    newer = add(service, 2, '2026-08-10', 'JORDAN   EXAMPLE')
    add(service, 3, '2026-08-11', 'Someone Else', 'Jordan Example called')
    add(service, 4, '2026-08-12', 'Jordan Exampleton')
    assert [i['id'] for i in service.related(older)['items']] == [newer, older]
    service.note(older, 'b'*32, 'Office', 'Unrelated names do not change grouping')
    assert service.related(older)['total'] == 2
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
    unknown = add(service, 30, None, '???')
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


def test_web_related_and_name_edits_keep_write_protection(web):
    app, service, ids = web
    client = app.test_client(); response = client.get('/gallery/')
    assert response.status_code == 200
    assert client.get(f'/gallery/api/items/{ids[0]}/related').json['total'] == 2
    assert client.get('/gallery/api/items/invalid/related').status_code == 404
    url = f'/gallery/api/items/{ids[0]}/lead-name'
    assert client.post(url, data={'lead_name': 'Another Name'}).status_code == 400
    with client.session_transaction() as session: csrf = session['csrf']
    form = dict(csrf=csrf, lead_name='Corrected Example')
    assert client.post(url, data=form, headers={'Origin':'http://elsewhere.test'}).status_code == 403
    assert service.item(ids[0])['lead_name'] == 'Jordan Example'
    assert client.post(url, data=form).status_code == 200
    assert client.get('/gallery/api/items?q=Corrected').json['total'] == 1
    assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI-only browser dependencies')
def test_phone_full_cards_related_and_shared_notes(web):
    from PIL import Image
    from playwright.sync_api import sync_playwright
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
                page = context.new_page(); page.goto(origin + '/gallery/')
                page.wait_for_selector('.gallery-card img')
                image = page.locator('.gallery-card img').first
                image.evaluate('(img) => img.decode()')
                box = image.bounding_box()
                assert box['width'] >= 360 and box['height'] == pytest.approx(box['width'] * 420/1200, abs=1)
                assert image.evaluate('(img) => getComputedStyle(img).objectFit') == 'contain'
                assert page.locator('.gallery-day').count() == 3
                assert page.locator('.gallery-day').first.get_attribute('data-date') == '2026-08-11'
                page.locator(f'.gallery-card[data-id="{ids[0]}"]').click()
                page.locator('#galleryViewer [data-action="related"]').click()
                page.wait_for_function("document.getElementById('galleryHeading').textContent === 'Related cards'")
                assert page.locator('.gallery-card').count() == 2
                assert page.locator('.gallery-card').first.get_attribute('data-id') == ids[1]
                assert page.locator('.gallery-card').all()[0].bounding_box()['x'] == page.locator('.gallery-card').all()[1].bounding_box()['x']
                page.locator('body > .gallery-dock [data-action="notes"]').click()
                page.locator('#galleryNote [name="body"]').fill('Shared follow-up note')
                page.locator('#galleryNote button').click()
                page.wait_for_function("document.getElementById('galleryNoteMessage').textContent.startsWith('Saved.')")
                second = browser.new_context(viewport={'width':390, 'height':844})
                other = second.new_page(); other.goto(origin + '/gallery/')
                other.locator(f'.gallery-card[data-id="{ids[0]}"]').click()
                other.locator('#galleryViewer [data-action="notes"]').click()
                other.wait_for_function("document.getElementById('galleryNotes').textContent.includes('Shared follow-up note')")
                service.note(ids[0], 'd'*32, 'Other device', 'Live update')
                other.wait_for_function("document.getElementById('galleryNotes').textContent.includes('Live update')", timeout=10000)
                other.locator('[data-close="galleryNotesSheet"]').click()
                other.locator('#galleryViewer [data-action="search"]').click()
                other.locator('#query').fill('follow-up')
                other.locator('#gallerySearch button').click()
                other.wait_for_function("document.getElementById('galleryHeading').textContent === 'Search results'")
                assert other.locator('.gallery-card').count() == 1
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
