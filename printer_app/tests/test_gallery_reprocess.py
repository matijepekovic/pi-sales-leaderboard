"""Gallery Queue reprocess discards gallery output and redelivers from email only."""
import hashlib
import time

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.tests.auth_helpers import login_admin


def seed_source(db, filename, *, message_id=None, sha256='', printed=False):
    now = time.time()
    if message_id is None:
        identity = hashlib.sha256((filename + str(now)).encode()).hexdigest()
        message_id = db.execute("""INSERT INTO processed_messages
            (identity,account,mailbox,uidvalidity,uid,message_id,subject,sender,state,created)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (identity, 'office@example.test', 'INBOX', '1', str(int(identity[:12], 16)),
             f'<{identity[:12]}@gallery.test>', 'Gallery source', 'office@example.test', 'COMPLETE', now))
    db.execute("""INSERT INTO email_attachment_routes
        (message_id,part,filename,print_document,import_document,gallery_delivered,error,updated)
        VALUES (?,?,?,?,?,?,?,?)""", (message_id, '1', filename, int(printed), 1, 1, '', now))
    if sha256:
        aid = db.execute("""INSERT INTO attachments(message_id,part,filename,sha256,path,error,state,created)
            VALUES (?,?,?,?,?,?,?,?)""", (message_id, '1', filename, sha256, '/tmp/already-collected.pdf', '', 'PENDING', now))
        if printed:
            jid = db.create_job(aid, 'pdf', {})
            db.execute("UPDATE jobs SET status='PRINTED',updated=?,completed=? WHERE id=?", (now, now, jid))
    return message_id


def seed_gallery(gallery, filename, payload, *, origin='scan'):
    gallery.initialize()
    ident = hashlib.sha256(payload).hexdigest()
    gallery.repository.enqueue(ident, filename, origin=origin)
    item_id = hashlib.sha256((ident + ':1:1').encode()).hexdigest()
    gallery.files.path('crops', item_id).write_bytes(b'poorly-processed-card')
    gallery.repository.finish(ident, [dict(id=item_id, import_id=ident, page=1, part=1,
        filename=filename, text='Lead Name: OLD RESULT', document_date='2026-09-17',
        date_status='printed', bytes=21, created=time.time(), recognition_revision=1,
        origin=origin)])
    gallery.note(item_id, item_id[:32], 'Office', 'delete this with the bad card')
    return ident, item_id


def test_gallery_queue_reprocess_deletes_cards_and_queues_original_email_again(tmp_path):
    env = tmp_path / 'env'; env.write_text('EMAIL_ENABLED=0\n')
    cfg = Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False)
    app = create_app(cfg)
    db = app.extensions['printer_db']
    gallery = app.extensions['printer_gallery']
    filename, payload = 'OLY REDLINES 91726.pdf', b'original gallery pdf bytes'
    ident, item_id = seed_gallery(gallery, filename, payload)
    seed_source(db, filename, sha256=ident, printed=True)
    jobs_before = db.rows('SELECT * FROM jobs ORDER BY id')
    attempts_before = db.rows('SELECT * FROM print_attempts ORDER BY id')

    client = app.test_client()
    assert client.get('/gallery/queue').status_code == 302
    login_admin(client)
    assert client.get('/gallery/queue').status_code == 200
    with client.session_transaction() as session:
        csrf = session['csrf']
    response = client.post(f'/gallery/jobs/{ident}/reprocess', data={'csrf': csrf})
    assert response.status_code == 303 and 'reprocess=1' in response.headers['Location']

    job = gallery.import_job(ident)
    assert job['state'] == 'ERROR' and job['count'] == 0 and job['retained'] == 0
    assert 'waiting to fetch the original email PDF again' in job['error']
    assert not gallery.files.path('crops', item_id).exists()
    assert gallery.item(item_id) is None
    route = db.one('SELECT * FROM email_attachment_routes')
    assert route['gallery_delivered'] == 0 and route['print_document'] == 1
    assert db.one('SELECT state FROM processed_messages')['state'] == 'FETCHING'
    assert [row['name'] for row in db.rows('SELECT name FROM commands')] == ['run-now']
    assert db.rows('SELECT * FROM jobs ORDER BY id') == jobs_before
    assert db.rows('SELECT * FROM print_attempts ORDER BY id') == attempts_before

    # The next Gmail handoff uses the same PDF hash and turns this receipt back
    # into a normal gallery WAITING job; no second print job is created here.
    assert gallery.offer(filename, payload, cfg.gallery) == ident
    assert gallery.import_job(ident)['state'] == 'WAITING'
    assert db.rows('SELECT * FROM jobs ORDER BY id') == jobs_before


def test_reprocess_refuses_ambiguous_legacy_filename_without_deleting_gallery(tmp_path):
    env = tmp_path / 'env'; env.write_text('EMAIL_ENABLED=0\n')
    cfg = Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False)
    app = create_app(cfg)
    db = app.extensions['printer_db']
    gallery = app.extensions['printer_gallery']
    filename, payload = 'same-name.pdf', b'one gallery source'
    ident, item_id = seed_gallery(gallery, filename, payload)
    seed_source(db, filename)
    seed_source(db, filename)

    client = app.test_client()
    login_admin(client)
    client.get('/gallery/queue')
    with client.session_transaction() as session:
        csrf = session['csrf']
    response = client.post(f'/gallery/jobs/{ident}/reprocess', data={'csrf': csrf})
    assert response.status_code == 400
    assert b'blocked rather than guessing' in response.data
    assert gallery.import_job(ident)['state'] == 'COMPLETE'
    assert gallery.files.path('crops', item_id).exists()
    assert len(db.rows('SELECT * FROM email_attachment_routes WHERE gallery_delivered=1')) == 2
    assert not db.rows('SELECT * FROM commands')


def test_queue_page_shows_reprocess_only_for_finished_gallery_jobs(tmp_path):
    env = tmp_path / 'env'; env.write_text('EMAIL_ENABLED=0\n')
    cfg = Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False)
    app = create_app(cfg)
    gallery = app.extensions['printer_gallery']
    ident, _ = seed_gallery(gallery, 'finished.pdf', b'finished')
    waiting = hashlib.sha256(b'waiting').hexdigest()
    gallery.repository.enqueue(waiting, 'waiting.pdf')
    client = app.test_client()
    login_admin(client)
    page = client.get('/gallery/queue')
    assert page.status_code == 200
    assert page.data.count(b'>Reprocess</button>') == 1
    assert f'/gallery/jobs/{ident}/reprocess'.encode() in page.data
    assert f'/gallery/jobs/{waiting}/reprocess'.encode() not in page.data


@pytest.fixture
def gallery_admin(tmp_path):
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False))
    gallery = app.extensions['printer_gallery']
    gallery.initialize()
    client = app.test_client()
    login_admin(client)
    with client.session_transaction() as session:
        csrf = session['csrf']
    return app, gallery, client, csrf


def test_generated_sheet_reprocess_cannot_requeue_even_a_matching_email(gallery_admin):
    app, gallery, client, csrf = gallery_admin
    db = app.extensions['printer_db']
    filename = 'MOD-Sheet-2026-09-17.pdf'
    ident, item_id = seed_gallery(gallery, filename, b'generated PDF', origin='morning')
    seed_source(db, filename, sha256=ident)
    before = gallery.item(item_id)
    routes_before = db.rows('SELECT * FROM email_attachment_routes')
    messages_before = db.rows('SELECT * FROM processed_messages')

    response = client.post(f'/gallery/jobs/{ident}/reprocess', data={'csrf': csrf})

    assert response.status_code == 400
    assert 'generated from Salesforce' in response.json['error']
    assert 'Pull Today to Gallery' in response.json['error']
    assert gallery.import_job(ident)['state'] == 'COMPLETE'
    assert gallery.item(item_id) == before
    assert gallery.files.path('crops', item_id).read_bytes() == b'poorly-processed-card'
    assert db.rows('SELECT * FROM email_attachment_routes') == routes_before
    assert db.rows('SELECT * FROM processed_messages') == messages_before
    assert not db.rows('SELECT * FROM commands')


def test_generated_sheet_ui_identifies_source_and_links_to_today_pull(gallery_admin):
    _, gallery, client, _ = gallery_admin
    ident, _ = seed_gallery(gallery, 'generated.pdf', b'generated', origin='morning')
    scan_id, _ = seed_gallery(gallery, 'scan.pdf', b'scan')

    queue = client.get('/gallery/queue').get_data(as_text=True)
    detail = client.get(f'/gallery/jobs/{ident}').get_data(as_text=True)

    assert 'Salesforce placeholders' in queue and 'Email scans' in queue
    assert f'/gallery/jobs/{ident}/reprocess' not in queue
    assert f'/gallery/jobs/{scan_id}/reprocess' in queue
    for page in (queue, detail):
        assert 'href="/mod-sheets/settings">Pull today from Salesforce</a>' in page
    assert 'placeholders until returned scans arrive' in detail
    assert '<details class="gallery-processing-log">' in detail
    assert '<details class="gallery-processing-log" open' not in detail
    assert 'gallery-job-diagnostics' in detail


def test_generated_sheet_ui_works_without_mod_settings_screen(gallery_admin):
    app, gallery, client, _ = gallery_admin
    ident, _ = seed_gallery(gallery, 'generated.pdf', b'generated', origin='morning')
    app.view_functions.pop('mod_sheets.settings_page')
    for path in ('/gallery/queue', f'/gallery/jobs/{ident}'):
        response = client.get(path)
        assert response.status_code == 200
        assert b'Fresh placeholders can be pulled for today' in response.data
        assert b'>Pull today from Salesforce</a>' not in response.data


def test_completed_publication_shows_saved_count_and_skip_reason(gallery_admin):
    _, gallery, client, _ = gallery_admin
    ident = hashlib.sha256(b'skipped generated PDF').hexdigest()
    gallery.repository.enqueue(ident, 'generated.pdf', origin='morning')
    gallery.repository.claim()
    gallery.repository.progress(ident, dict(stage='publish', page=5, pages=5, crops=13,
        message='Saving gallery images — page 5 of 5, 13 images prepared'))
    gallery.repository.finish(ident, [], publication=dict(prepared=13, saved=0,
        skipped_existing=13, skipped_blank_notes=0, needs_notes_review=0))
    job = gallery.import_job(ident)

    queue = client.get('/gallery/queue').get_data(as_text=True)
    detail = client.get(f'/gallery/jobs/{ident}').get_data(as_text=True)
    for current_status in (queue, detail.split('<details class="gallery-processing-log">')[0]):
        assert job['progress']['message'] in current_status
        assert '13 already present' in current_status
        assert '0 saved' in current_status
        assert 'Saving gallery images' not in current_status
    assert '<dt>Cards saved by this job</dt><dd>0</dd>' in detail


def test_old_completed_job_hides_stale_progress_without_guessing_skip_reason(gallery_admin):
    _, gallery, client, _ = gallery_admin
    ident = hashlib.sha256(b'legacy complete job').hexdigest()
    gallery.repository.enqueue(ident, 'legacy.pdf')
    gallery.repository.claim()
    gallery.repository.progress(ident, dict(stage='publish', page=5, pages=5, crops=13,
        message='Saving gallery images — page 5 of 5, 13 images prepared'))
    gallery.repository.finish(ident, [])

    for path in ('/gallery/queue', f'/gallery/jobs/{ident}'):
        page = client.get(path).get_data(as_text=True)
        current_status = page.split('<details class="gallery-processing-log">')[0]
        assert 'Completed. 0 card(s) saved.' in current_status
        assert 'Saving gallery images' not in current_status
        assert 'already present' not in current_status
        assert 'skipped with blank MOD Notes' not in current_status


def test_processing_job_keeps_live_progress(gallery_admin):
    _, gallery, client, _ = gallery_admin
    ident = hashlib.sha256(b'in progress').hexdigest()
    gallery.repository.enqueue(ident, 'processing.pdf')
    gallery.repository.claim()
    message = 'Saving gallery images — page 2 of 5, 6 images prepared'
    gallery.repository.progress(ident, dict(stage='publish', page=2, pages=5, crops=6, message=message))

    for path in ('/gallery/queue', f'/gallery/jobs/{ident}'):
        page = client.get(path).get_data(as_text=True)
        assert message in page.split('<details class="gallery-processing-log">')[0]


def test_unreadable_notes_do_not_offer_identity_approval(gallery_admin):
    _, gallery, client, _ = gallery_admin
    ident = hashlib.sha256(b'notes review scan').hexdigest()
    item_id = hashlib.sha256(b'notes review card').hexdigest()
    gallery.repository.enqueue(ident, 'scan.pdf')
    gallery.repository.finish(ident, [dict(id=item_id, import_id=ident, page=1, part=1,
        filename='scan.pdf', text='Work Order Number: 02000001\nLead Name: Example Customer',
        work_order_number='02000001', work_order_candidates=(),
        document_date='2026-09-17', date_status='printed', bytes=20, created=time.time(),
        mod_notes_status='unknown')])

    page = client.get(f'/gallery/jobs/{ident}').get_data(as_text=True)

    assert 'MOD notes need checking.' in page
    assert 'Work order needs correction.</strong>' not in page
    assert '>Approve to Gallery</button>' not in page
    assert 'need MOD Notes review' not in page  # Older imports have no publication breakdown.
