"""Gallery Queue reprocess discards gallery output and redelivers from email only."""
import hashlib
import time

from printer_app.app import create_app
from printer_app.config import Config


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


def seed_gallery(gallery, filename, payload):
    gallery.initialize()
    ident = hashlib.sha256(payload).hexdigest()
    gallery.repository.enqueue(ident, filename)
    item_id = hashlib.sha256((ident + ':1:1').encode()).hexdigest()
    gallery.files.path('crops', item_id).write_bytes(b'poorly-processed-card')
    gallery.repository.finish(ident, [dict(id=item_id, import_id=ident, page=1, part=1,
        filename=filename, text='Lead Name: OLD RESULT', document_date='2026-09-17',
        date_status='printed', bytes=21, created=time.time(), recognition_revision=1)])
    gallery.note(item_id, 'e' * 32, 'Office', 'delete this with the bad card')
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

    client = app.test_client(); client.get('/gallery/queue')
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
    page = app.test_client().get('/gallery/queue')
    assert page.status_code == 200
    assert page.data.count(b'>Reprocess</button>') == 1
    assert f'/gallery/jobs/{ident}/reprocess'.encode() in page.data
    assert f'/gallery/jobs/{waiting}/reprocess'.encode() not in page.data
