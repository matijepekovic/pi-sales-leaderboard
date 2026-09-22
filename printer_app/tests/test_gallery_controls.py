"""Regression coverage for the complete shipped controls, not just backend helpers."""
import hashlib
import os
import threading
import time
from pathlib import Path

import pytest

from printer_app.db import Database
from printer_app.gallery.bootstrap import build
from printer_app.print_queue_repository import PrintQueueRepository
from printer_app.tests.auth_helpers import login_admin, open_gallery


def print_fixture(db, number=1):
    mid = db.execute('''INSERT INTO processed_messages
        (identity,account,mailbox,uidvalidity,uid,message_id,subject,sender,created)
        VALUES (?,'fixture','INBOX','1',?,?,'Test email','fixture@example.test',1)''',
        (str(number), str(number), str(number)))
    aid = db.execute("INSERT INTO attachments(message_id,part,filename,state,created) VALUES (?,'1','report.pdf','DONE',1)", (mid,))
    jid = db.create_job(aid, 'pdf', {})
    db.execute("UPDATE jobs SET status='READY' WHERE id=?", (jid,))
    return aid, jid


def card(service, number, name, day='2026-09-15', extra=''):
    service.initialize()
    ident = hashlib.sha256(str(number).encode()).hexdigest()
    iid = 'a' * 64
    service.repository.enqueue(iid, 'fixture.pdf')
    service.repository.finish(iid, [dict(id=ident, import_id=iid, filename='fixture.pdf', page=number,
        part=1, text=f'Work Order Number: {number:08} Lead Name: {name} Address: {number} Test street\n{extra}',
        document_date=day, date_status='printed', bytes=10, created=number)])
    return ident


def test_cancelled_attachment_never_returns_on_release_or_restart(tmp_path):
    db = Database(tmp_path / 'queue.db')
    aid, jid = print_fixture(db)
    other, other_job = print_fixture(db, 2)
    queue = PrintQueueRepository(db)
    assert queue.cancel_attachment(aid, 2)
    assert not queue.cancel_attachment(aid, 3)
    queue = PrintQueueRepository(Database(db.path))
    queue.request_manual_release(4); queue.release_requested(4)
    queue.recover_cancellations(5)
    assert queue.reserve_attempt(jid, 'cancelled', 6) is None
    assert [j['id'] for j in queue.due_jobs(6, True)] == [other_job]
    assert db.job(jid)['status'] == 'CANCELLED'
    assert not queue.cancelled(other)


def test_submission_reservation_wins_over_late_removal(tmp_path):
    db = Database(tmp_path / 'queue.db'); aid, jid = print_fixture(db)
    queue = PrintQueueRepository(db)
    assert queue.reserve_attempt(jid, 'in-flight', 2)
    with pytest.raises(ValueError): queue.cancel_attachment(aid, 3)
    assert not queue.cancelled(aid)


def test_existing_flattened_names_backfill_and_notes_stay_out_of_related_identity(tmp_path):
    service = build(tmp_path)
    anchor = card(service, 1, 'Jordan Example')
    other = card(service, 2, 'Someone Else', '2026-08-07', 'Jordan Example called')
    note_only = card(service, 3, 'Other Person', '2026-09-01')
    service.note(note_only, 'c' * 32, 'Desk', 'Follow up Jordan Example')
    service.lead(other, 'User Corrected')
    with service.repository.connect() as c:
        c.execute("UPDATE items SET lead_name='',lead_key='',lead_status='needs-name' WHERE id=?", (anchor,))
        c.execute("DELETE FROM meta WHERE key='flattened_lead_backfill'")
    restarted = build(tmp_path)
    assert restarted.item(anchor)['lead_name'] == 'Jordan Example'
    assert restarted.item(other)['lead_name'] == 'User Corrected'
    assert {i['id'] for i in restarted.related(anchor)['items']} == {anchor}
    assert {i['id'] for i in restarted.search('Jordan Example', 0)['items']} == {anchor, other, note_only}
    assert restarted.item(note_only)['notes'][0]['body'] == 'Follow up Jordan Example'


