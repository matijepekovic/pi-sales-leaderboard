"""Gallery boundary regressions. No private customer documents or live services."""
import ast
import base64
import hashlib
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from printer_app.config import Config
from printer_app.db import Database
from printer_app.gallery.bootstrap import build
from printer_app.gallery.policy import GalleryOptions


def item(service, document_date=None, text='Roofing address 12345 Acorn Avenue'):
    ident, iid = 'a' * 64, 'b' * 64
    service.initialize()
    service.repository.enqueue(iid, 'report.pdf')
    service.files.path('crops', ident).write_bytes(b'fixture-png')
    service.repository.finish(iid, [dict(id=ident, import_id=iid, filename='report.pdf',
        page=1, part=1, text=text, document_date=document_date, date_status='printed' if document_date else 'needs-date',
        bytes=11, created=time.time())])
    return ident


def test_search_covers_arbitrary_printed_text_and_notes(tmp_path):
    service = build(tmp_path)
    ident = item(service)
    assert service.search('acorn 12345', 0)['total'] == 1
    assert service.search('NOT (SELECT *)', 0)['total'] == 0
    service.note(ident, 'c' * 32, 'Office', 'Call tomorrow about the blue door')
    service.note(ident, 'c' * 32, 'Office', 'Call tomorrow about the blue door')
    other = build(tmp_path)
    assert other.search('"blue door"', 0)['total'] == 1
    assert len(other.item(ident)['notes']) == 1


def test_dated_expiry_deletes_image_and_notes_not_printer_files(tmp_path):
    service = build(tmp_path)
    ident = item(service, (datetime.now(timezone.utc).date() - timedelta(days=8)).isoformat())
    service.note(ident, 'c' * 32, 'Office', 'Saved note')
    printer_file = tmp_path / 'attachments' / 'original.pdf'
    printer_file.parent.mkdir()
    printer_file.write_bytes(b'printer-owned')
    service.expire(7, 'UTC')
    assert not service.files.path('crops', ident).exists()
    assert service.search('', 0)['total'] == 0
    assert printer_file.read_bytes() == b'printer-owned'
    assert service.repository.imported('b' * 64)


def test_uncertain_date_is_never_guessed_for_deletion(tmp_path):
    service = build(tmp_path)
    ident = item(service)
    service.expire(1, 'UTC')
    assert service.item(ident)
    with pytest.raises(ValueError):
        service.date(ident, 'not-a-date')


def test_disk_cap_and_identical_pdf_receipt(tmp_path):
    service = build(tmp_path)
    opts = GalleryOptions()
    payload = b'fixture-pdf'
    service.offer('one.pdf', payload, opts)
    service.offer('two.pdf', payload, opts)
    assert service.repository.overview()['waiting'] == 1
    with pytest.raises(ValueError):
        service.files.path('crops', '../../printer_app.db')
    with pytest.raises(OSError):
        service.offer('third.pdf', b'other-pdf', replace(opts, max_mb=0))
    actual = service.summary(opts)
    assert actual['storage']['spool'] == len(payload)


@pytest.mark.parametrize('print_match', [False, True])
@pytest.mark.parametrize('gallery_failure', [False, True])
def test_gallery_handoff_does_not_create_cancel_or_duplicate_print_jobs(tmp_path, monkeypatch, print_match, gallery_failure):
    from printer_app.gmail_client import GmailClient
    from printer_app.retention_repository import RetentionRepository
    from printer_app.tests.test_inline_images import leaf, wire
    structure = leaf('APPLICATION', 'PDF', 'report.pdf', 'ATTACHMENT')
    payload = b'original PDF bytes'
    class IMAP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): return 'OK', []
        def select(self, *a, **kw): return 'OK', []
        def response(self, name): return name, [b'123']
        def uid(self, action, *a):
            if action == 'search': return 'OK', [b'1']
            if 'HEADER.FIELDS' in a[1]:
                return 'OK', [(b'x', b'Subject: Redlines\r\nFrom: office@example.test\r\nMessage-ID: <gallery@test>\r\n\r\n')]
            if 'BODYSTRUCTURE' in a[1]: return 'OK', [('1 (BODYSTRUCTURE ' + wire(structure) + ')').encode()]
            return 'OK', [(b'x', base64.b64encode(payload))]
    class Consumer:
        calls = 0
        def offer(self, name, data):
            assert data == payload
            self.calls += 1
            if gallery_failure: raise OSError('Gallery is full')
    monkeypatch.setattr('printer_app.gmail_client.imaplib.IMAP4_SSL', IMAP)
    cfg = Config(data_dir=tmp_path, email_user='fixture@example.test', email_password='fixture',
                 subject_contains='' if print_match else 'Other print mail',
                 gallery=GalleryOptions(enabled=True, print_mode='also-print'))
    db = Database(cfg.db_path)
    consumer = Consumer()
    client = GmailClient(cfg, db, gallery=consumer)
    client.poll()
    client.poll()
    attachments = db.rows('SELECT * FROM attachments')
    assert len(attachments) == int(print_match)
    if print_match: assert Path(attachments[0]['path']).read_bytes() == payload
    assert db.rows('SELECT * FROM jobs') == []
    record = db.one('SELECT * FROM processed_messages')
    assert RetentionRepository(db).download_pending(record['identity']) == gallery_failure
    assert consumer.calls == (2 if gallery_failure else 1)


