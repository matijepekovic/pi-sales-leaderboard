"""Gallery-only routing cannot fall through to physical printing, including on retry."""
import ast
import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest

from printer_app.attachment_routing import AttachmentRouter
from printer_app.attachment_routing_repository import AttachmentRoutingRepository
from printer_app.config import Config
from printer_app.db import Database
from printer_app.gallery.policy import GalleryOptions
from printer_app.gmail_client import GmailClient
from printer_app.retention_repository import RetentionRepository
from printer_app.tests.test_inline_images import leaf, wire


class Consumer:
    def __init__(self, failure=None):
        self.failure, self.calls = failure, []

    def offer(self, filename, data):
        self.calls.append((filename, data))
        if self.failure:
            raise self.failure


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    """Two PDFs and a workbook from one sender; nothing here contacts real Gmail."""
    payloads = {'1': b'gallery source', '2': b'normal PDF', '3': b'normal workbook'}

    class IMAP:
        fetches = []
        subject = 'Daily packet'
        bad_structure = False
        failure = None
        bad_encoding = False

        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def login(self, *args): return 'OK', []
        def select(self, mailbox, readonly):
            assert readonly
            return 'OK', []
        def response(self, name): return name, [b'123']

        def uid(self, action, *args):
            if action == 'search': return 'OK', [b'7']
            assert action == 'fetch'
            query = args[1]
            self.fetches.append(query)
            if 'HEADER.FIELDS' in query:
                message = f'Subject: {self.subject}\r\nFrom: same@example.test\r\nMessage-ID: <routing@test>\r\n\r\n'
                return 'OK', [(b'x', message.encode())]
            if 'BODYSTRUCTURE' in query:
                if self.bad_structure: return 'OK', [b'7 (NO-STRUCTURE)']
                children = [leaf('APPLICATION', 'PDF', 'Oly_REDlines.pdf', 'ATTACHMENT'),
                            leaf('APPLICATION', 'PDF', 'Sales.pdf', 'ATTACHMENT'),
                            leaf('APPLICATION', 'OCTET-STREAM', 'Sales.xlsx', 'ATTACHMENT'), 'MIXED']
                return 'OK', [('7 (BODYSTRUCTURE ' + wire(children) + ')').encode()]
            part = query.removeprefix('(BODY.PEEK[').removesuffix('])')
            assert part in payloads
            if part == '1' and self.failure: raise self.failure
            encoded = b'!invalid-base64!' if part == '1' and self.bad_encoding else base64.b64encode(payloads[part])
            return 'OK', [(b'x', encoded)]

    monkeypatch.setattr('printer_app.gmail_client.imaplib.IMAP4_SSL', IMAP)
    cfg = Config(data_dir=tmp_path, email_user='fixture@example.test', email_password='private-fixture',
                 gallery=GalleryOptions(enabled=True, subject='', filename='redlines'))
    db = Database(cfg.db_path)
    return cfg, db, IMAP, payloads


def attachment_names(db):
    return [r['filename'] for r in db.rows('SELECT filename FROM attachments ORDER BY id')]


def test_mixed_email_routes_only_matching_pdf_to_gallery(inbox):
    cfg, db, imap, payloads = inbox
    consumer = Consumer()
    assert GmailClient(cfg, db, gallery=consumer).poll() == 1
    assert consumer.calls == [('Oly_REDlines.pdf', payloads['1'])]
    assert attachment_names(db) == ['Sales.pdf', 'Sales.xlsx']
    for row in db.rows('SELECT * FROM attachments'):
        assert Path(row['path']).read_bytes() in (payloads['2'], payloads['3'])
        assert row['error'] == ''
    excluded = db.one("SELECT * FROM email_attachment_routes WHERE part='1'")
    assert not excluded['print_document'] and excluded['gallery_delivered']
    assert db.rows('SELECT * FROM jobs') == []
    queries = list(imap.fetches)
    assert GmailClient(cfg, Database(cfg.db_path), gallery=consumer).poll() == 0
    assert imap.fetches == queries and len(consumer.calls) == 1


@pytest.mark.parametrize('kind', ['handoff', 'missing-consumer', 'download', 'decode', 'mime'])
def test_failures_never_generate_original_or_error_sheet(inbox, kind):
    cfg, db, imap, _ = inbox
    consumer = Consumer(OSError('Gallery disk full: private-fixture')) if kind == 'handoff' else Consumer()
    if kind == 'missing-consumer': consumer = None
    if kind == 'download': imap.failure = OSError('Offline')
    if kind == 'decode': imap.bad_encoding = True
    if kind == 'mime': imap.bad_structure = True
    GmailClient(cfg, db, gallery=consumer).poll()
    assert attachment_names(db) == ([] if kind == 'mime' else ['Sales.pdf', 'Sales.xlsx'])
    assert db.rows('SELECT * FROM jobs') == []
    assert db.rows('SELECT * FROM print_attempts') == []
    record = db.one('SELECT * FROM processed_messages')
    assert RetentionRepository(db).download_pending(record['identity'])
    failures = AttachmentRoutingRepository(db).failures()
    assert failures and 'private-fixture' not in json.dumps(failures)
    assert not list(cfg.data_dir.rglob('error.pdf'))


