"""Oversized mail attachments download normally; size must not select an error job."""
from __future__ import annotations

import base64
import hashlib
import io
import quopri
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from printer_app.config import Config
from printer_app.db import Database
from printer_app.gmail_client import GmailClient


def received_pdf(padding=20000):
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=792, height=612)
    stream = io.BytesIO()
    writer.write(stream)
    # Valid PDF comments keep the report readable while exercising the old caps.
    return stream.getvalue() + b'\n%' + b'oversized-report ' * (padding // 17) + b'\n'


def fake_mail(monkeypatch, encoding, encoded, declared_size):
    class IMAP:
        body_queries = []
        fail_body = False

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, *args):
            return 'OK', []

        def select(self, mailbox, readonly):
            assert readonly is True
            return 'OK', []

        def response(self, name):
            return name, [b'123']

        def uid(self, action, *args):
            if action == 'search':
                return 'OK', [b'7']
            assert action == 'fetch'
            query = args[1]
            if 'HEADER.FIELDS' in query:
                return 'OK', [(b'x', b'Subject: Report\r\nFrom: sender@example.test\r\nMessage-ID: <oversized@test>\r\n\r\n')]
            if 'BODYSTRUCTURE' in query:
                structure = f'7 (BODYSTRUCTURE ("APPLICATION" "PDF" NIL NIL NIL "{encoding}" {declared_size} NIL ("ATTACHMENT" ("FILENAME" "report.pdf"))))'
                return 'OK', [structure.encode()]
            self.body_queries.append(query)
            assert query == '(BODY.PEEK[1])', 'Download the complete part, never a size-limited prefix'
            if self.fail_body:
                raise OSError('Simulated connection failure')
            return 'OK', [(b'x', encoded)]

    monkeypatch.setattr('printer_app.gmail_client.imaplib.IMAP4_SSL', IMAP)
    return IMAP


def configured(tmp_path):
    cfg = Config(data_dir=tmp_path / 'private', email_user='test@example.test',
                 email_password='test-only-not-a-secret', attachment_limit=128)
    return cfg, Database(cfg.db_path)


@pytest.mark.parametrize('encoding', ['BASE64', 'QUOTED-PRINTABLE', '7BIT', '8BIT', 'BINARY', ''])
@pytest.mark.parametrize('declared_size', [1, 100_000_000], ids=['underreported-size', 'oversized-metadata'])
def test_oversized_attachment_is_downloaded_whole(tmp_path, monkeypatch, caplog, encoding, declared_size):
    cfg, db = configured(tmp_path)
    payload = received_pdf()
    encoded = base64.encodebytes(payload) if encoding == 'BASE64' else quopri.encodestring(payload) if encoding == 'QUOTED-PRINTABLE' else payload
    assert len(encoded) > cfg.attachment_limit * 3 + 8192
    imap = fake_mail(monkeypatch, encoding, encoded, declared_size)
    assert GmailClient(cfg, db).poll() == 1
    attachment = db.one('SELECT * FROM attachments')
    assert attachment['state'] == 'PENDING'
    assert not attachment['error']
    assert Path(attachment['path']).read_bytes() == payload
    assert attachment['sha256'] == hashlib.sha256(payload).hexdigest()
    assert len(PdfReader(attachment['path']).pages) == 2
    assert db.one('SELECT state FROM processed_messages')['state'] == 'COMPLETE'
    assert imap.body_queries == ['(BODY.PEEK[1])']
    assert 'Oversized attachment downloaded' in caplog.text
    assert cfg.email_password not in caplog.text


def test_decoded_size_above_threshold_is_not_a_rejection(tmp_path, monkeypatch):
    cfg, db = configured(tmp_path)
    payload = received_pdf(padding=0)
    encoded = base64.b64encode(payload)
    assert cfg.attachment_limit < len(payload) < cfg.attachment_limit * 3 + 8192
    fake_mail(monkeypatch, 'BASE64', encoded, len(encoded))
    assert GmailClient(cfg, db).poll() == 1
    attachment = db.one('SELECT * FROM attachments')
    assert not attachment['error']
    assert Path(attachment['path']).read_bytes() == payload


def test_oversized_download_stays_deduplicated_after_restart(tmp_path, monkeypatch):
    cfg, db = configured(tmp_path)
    payload = received_pdf()
    imap = fake_mail(monkeypatch, 'BINARY', payload, len(payload))
    assert GmailClient(cfg, db).poll() == 1
    restarted = GmailClient(cfg, Database(cfg.db_path))
    assert restarted.poll() == 0
    assert len(db.rows('SELECT * FROM attachments')) == 1
    assert len(imap.body_queries) == 1


@pytest.mark.parametrize('encoding,encoded', [('BASE64', b'not valid base64!!'), ('UNKNOWN', b'report')])
def test_real_decoding_errors_are_still_recorded(tmp_path, monkeypatch, encoding, encoded):
    cfg, db = configured(tmp_path)
    fake_mail(monkeypatch, encoding, encoded, 100_000_000)
    assert GmailClient(cfg, db).poll() == 1
    attachment = db.one('SELECT * FROM attachments')
    assert attachment['state'] == 'PENDING'
    assert attachment['error']
    assert 'SIZE LIMIT' not in attachment['error']
    assert not attachment['path']


def test_interrupted_oversized_download_remains_retryable(tmp_path, monkeypatch):
    cfg, db = configured(tmp_path)
    payload = received_pdf()
    imap = fake_mail(monkeypatch, 'BINARY', payload, len(payload))
    imap.fail_body = True
    with pytest.raises(OSError, match='connection failure'):
        GmailClient(cfg, db).poll()
    assert db.one('SELECT state FROM processed_messages')['state'] == 'FETCHING'
    assert not db.rows('SELECT * FROM attachments')
    imap.fail_body = False
    assert GmailClient(cfg, Database(cfg.db_path)).poll() == 1
    assert Path(db.one('SELECT * FROM attachments')['path']).read_bytes() == payload
