"""Outlook mailbox trial: real MIME parsing, read-only transport and sandbox isolation."""
from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
import stat
import threading
import time

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.outlook_sandbox.adapter import OutlookImapAdapter
from printer_app.outlook_sandbox.repository import OutlookConfig, SandboxError, SandboxRepository
from printer_app.outlook_sandbox.service import OutlookSandboxService
from printer_app.tests.auth_helpers import login_admin


TENANT = '11111111-1111-4111-8111-111111111111'
CLIENT = '22222222-2222-4222-8222-222222222222'


def values(**overrides):
    data = dict(tenant_id=TENANT, client_id=CLIENT,
                mailbox='reports@example.test', folder='Printer')
    data.update(overrides)
    return data


def test_configuration_rejects_bad_tenant_mailbox_and_mailbox_injection():
    cfg = OutlookConfig.from_form(values())
    assert cfg.folder == 'Printer' and cfg.identity()[0] == TENANT
    for bad in [
        dict(tenant_id='common'), dict(client_id='no-app'),
        dict(mailbox='not-an-email'), dict(mailbox='a@b.test\x01injected'), dict(folder=''),
        dict(folder='INBOX\r\nSTORE 1'), dict(folder='INBOX\x00Printer'),
        dict(folder='a' * 201),
    ]:
        with pytest.raises(SandboxError):
            OutlookConfig.from_form(values(**bad))