@pytest.mark.parametrize('interrupted_mime', [False, True])
def test_restart_and_changed_selectors_cannot_convert_exclusion_into_print(inbox, interrupted_mime):
    cfg, db, imap, _ = inbox
    imap.bad_structure = interrupted_mime
    consumer = Consumer(OSError('Full'))
    GmailClient(cfg, db, gallery=consumer).poll()
    imap.bad_structure = False
    # Turn imports off after the failure. No PDF is allowed to fall into printing.
    disabled = replace(cfg, gallery=replace(cfg.gallery, enabled=False, filename='different', print_mode='also-print'))
    consumer.failure = None
    calls = len(consumer.calls)
    GmailClient(disabled, Database(cfg.db_path), gallery=consumer).poll()
    assert len(consumer.calls) == calls
    assert attachment_names(db) == ['Sales.pdf', 'Sales.xlsx']
    assert db.one('SELECT state FROM processed_messages')['state'] == 'FETCHING'
    # Restoring imports delivers the frozen gallery-only decision, not new print rules.
    enabled = replace(disabled, gallery=replace(disabled.gallery, enabled=True))
    GmailClient(enabled, Database(cfg.db_path), gallery=consumer).poll()
    assert len(consumer.calls) == calls + 1
    assert attachment_names(db) == ['Sales.pdf', 'Sales.xlsx']
    assert db.one('SELECT state FROM processed_messages')['state'] == 'COMPLETE'
    assert AttachmentRoutingRepository(db).failures() == []
    assert 'private-fixture' not in db.one('SELECT policy FROM email_routing_policies')['policy']


@pytest.mark.parametrize('print_match', [False, True])
def test_both_mode_still_requires_normal_print_match(inbox, print_match):
    cfg, db, _, _ = inbox
    cfg = replace(cfg, subject_contains='' if print_match else 'different subject',
                  gallery=replace(cfg.gallery, print_mode='also-print'))
    consumer = Consumer()
    GmailClient(cfg, db, gallery=consumer).poll()
    assert attachment_names(db) == (['Oly_REDlines.pdf', 'Sales.pdf', 'Sales.xlsx'] if print_match else [])
    assert len(consumer.calls) == 1


def test_disabled_gallery_preserves_normal_rules_for_new_emails(inbox):
    cfg, db, _, _ = inbox
    consumer = Consumer()
    GmailClient(replace(cfg, gallery=replace(cfg.gallery, enabled=False)), db, gallery=consumer).poll()
    assert attachment_names(db) == ['Oly_REDlines.pdf', 'Sales.pdf', 'Sales.xlsx']
    assert not consumer.calls


def test_subject_only_excludes_pdfs_not_excel_in_same_email(inbox):
    cfg, db, imap, _ = inbox
    imap.subject = 'Fw: Redlines today'
    cfg = replace(cfg, gallery=GalleryOptions(enabled=True))
    consumer = Consumer()
    GmailClient(cfg, db, gallery=consumer).poll()
    assert len(consumer.calls) == 2
    assert attachment_names(db) == ['Sales.xlsx']


def test_existing_print_jobs_and_receipts_are_not_cancelled(inbox):
    cfg, db, _, _ = inbox
    # Simulate the already-collected PDF in the old dual-route version.
    consumer = Consumer(OSError('Full'))
    original = replace(cfg, gallery=replace(cfg.gallery, print_mode='also-print'))
    GmailClient(original, db, gallery=consumer).poll()
    attachment = db.one("SELECT * FROM attachments WHERE filename='Oly_REDlines.pdf'")
    jid = db.create_job(attachment['id'], 'pdf', cfg.print_options.snapshot())
    before = db.job(jid)
    paths = {r['id']: Path(r['path']).read_bytes() for r in db.rows('SELECT * FROM attachments')}
    consumer.failure = None
    GmailClient(cfg, Database(cfg.db_path), gallery=consumer).poll()
    assert db.job(jid) == before
    assert {r['id']: Path(r['path']).read_bytes() for r in db.rows('SELECT * FROM attachments')} == paths
    assert len(db.rows('SELECT * FROM jobs')) == 1


