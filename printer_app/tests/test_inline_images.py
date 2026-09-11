"""MIME presentation resources must be filtered before entering the print queue."""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import pytest

from printer_app.config import Config
from printer_app.db import Database
from printer_app.gmail_client import GmailClient, attachment_parts, sexpr


def leaf(major='IMAGE', minor='PNG', filename='image001.png', disposition=None, cid=None):
    params = ['NAME', filename] if filename else None
    body = [major, minor, params, cid, None, 'BASE64', 128]
    if major.upper() == 'TEXT':
        body.append(1)  # Text-only line count precedes the extension fields.
    body.extend([None, [disposition, ['FILENAME', filename] if filename else None]
                 if disposition else None])
    return body


def wire(value):
    if isinstance(value, list):
        return '(' + ' '.join(wire(item) for item in value) + ')'
    return 'NIL' if value is None else json.dumps(value)


def selected(tree):
    return list(attachment_parts(sexpr(wire(tree).encode())))


@pytest.mark.parametrize('minor,filename', [
    ('PNG', 'image001.png'), ('PNG', 'image002.png'),
    ('JPEG', 'arbitrary-photo.jpg'), ('GIF', 'footer.gif'), ('SVG+XML', 'logo.svg'),
])
@pytest.mark.parametrize('cid', [None, '<signature@example.test>'])
def test_inline_images_are_ignored_regardless_of_name_or_content_id(minor, filename, cid):
    assert selected(leaf(minor=minor, filename=filename, disposition='inline', cid=cid)) == []


@pytest.mark.parametrize('disposition', [None, 'INLINE', 'ATTACHMENT'])
def test_related_images_are_resources_even_when_their_disposition_says_attachment(disposition):
    html = leaf('TEXT', 'HTML', None)
    image = leaf(disposition=disposition, cid='<image@example.test>')
    assert selected([html, image, 'RELATED', ['TYPE', 'text/html']]) == []


def test_nested_related_images_do_not_renumber_or_hide_real_attachments():
    plain, html = leaf('TEXT', 'PLAIN', None), leaf('TEXT', 'HTML', None)
    alternative = [plain, html, 'ALTERNATIVE']
    related = [alternative, leaf(), leaf(filename='image002.png'), 'RELATED']
    pdf = leaf('APPLICATION', 'PDF', 'report.pdf', 'ATTACHMENT')
    image_attachment = leaf(filename='image001.png', disposition='ATTACHMENT', cid='<separate>')
    parts = selected([related, pdf, image_attachment, 'MIXED'])
    assert [(p['part'], p['filename']) for p in parts] == [('2', 'report.pdf'), ('3', 'image001.png')]


def test_related_start_can_identify_a_nonfirst_root():
    image = leaf(cid='<resource>')
    html = leaf('TEXT', 'HTML', None, cid='<root>')
    assert selected([image, html, 'RELATED', ['START', '<root>']]) == []


def test_a_related_root_image_is_not_mistaken_for_a_signature():
    html = leaf('TEXT', 'HTML', None)
    image = leaf(filename='root.png', cid='<root>')
    parts = selected([html, image, 'RELATED', ['START', '<root>']])
    assert [(p['part'], p['filename']) for p in parts] == [('2', 'root.png')]
    assert selected([image, html, 'RELATED'])[0]['filename'] == 'root.png'


@pytest.mark.parametrize('start', ['<missing>', '<duplicate>'])
def test_unresolved_related_root_does_not_guess_which_images_to_discard(start):
    parts = selected([leaf(cid='<duplicate>'), leaf(filename='image002.png', cid='<duplicate>'),
                      'RELATED', ['START', start]])
    assert [p['filename'] for p in parts] == ['image001.png', 'image002.png']


@pytest.mark.parametrize('filename', ['report.pdf', 'report.xlsx', 'report.xls', 'report.xlsm', 'report.doc'])
def test_named_documents_are_kept_even_when_inline_or_related(filename):
    document = leaf('APPLICATION', 'OCTET-STREAM', filename, 'INLINE', cid='<document>')
    assert selected(document)[0]['filename'] == filename
    assert selected([leaf('TEXT', 'HTML', None), document, 'RELATED'])[0]['filename'] == filename


@pytest.mark.parametrize('disposition', [None, 'ATTACHMENT'])
def test_standalone_named_images_are_not_discarded_on_filename_or_cid_alone(disposition):
    image = leaf(disposition=disposition, cid='<some-id>')
    assert selected(image)[0]['filename'] == 'image001.png'
    assert selected([leaf('TEXT', 'HTML', None), image, 'MIXED'])[0]['part'] == '2'


@pytest.mark.parametrize('include_report', [False, True])
def test_poll_skips_image_downloads_and_deduplicates_the_message(tmp_path, monkeypatch, caplog, include_report):
    html = leaf('TEXT', 'HTML', None)
    related = [html, leaf(disposition='INLINE'), leaf(filename='image002.png', cid='<embedded>'), 'RELATED']
    report = b'original attachment bytes, kept unchanged'
    structure = [related, leaf('APPLICATION', 'PDF', 'report.pdf', 'ATTACHMENT'), 'MIXED'] if include_report else related

    class IMAP:
        queries = []

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
            self.queries.append(query)
            if 'HEADER.FIELDS' in query:
                return 'OK', [(b'x', b'Subject: Report\r\nFrom: sender@example.test\r\nMessage-ID: <inline@test>\r\n\r\n')]
            if 'BODYSTRUCTURE' in query:
                return 'OK', [('7 (BODYSTRUCTURE ' + wire(structure) + ')').encode()]
            # Never fetch an embedded image (not even to inspect/decode it).
            assert include_report and query == '(BODY.PEEK[2])'
            return 'OK', [(b'x', base64.b64encode(report))]

    monkeypatch.setattr('printer_app.gmail_client.imaplib.IMAP4_SSL', IMAP)
    cfg = Config(data_dir=tmp_path, email_user='fixture@example.test', email_password='fixture-password')
    db = Database(cfg.db_path)
    caplog.set_level(logging.INFO, logger='printer_app.gmail_client')
    assert GmailClient(cfg, db).poll() == 1
    attachments = db.rows('SELECT * FROM attachments')
    assert [a['filename'] for a in attachments] == (['report.pdf'] if include_report else [])
    if include_report:
        assert Path(attachments[0]['path']).read_bytes() == report
        assert attachments[0]['error'] == ''
    assert db.rows('SELECT * FROM jobs') == []  # Collection never invents an image/error job.
    assert db.one('SELECT state FROM processed_messages')['state'] == 'COMPLETE'
    assert caplog.text.count('Skipped embedded email image:') == 2
    assert cfg.email_password not in caplog.text
    queries = list(IMAP.queries)
    assert GmailClient(cfg, Database(cfg.db_path)).poll() == 0
    assert IMAP.queries == queries
    assert len(db.rows('SELECT * FROM attachments')) == len(attachments)