def test_web_controls_really_render_and_cancel_with_csrf(tmp_path):
    from printer_app.app import create_app
    from printer_app.config import Config
    env = tmp_path / 'env'; env.write_text('EMAIL_ENABLED=0\nPRINT_SCHEDULE_MODE=hold\n')
    app = create_app(Config(data_dir=tmp_path, env_file=env, secret_key='s'*64))
    client = app.test_client(); db = app.extensions['printer_db']
    assert client.get('/').status_code == 302
    login_admin(client)
    aid, jid = print_fixture(db)
    service = app.extensions['printer_gallery']
    ident = card(service, 1, 'Jordan Example')
    service.files.path('crops', ident).write_bytes(b'fixture image')
    service.repository.enqueue('b'*64, 'waiting.pdf')
    service.repository.failed('d'*64, 'No-op unknown job')
    home = client.get('/')
    assert home.status_code == 200
    assert b'Gallery Queue' in home.data and b'View gallery jobs' in home.data
    assert b'Remove from print queue' in home.data
    assert client.get('/gallery/queue').status_code == 200
    job_page = client.get('/gallery/jobs/' + 'a'*64)
    assert job_page.status_code == 200 and b'Generated work orders' in job_page.data
    assert b'value="00000001"' in job_page.data
    assert b'Work order needs correction' not in job_page.data
    admin_image = '/gallery/jobs/' + 'a' * 64 + '/items/' + ident + '/image'
    assert admin_image.encode() in job_page.data
    assert client.get(admin_image).data == b'fixture image'
    assert b'Processing log' in job_page.data
    assert client.get('/gallery/jobs/invalid').status_code == 404
    assert client.get('/gallery/queue?offset=bad').status_code == 400
    assert b'Remove from print queue' in client.get(f'/jobs/{jid}').data
    url = f'/print-queue/{aid}/remove'
    assert client.get(url).status_code == 200  # A GET never cancels.
    assert db.job(jid)['status'] == 'READY'
    assert client.post(url, data={'confirm':'remove'}).status_code == 400
    with client.session_transaction() as s: csrf = s['csrf']
    form = dict(confirm='remove', csrf=csrf)
    assert client.post(url, data=form, headers={'Origin':'http://elsewhere.test'}).status_code == 403
    assert client.post(url, data=form).status_code == 303
    assert db.job(jid)['status'] == 'CANCELLED'
    assert service.item(ident) and service.files.path('crops', ident).read_bytes() == b'fixture image'
    other_aid, other_jid = print_fixture(db, 2)
    PrintQueueRepository(db).reserve_attempt(other_jid, 'reserved', time.time())
    assert client.post(f'/print-queue/{other_aid}/remove', data=form).status_code == 409
    token = app.extensions['gallery_access'].issue_full_invite()
    gallery = client.get('/gallery/access/' + token, follow_redirects=True).data
    assert b'Print Control</a>' not in gallery and b'Gallery settings</a>' not in gallery
    assert b'href="/settings' not in gallery and b'href="/system/print-control' not in gallery


def test_gallery_focus_is_loaded_and_related_has_no_prompt():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'static/gallery.js').read_text()
    template = (root / 'templates/gallery.html').read_text()
    assert "import { GalleryFocus } from './gallery_focus.js'" in source
    assert 'new GalleryFocus(' in source and 'focus.reset()' in source
    assert 'form.dataset.itemId' in source
    assert 'openNotes(true)' not in source and 'relatedAfterSave' not in source
    assert 'history.back(' not in source
    assert template.count('data-action="related"') == 1
    assert "if (!el('galleryViewer').open) return;" in source
    assert 'id="galleryMenuButton"' in template and 'id="galleryMenuSheet"' in template
    calendar = template.split('id="galleryDateSheet"', 1)[1].split('</dialog>', 1)[0]
    assert 'galleryShare' not in calendar
    assert 'galleryOfflineToggle' not in calendar
    assert 'galleryMenuRefresh' not in calendar
    for name in ('app.py', 'gallery/web.py', 'gallery/service.py', 'static/gallery_focus.js'):
        assert 'print_queue_cancellations' not in (root / name).read_text()


