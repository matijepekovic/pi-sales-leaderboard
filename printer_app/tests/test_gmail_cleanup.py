"""Stateful IMAP fake: only selected expired inbox messages may be purged."""
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from printer_app.config import Config
from printer_app.db import Database
from printer_app.gmail_cleanup import GmailCleanup
from printer_app.retention import RetentionService
from printer_app.retention_files import RetentionFiles
from printer_app.retention_policy import RetentionPolicy, mailbox_scope
from printer_app.retention_repository import RetentionRepository

NOW = datetime(2026, 9, 11, 3, tzinfo=timezone.utc).timestamp()
OLD = '01-Sep-2026 03:00:00 +0000'
NEW = '10-Sep-2026 03:00:00 +0000'
BOUNDARY = '04-Sep-2026 03:00:00 +0000'
TRASH = '[Gmail]/Papierkorb'


class Mailbox:
    capabilities = b'IMAP4rev1 MOVE UIDPLUS X-GM-EXT-1'

    def __init__(self):
        self.folders = {'INBOX': {'1': ('11', OLD), '2': ('22', NEW), '3': ('33', BOUNDARY)},
                        TRASH: {'99': ('99', OLD)}, 'Archive': {'44': ('44', OLD)}}
        self.selected = None
        self.calls = []
        self.deleted = {'99'}  # Another client's already-deleted Trash item.
        self.fail_after_move = False
        self.assert_intent = lambda: None

    def login(self, *args): return 'OK', []
    def logout(self): return 'BYE', []
    def capability(self): return 'OK', [self.capabilities]
    def response(self, name): return name, [b'123']
    def list(self):
        return 'OK', [b'(\\HasNoChildren) "/" "INBOX"',
                      b'(\\Trash) "/" "[Gmail]/Papierkorb"',
                      b'(\\All) "/" "[Gmail]/All Mail"']

    def select(self, mailbox, readonly=True):
        self.selected = json.loads(mailbox)
        assert self.selected in self.folders
        return 'OK', []

    def uid(self, action, *args):
        action = action.upper()
        self.calls.append((self.selected, action, args))
        folder = self.folders[self.selected]
        if action == 'SEARCH':
            if args[1] == 'BEFORE':
                ids = list(folder)  # Include boundary candidates deliberately.
            else:
                assert args[1] == 'X-GM-MSGID'
                ids = [uid for uid, (key, _) in folder.items() if key == args[2]]
            return 'OK', [' '.join(ids).encode()]
        if action == 'FETCH':
            if 'HEADER.FIELDS' in args[1]:
                key = folder[args[0]][0]
                return 'OK', [(b'1 (BODY[HEADER.FIELDS (MESSAGE-ID)] {99}',
                              f'Message-ID: <{key}@fixture>\r\nDate: 1 Jan 1900 00:00:00 +0000\r\n\r\n'.encode()), b')']
            return 'OK', [f'1 (UID {uid} X-GM-MSGID {folder[uid][0]} INTERNALDATE "{folder[uid][1]}")'.encode()
                          for uid in args[0].split(',') if uid in folder]
        if action == 'MOVE':
            self.assert_intent()
            assert self.selected == 'INBOX' and json.loads(args[1]) == TRASH
            self.folders[TRASH]['201'] = folder.pop(args[0])
            if self.fail_after_move:
                self.fail_after_move = False
                raise OSError('Connection lost after successful move')
            return 'OK', []
        if action == 'STORE':
            assert self.selected == TRASH and args[1:] == ('+FLAGS.SILENT', '(\\Deleted)')
            self.deleted.add(args[0])
            return 'OK', []
        if action == 'EXPUNGE':
            assert len(args) == 1 and args[0].isdigit() and self.selected == TRASH
            assert args[0] in self.deleted
            folder.pop(args[0], None)
            return 'OK', []
        raise AssertionError(action)

    def expunge(self): raise AssertionError('Global EXPUNGE is prohibited')
    def close(self): raise AssertionError('Implicit expunge through CLOSE is prohibited')