def test_private_storage_preserves_gmail_and_invalidates_credentials_on_identity_change(tmp_path):
    repo = SandboxRepository(tmp_path)
    cfg = OutlookConfig.from_form(values())
    repo.save_config(cfg)
    repo.write_tokens('sensitive-token-cache')
    assert repo.read_config() == cfg
    assert stat.S_IMODE(repo.tokens_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(repo.settings_path.stat().st_mode) == 0o600
    repo.save_config(OutlookConfig.from_form(values(folder='INBOX/Printer')))
    assert repo.read_tokens() == 'sensitive-token-cache'
    repo.save_config(OutlookConfig.from_form(values(mailbox='new@example.test')))
    assert repo.read_tokens() == ''
    assert not (tmp_path / 'attachments').exists()
    assert not (tmp_path / 'printer_app.db').exists()


def test_staged_files_are_private_and_non_traversable(tmp_path):
    repo = SandboxRepository(tmp_path)
    cfg = OutlookConfig.from_form(values())
    sid = repo.stage_id(cfg, '19', '100')
    files = repo.save_attachments(sid, [('../../report.pdf', b'%PDF-test'), ('report.pdf', b'data')])
    assert len(files) == 2
    assert files[0]['name'] == '01-report.pdf'
    path, name = repo.file(sid, 0)
    assert path.read_bytes() == b'%PDF-test' and name == '01-report.pdf'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    for bad in ('../private', 'x' * 64):
        with pytest.raises(SandboxError):
            repo.file(bad, 0)
    with pytest.raises(SandboxError):
        repo.file(sid, 55)
    sid_long = repo.stage_id(cfg, '19', '101')
    repo.save_attachments(sid_long, [('x' * 149 + '.pdf', b'safe')])
    assert repo.file(sid_long, 0)[0].read_bytes() == b'safe'


def sample_email():
    email = EmailMessage()
    email['Subject'] = 'Weekly Summary'
    email['From'] = 'daily@example.test'
    email['Date'] = 'Fri, 23 Oct 2026 11:00:00 +0000'
    email.set_content('Report attached')
    email.add_attachment(b'%PDF-TEST', maintype='application', subtype='pdf',
                         filename='Weekly report.pdf')
    return email.as_bytes()


class FakeImap:
    instances = []

    def __init__(self, *args, **kwargs):
        self.commands = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def authenticate(self, method, callback):
        self.commands.append(('AUTH', method, callback(b'')))
        return ('OK', [b'Authenticated'])

    def select(self, folder, readonly=False):
        self.commands.append(('SELECT', folder, readonly))
        return ('OK', [b'2'])

    def response(self, key):
        return ('UIDVALIDITY', [b'99'])

    def list(self):
        self.commands.append(('LIST',))
        return ('OK', [b'(\\HasNoChildren) "/" "INBOX"',
                        b'(\\HasNoChildren) "/" "Printer"'])

    def uid(self, op, *args):
        self.commands.append((op, *args))
        if op == 'search':
            return ('OK', [b'101 102'])
        if b'HEADER' in args[-1].encode('ascii'):
            raw = b'Subject: Weekly Summary\r\nFrom: daily@example.test\r\n\r\n'
        else:
            raw = sample_email()
        return ('OK', [(b'1 (BODY[] {1}', raw), b')'])


def test_exchange_imap_only_selects_readonly_and_reads_actual_attachments(monkeypatch):
    monkeypatch.setattr('printer_app.outlook_sandbox.adapter.imaplib.IMAP4_SSL', FakeImap)
    FakeImap.instances.clear()
    adapter = OutlookImapAdapter(OutlookConfig.from_form(values()), 'never-share-this-token')
    assert adapter.folders() == ['INBOX', 'Printer']
    messages = adapter.recent()
    assert messages['uidvalidity'] == '99'
    assert [x['uid'] for x in messages['messages']] == ['102', '101']
    assert messages['messages'][0]['subject'] == 'Weekly Summary'
    validity, attachments = adapter.attachments('102')
    assert validity == '99'
    assert attachments == [('Weekly report.pdf', b'%PDF-TEST')]
    with pytest.raises(SandboxError):
        adapter.attachments('102\r\nSTORE')
    for item in FakeImap.instances:
        assert not any(command[0] in ('STORE', 'EXPUNGE', 'COPY') for command in item.commands)
        for command in item.commands:
            if command[0] == 'SELECT':
                assert command == ('SELECT', '"Printer"', True)
            if command[0] == 'AUTH':
                assert command[1] == 'XOAUTH2'
                assert b'user=reports@example.test\x01auth=Bearer never-share-this-token\x01\x01' == command[2]


def test_logout_during_signin_cannot_restore_revoked_token(tmp_path, monkeypatch):
    repository = SandboxRepository(tmp_path)
    service = OutlookSandboxService(repository)
    service.configure(values())
    started, release = threading.Event(), threading.Event()

    class FakeMsal:
        def initiate_device_flow(self, **kwargs):
            return dict(user_code='CODE-123', expires_in=60, expires_at=time.time() + 60)

        def acquire_token_by_device_flow(self, flow):
            started.set()
            assert release.wait(2)
            return dict(access_token='sensitive')

    monkeypatch.setattr(service, '_app', lambda cfg, cache: FakeMsal())
    assert service.start_login()['state'] == 'pending'
    assert started.wait(2)
    service.disconnect()
    release.set()
    for thread in threading.enumerate():
        if thread.name == 'outlook-sandbox-oauth':
            thread.join(timeout=2)
            assert not thread.is_alive()
    assert not repository.tokens_path.exists()


@pytest.fixture
def web(tmp_path):
    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\nEMAIL_MAILBOX=INBOX\n')
    cfg = Config(data_dir=tmp_path / 'appdata', env_file=env,
                 secret_key='a' * 64, email_enabled=False)
    app = create_app(cfg)
    app.testing = True
    client = app.test_client()
    csrf = login_admin(client)
    return app, client, csrf, env


def test_admin_csrf_and_gmail_isolation(web):
    app, client, csrf, env = web
    assert client.get('/outlook-sandbox').status_code == 200
    assert client.get('/settings').status_code == 200
    assert b'Open Outlook Sandbox' in client.get('/settings').data
    before = env.read_bytes()
    assert client.post('/outlook-sandbox/config', data=values()).status_code == 400
    assert client.post('/outlook-sandbox/config', data=dict(values(), csrf=csrf)).status_code == 303
    assert env.read_bytes() == before
    status = client.get('/outlook-sandbox/status').json['result']
    assert status['configured'] and not status['signed_in']
    resp = client.post('/outlook-sandbox/check', data={'csrf': csrf})
    assert resp.status_code == 400 and not resp.json['ok']
    assert app.extensions['printer_db'].rows('SELECT * FROM attachments') == []


def test_web_staging_stays_outside_print_queue_and_is_admin_only(web, monkeypatch):
    app, client, csrf, env = web
    service = app.extensions['outlook_sandbox']
    service.configure(values())
    cfg = service.configuration()
    class FakeAdapter:
        config = cfg
        def recent(self):
            return {'folder': 'Printer', 'uidvalidity': '99',
                    'messages': [{'uid': '102', 'subject': 'Daily report', 'sender': 'example',
                                  'date': '2026-10-23'}]}
        def attachments(self, uid):
            assert uid == '102'
            return '99', [('Daily.pdf', b'%PDF-test')]
    monkeypatch.setattr(service, '_adapter', lambda: FakeAdapter())
    unauth = app.test_client()
    assert unauth.get('/outlook-sandbox/staged/' + 'a' * 64 + '/0').status_code == 302
    assert unauth.post('/outlook-sandbox/stage', data={'uid': '102'}).status_code == 400
    checked = client.post('/outlook-sandbox/check', data={'csrf': csrf})
    assert checked.status_code == 200
    assert checked.json['result']['messages'][0]['subject'] == 'Daily report'
    response = client.post('/outlook-sandbox/stage', data={'csrf': csrf, 'uid': '102'})
    assert response.status_code == 200
    staged = response.json['result']
    file = client.get(staged['files'][0]['download_url'])
    assert file.status_code == 200 and file.data == b'%PDF-test'
    assert app.extensions['printer_db'].rows('SELECT * FROM attachments') == []
    assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []
    assert b'EMAIL_ENABLED=0' in env.read_bytes()


def test_outlook_boundary_does_not_enter_live_email_or_print_workflow():
    root = Path(__file__).resolve().parents[1]
    for name in ('worker.py', 'gmail_client.py', 'print_dispatch.py',
                 'gmail_cleanup.py', 'settings.py'):
        assert 'outlook_sandbox' not in (root / name).read_text()
    source = (root / 'outlook_sandbox' / 'service.py').read_text()
    assert 'PrintQueue' not in source and 'GmailClient' not in source
    assert 'outlook_sandbox' in (root / 'app.py').read_text()

@pytest.mark.skipif(__import__('os').environ.get('PRINTER_BROWSER_TESTS') != '1',
                    reason='Run in CI with real Chromium')
def test_real_browser_folder_preview_and_stage(web, monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    from werkzeug.serving import make_server
    from printer_app.tests.auth_helpers import browser_login

    app, _, _, _ = web
    service = app.extensions['outlook_sandbox']
    service.configure(values())
    config = service.configuration()

    class BrowserAdapter:
        def __init__(self):
            self.config = config

        def folders(self):
            return ['INBOX', 'Printer']

        def recent(self):
            return {'folder': 'Printer', 'uidvalidity': '19',
                    'messages': [{'uid': '104', 'subject': 'Actual PDF report',
                                  'sender': 'sales@example.test', 'date': 'Today'}]}

        def attachments(self, uid):
            assert uid == '104'
            return '19', [('Report.pdf', b'%PDF-BROWSER')]

    monkeypatch.setattr(service, '_adapter', lambda: BrowserAdapter())
    monkeypatch.setattr(service, 'status', lambda: dict(
        configured=True, signed_in=True, account='reports@example.test', state='connected'))

    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://printer.test:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True,
                args=['--no-proxy-server', '--host-resolver-rules=MAP printer.test 127.0.0.1'])
            try:
                page = browser.new_page()
                browser_login(page, app, origin)
                assert page.goto(origin + '/outlook-sandbox').status == 200
                expect(page.locator('#outlookConnectionStatus')).to_contain_text('reports@example.test')
                page.locator('#outlookFolders').click()
                expect(page.locator('#outlookFolderResult')).to_contain_text('Printer')
                page.locator('#outlookCheck').click()
                expect(page.locator('#outlookCheckResult')).to_contain_text('Read-only connection succeeded')
                expect(page.locator('#outlookMessages')).to_contain_text('Actual PDF report')
                page.get_by_role('button', name='Stage attachments').click()
                expect(page.locator('#outlookStageResult')).to_contain_text('No printing occurred')
                expect(page.locator('#outlookStageResult a')).to_have_count(1)
                assert page.locator('#outlookStageResult a').get_attribute('href').startswith(
                    '/outlook-sandbox/staged/')
                assert app.extensions['printer_db'].rows('SELECT * FROM jobs') == []
            finally:
                browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