def test_routing_receipts_cleanup_with_parent_without_touching_replay_marker(inbox):
    cfg, db, imap, _ = inbox
    imap.subject = 'Redlines'
    cfg = replace(cfg, subject_contains='unmatched', gallery=GalleryOptions(enabled=True))
    GmailClient(cfg, db, gallery=Consumer()).poll()
    record = db.one('SELECT * FROM processed_messages')
    assert db.rows('SELECT * FROM email_attachment_routes')
    RetentionRepository(db).forget_message(record['id'], record['identity'])
    assert not db.rows('SELECT * FROM email_attachment_routes')
    assert not db.rows('SELECT * FROM email_routing_policies')
    assert RetentionRepository(db).seen(record['identity'])


def test_matching_options_are_literal_combined_and_require_a_selector():
    opts = GalleryOptions().apply({'GALLERY_ENABLED': '1', 'GALLERY_FILENAME_CONTAINS': 'redlines'})
    router = AttachmentRouter('', '', opts)
    assert router.attachment('REDLINES', 'office', 'REDLINES.PDF').import_document
    assert not router.attachment('Other', 'office', 'redlines.pdf').import_document
    assert not router.attachment('redlines', 'office', 'other.pdf').import_document
    assert not router.attachment('redlines', 'office', 'redlines.xlsx').import_document
    assert router.unreadable_message('redlines', 'office').print_document is False
    sender_only = replace(opts, subject='', filename='', sender='office')
    assert not sender_only.matches('anything', 'office')
    with pytest.raises(ValueError): sender_only.apply({})
    with pytest.raises(ValueError): opts.apply({'GALLERY_PRINT_MODE': 'nonsense'})
    assert opts.apply({'GALLERY_PRINT_MODE': 'also-print'}).environment()['GALLERY_PRINT_MODE'] == 'also-print'
    only_file = opts.apply({'GALLERY_SUBJECT_CONTAINS': '', 'GALLERY_FROM_CONTAINS': 'office'})
    assert only_file.matches_pdf('anything', 'office', 'redlines.pdf')
    assert not only_file.matches_pdf('anything', 'someone else', 'redlines.pdf')


def test_settings_save_mode_and_filename_with_no_printer_changes(tmp_path):
    from printer_app.app import create_app
    from printer_app.settings import SettingsService
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\nGALLERY_ENABLED=1\nGALLERY_SUBJECT_CONTAINS=redlines\n')
    cfg = Config(data_dir=tmp_path, env_file=env, secret_key='s' * 64, email_enabled=False)
    app = create_app(cfg)
    client = app.test_client()
    page = client.get('/settings')
    assert b'Gallery only' in page.data and b'GALLERY_FILENAME_CONTAINS' in page.data
    service = app.extensions['printer_settings']
    current, revision = service.read()
    assert current.gallery.print_mode == 'gallery-only'  # Upgrade default; gallery enable state preserved.
    with client.session_transaction() as session: csrf = session['csrf']
    form = dict(SettingsService.public_values(current), csrf=csrf, revision=revision,
                gallery_present='1', GALLERY_PRINT_MODE='also-print',
                GALLERY_FILENAME_CONTAINS='redlines', GALLERY_SUBJECT_CONTAINS='')
    assert client.post('/settings', data=form, headers={'Origin': 'http://elsewhere.test'}).status_code == 403
    assert client.post('/settings', data={k:v for k,v in form.items() if k != 'csrf'}).status_code == 400
    assert client.post('/settings', data=form).status_code == 303
    saved, revision = service.read()
    assert saved.gallery.filename == 'redlines' and saved.gallery.print_mode == 'also-print'
    assert saved.print_options == current.print_options and saved.print_schedule == current.print_schedule
    assert saved.retention == current.retention and saved.subject_contains == current.subject_contains
    before = env.read_bytes()
    form.update(revision=revision, GALLERY_PRINT_MODE='bad')
    assert client.post('/settings', data=form).status_code == 400
    assert env.read_bytes() == before


def test_routing_owner_has_no_io_and_consumer_availability_is_not_a_selector():
    root = Path(__file__).resolve().parents[1]
    pure = (root / 'attachment_routing.py').read_text()
    imports = [n.module or '' for n in ast.walk(ast.parse(pure)) if isinstance(n, ast.ImportFrom)]
    assert imports == ['dataclasses', 'typing', 'gallery.policy']
    assert '.execute(' not in pure and 'sqlite3' not in pure and 'subprocess' not in pure
    source = (root / 'gmail_client.py').read_text()
    assert 'self.gallery.matches' not in source
    assert source.index('self.routes.remember(record') < source.index('to_print = bool')
    for name in ('worker.py', 'printer.py', 'gallery/worker.py', 'gallery/processing.py'):
        assert 'email_attachment_routes' not in (root / name).read_text()