@pytest.mark.skipif(os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies')
def test_browser_one_click_related_and_notes_target_visible_card(tmp_path):
    from PIL import Image
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.serving import make_server
    from printer_app.app import create_app
    from printer_app.config import Config
    env = tmp_path / 'env'; env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path, env_file=env, secret_key='s'*64))
    service = app.extensions['printer_gallery']
    anchor = card(service, 1, 'Jordan Example')
    older = card(service, 2, 'JORDAN EXAMPLE', '2026-08-07')
    third = card(service, 3, 'Someone Else', '2026-08-01')
    service.note(third, 'e'*32, 'Desk', 'Jordan Example follow-up')
    for ident in (anchor, older, third):
        # Two related cards must create real scroll travel for visible-card focus.
        Image.new('RGB', (1200, 1400), 'white').save(service.files.path('crops', ident))
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={'width':390, 'height':844}, is_mobile=True, has_touch=True)
            page = context.new_page(); errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
            open_gallery(page, app, origin)
            expect(page.locator(f'.gallery-card[data-id="{anchor}"]')).to_have_attribute('aria-pressed', 'true')
            # Feed controls expose Menu/Notes/Search. Related belongs only to an opened card.
            page.locator('#galleryChooseDate').click()
            page.locator('#galleryCalendarDays [data-date="2026-09-15"]').click()
            expect(page.locator('.gallery-card')).to_have_count(1)
            expect(page.locator('body > .gallery-dock [data-action="related"]')).to_have_count(0)
            page.locator('#galleryMenuButton').click()
            expect(page.locator('#galleryMenuSheet')).to_be_visible()
            expect(page.locator('#galleryMenuRefresh')).to_be_visible()
            page.locator('[data-close="galleryMenuSheet"]').click()
            page.locator('.gallery-card').click()
            page.locator('#galleryViewer [data-action="related"]').click()
            expect(page.locator('#galleryHeading')).to_have_text('Related cards')
            expect(page.locator('#galleryFilterTitle')).to_have_text('Jordan Example')
            expect(page.locator('.gallery-card')).to_have_count(2)
            expect(page.locator('#galleryNotesSheet')).not_to_be_visible()
            # Scroll without tapping a card; actions follow the topmost visible card.
            target = page.locator(f'.gallery-card[data-id="{older}"]')
            target.locator('img').evaluate('(img) => img.decode()')
            target.evaluate('''(node) => {
                const rect = node.getBoundingClientRect();
                window.scrollTo(0, scrollY + rect.top + rect.height / 2 - innerHeight / 2);
            }''')
            expect(target).to_have_attribute('aria-pressed', 'true')
            page.locator('body > .gallery-dock [data-action="notes"]').click()
            expect(page.locator('#galleryNote')).to_have_attribute('data-item-id', older)
            page.locator('#galleryNote [name="body"]').fill('Visible-card note')
            page.set_viewport_size({'width':390, 'height':690})
            page.locator('#galleryNote button').click()
            expect(page.locator('#galleryNoteMessage')).to_contain_text('Saved.')
            assert len(service.item(anchor)['notes']) == 0
            assert service.item(older)['notes'][0]['body'] == 'Visible-card note'
            second = browser.new_page(viewport={'width':390,'height':844})
            open_gallery(second, app, origin)
            # A fresh gallery opens the latest date. Choose the older card's month
            # and date before checking that its shared note persisted.
            second.locator('#galleryChooseDate').click()
            second.locator('#galleryCalendarMonth').select_option('2026-08')
            second.locator('#galleryCalendarDays [data-date="2026-08-07"]').click()
            expect(second.locator('.gallery-day')).to_have_attribute('data-date', '2026-08-07')
            second.locator(f'.gallery-card[data-id="{older}"]').click()
            second.locator('#galleryViewer [data-action="notes"]').click()
            expect(second.locator('#galleryNotes')).to_contain_text('Visible-card note')
            assert not errors
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