@pytest.fixture
def cleanup(tmp_path, monkeypatch):
    backend = Mailbox()
    monkeypatch.setattr('printer_app.gmail_cleanup.imaplib.IMAP4_SSL', lambda *a, **kw: backend)
    monkeypatch.setattr('printer_app.retention.time.time', lambda: NOW)
    cfg = Config(data_dir=tmp_path, email_user='fixture@example.test', email_password='fake-only',
                 subject_contains='This filter must NOT affect cleanup', from_contains='neither@filter.test',
                 retention=RetentionPolicy(True, 7, True, mailbox_scope('fixture@example.test', 'INBOX')))
    repo = RetentionRepository(Database(cfg.db_path))
    service = RetentionService(cfg, repo, RetentionFiles(cfg.data_dir), GmailCleanup)
    backend.assert_intent = lambda: require_intent(repo, cfg)
    return cfg, repo, service, backend


def require_intent(repo, cfg):
    assert [m.key for m in repo.pending_deletions(cfg.email_user, cfg.mailbox, NOW)] == ['11']


def test_all_old_inbox_mail_only_no_filters_threads_or_trash_empty(cleanup):
    cfg, repo, service, backend = cleanup
    service.run()
    assert not repo.state()['error']
    assert set(backend.folders['INBOX']) == {'2', '3'}  # Recent and exact boundary preserved.
    assert backend.folders[TRASH] == {'99': ('99', OLD)}
    assert backend.folders['Archive'] == {'44': ('44', OLD)}
    assert repo.state()['emails'] == 1
    assert repo.pending_deletions(cfg.email_user, cfg.mailbox, NOW) == []
    assert [c[2] for c in backend.calls if c[1] == 'EXPUNGE'] == [('201',)]
    assert all('X-GM-THRID' not in str(c) for c in backend.calls)


def test_crash_after_move_retries_only_same_message_identity(cleanup):
    cfg, repo, service, backend = cleanup
    backend.fail_after_move = True
    service.run()
    assert repo.state()['error'] and backend.folders[TRASH]['201'][0] == '11'
    assert repo.pending_deletions(cfg.email_user, cfg.mailbox, NOW)
    # A fresh service resumes the durable outbox; no new inbox selection needed.
    RetentionService(cfg, RetentionRepository(Database(cfg.db_path)), RetentionFiles(cfg.data_dir), GmailCleanup).run()
    assert not repo.state()['error']
    assert backend.folders[TRASH] == {'99': ('99', OLD)}
    assert len([c for c in backend.calls if c[1] == 'MOVE']) == 1


def test_no_remote_mutation_without_safe_capabilities(cleanup):
    _, repo, service, backend = cleanup
    backend.capabilities = b'IMAP4rev1 X-GM-EXT-1 MOVE'
    service.run()
    assert repo.state()['error']
    assert not [c for c in backend.calls if c[1] in ('MOVE', 'STORE', 'EXPUNGE')]


def test_disabling_mid_operation_stops_the_purge_and_keeps_intent(cleanup):
    cfg, repo, _, backend = cleanup
    def active(): return '1' in backend.folders['INBOX']
    RetentionService(cfg, repo, RetentionFiles(cfg.data_dir), GmailCleanup, active).run()
    assert backend.folders[TRASH]['201'][0] == '11'
    assert not [c for c in backend.calls if c[1] in ('STORE', 'EXPUNGE')]
    assert repo.pending_deletions(cfg.email_user, cfg.mailbox, NOW)


def test_all_mail_is_not_an_allowed_cleanup_source(cleanup):
    cfg, _, _, backend = cleanup
    cfg = replace(cfg, mailbox='[Gmail]/All Mail', retention=replace(cfg.retention,
        email_scope=mailbox_scope(cfg.email_user, '[Gmail]/All Mail')))
    with pytest.raises(ValueError):
        with GmailCleanup(cfg, lambda: True):
            raise AssertionError('All Mail must never open for cleanup')
    assert backend.calls == []


def test_new_account_or_label_does_not_inherit_deletion_consent(cleanup):
    cfg, _, _, backend = cleanup
    cfg = replace(cfg, email_user='different@example.test')
    with pytest.raises(ValueError):
        with GmailCleanup(cfg, lambda: True):
            pass
    assert backend.calls == []