def test_gallery_settings_and_notes_keep_existing_write_security(tmp_path):
    from printer_app.app import create_app
    from printer_app.settings import SettingsService
    from printer_app.settings_repository import SettingsRepository
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\nEMAIL_MAILBOX=INBOX\n')
    cfg = Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False)
    app = create_app(cfg)
    client = app.test_client()
    assert client.get('/gallery/').status_code == 200
    assert client.get('/gallery/qr.svg').status_code == 200
    current, revision = app.extensions['printer_settings'].read()
    with client.session_transaction() as session: csrf = session['csrf']
    form = dict(SettingsService.public_values(current), csrf=csrf, revision=revision,
                gallery_present='1', GALLERY_ENABLED='1', GALLERY_KEEP_DAYS='30')
    assert client.post('/settings', data=form).status_code == 303
    saved, _ = SettingsService(SettingsRepository(env), cfg).read()
    assert saved.gallery.enabled and saved.gallery.days == 30
    assert saved.print_options == current.print_options
    assert saved.print_schedule == current.print_schedule
    service = build(tmp_path)
    ident = item(service)
    note = dict(csrf=csrf, note_id='d'*32, author='Desk', body='Shared note')
    assert client.post(f'/gallery/api/items/{ident}/notes', data={'body': 'Unsafe'}).status_code == 400
    assert client.post(f'/gallery/api/items/{ident}/notes', data=note, headers={'Origin': 'http://other.example'}).status_code == 403
    assert client.post(f'/gallery/api/items/{ident}/notes', data=note).status_code == 200
    assert client.get('/gallery/api/items?q=shared').json['total'] == 1


def test_gallery_architecture_keeps_ocr_and_sql_out_of_printing():
    root = Path(__file__).resolve().parents[1]
    for name in ('policy.py', 'service.py', 'files.py', 'web.py', 'bootstrap.py'):
        source = (root / 'gallery' / name).read_text()
        imports = [n.module or '' for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)]
        assert not any(i.endswith(('printer', 'gmail_client', 'db')) for i in imports)
        if name != 'files.py': assert 'cv2' not in source
        assert '.execute(' not in source
    cutter = (root / 'gallery/cropper.py').read_text()
    assert 'tesseract' not in cutter.lower() and 'pytesseract' not in cutter.lower()
    unit = (root / 'systemd/printer-app-gallery.service').read_text()
    assert 'PrivateNetwork=true' in unit and 'CPUQuota=25%' in unit and 'User=scoreboard' in unit
    assert 'Requires=' not in unit and 'PartOf=' not in unit

    # Completed pages are a durable processing boundary. Worker restarts must
    # reuse the work directory and the phone UI must not link into certificate setup.
    processing = (root / 'gallery/processing.py').read_text()
    worker = (root / 'gallery/worker.py').read_text()
    gallery_ui = (root / 'static/gallery.js').read_text()
    gallery_template = (root / 'templates/gallery.html').read_text()
    assert "CHECKPOINT = 'checkpoint.json'" in processing
    assert 'save_checkpoint(output, pages, page, manifest, pdf_date)' in processing
    assert 'directory.mkdir(exist_ok=True)' in worker
    assert "work_bytes = gallery.files.work_size(job['id'])" in worker
    assert 'offline-setup' not in gallery_ui
    assert 'galleryOfflineSetup' not in gallery_ui
    assert 'galleryOfflineSetup' not in gallery_template
