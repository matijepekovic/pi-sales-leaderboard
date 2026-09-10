"""Browser settings, atomic storage, write-only secrets and live configuration."""
from __future__ import annotations

import ast
from dataclasses import replace
import hashlib
import logging
import os
from pathlib import Path
import stat

import pytest

from printer_app.config import Config, parse_env
from printer_app.settings import SettingsService, SettingsError
from printer_app.settings_repository import SettingsRepository, SettingsStorageError, SettingsConflict
from printer_app.gmail_client import test_connection as probe_gmail
from printer_app.worker import RedactingFormatter


@pytest.fixture
def configured(tmp_path):
    env = tmp_path / 'config/env'
    env.parent.mkdir()
    env.write_text('# keep this comment\nEMAIL_USER=reports@example.test\nEMAIL_APP_PASSWORD=stored-app-password\n'
                   'EMAIL_MAILBOX=INBOX\nEMAIL_POLL_SECONDS=60\nPRINTER_QUEUE=konicaa\n'
                   'PRINTER_SECRET_KEY=' + 'a' * 64 + '\nUNRELATED_KEY=preserve-me\n')
    env.chmod(0o600)
    cfg = Config(data_dir=tmp_path / 'data', env_file=env, secret_key='a' * 64)
    repository = SettingsRepository(env)
    return SettingsService(repository, cfg), env


def form(service, **changes):
    cfg, revision = service.read()
    result = dict(service.public_values(cfg), revision=revision, EMAIL_APP_PASSWORD='')
    result.update(changes)
    return result


def test_save_preserves_secret_unrelated_settings_and_comments(configured):
    service, env = configured
    service.save(form(service, EMAIL_POLL_SECONDS='91', EMAIL_SUBJECT_CONTAINS='Daily Report'))
    cfg, _ = service.read()
    assert cfg.poll_seconds == 91 and cfg.subject_contains == 'Daily Report'
    assert cfg.email_password == 'stored-app-password'
    assert cfg.queue == 'konicaa'
    text = env.read_text()
    assert '# keep this comment' in text and 'UNRELATED_KEY=preserve-me' in text
    assert 'PRINTER_SECRET_KEY=' + 'a' * 64 in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert not list(env.parent.glob('.settings-*'))


def test_blank_password_keeps_saved_value_and_clear_is_explicit(configured):
    service, env = configured
    service.save(form(service, EMAIL_APP_PASSWORD='new app password'))
    assert service.read()[0].email_password == 'newapppassword'
    service.save(form(service, EMAIL_APP_PASSWORD=''))
    assert service.read()[0].email_password == 'newapppassword'
    service.save(form(service, EMAIL_ENABLED='0', clear_password='1'))
    assert service.read()[0].email_password == ''
    assert not service.read()[0].email_enabled


@pytest.mark.parametrize('changes', [
    {'EMAIL_POLL_SECONDS':'9'}, {'EMAIL_POLL_SECONDS':'60.1'},
    {'EMAIL_LOOKBACK_DAYS':'0'}, {'CONVERSION_TIMEOUT_SECONDS':'601'},
    {'PRINTER_RETRY_SECONDS':'0'}, {'MAX_ATTACHMENT_MB':'101'},
    {'PRINTER_TIMEZONE':'made/up'}, {'EMAIL_MAILBOX':''},
    {'EMAIL_SUBJECT_CONTAINS':'x\nPRINTER_SECRET_KEY=bad'},
    {'EMAIL_FROM_CONTAINS':'x\r\nEVIL=1'}, {'EMAIL_APP_PASSWORD':'x\x00y'},
    {'PRINTER_DATA_DIR':'/tmp/other'}, {'LIBREOFFICE_BIN':'touch /tmp/evil'},
    {'PRINTER_QUEUE':'other'}, {'PRINTER_SECRET_KEY':'stolen'},
    {'EMAIL_ENABLED':'yes'}, {'EMAIL_USER':'other@example.test'},
])
def test_invalid_values_do_not_modify_any_settings(configured, changes):
    service, env = configured
    before = env.read_bytes()
    with pytest.raises(SettingsError):
        service.save(form(service, **changes))
    assert env.read_bytes() == before


def test_env_quoting_is_literal_and_roundtrips(configured, tmp_path):
    service, env = configured
    text = 'Report "quoted" \\ $HOME `command` # literal'
    service.save(form(service, EMAIL_SUBJECT_CONTAINS=text))
    assert service.read()[0].subject_contains == text
    assert parse_env(env.read_text())['EMAIL_SUBJECT_CONTAINS'] == text


def test_stale_form_does_not_overwrite_a_newer_save(configured):
    service, env = configured
    old = form(service)
    service.save(form(service, EMAIL_POLL_SECONDS='120'))
    with pytest.raises(SettingsConflict):
        service.save(old)
    assert service.read()[0].poll_seconds == 120


def test_atomic_replace_failure_leaves_existing_file(configured, monkeypatch):
    service, env = configured
    before = env.read_bytes()
    def fail(*a):
        raise OSError('simulated disk error')
    monkeypatch.setattr('printer_app.settings_repository.os.replace', fail)
    with pytest.raises(SettingsStorageError):
        service.save(form(service, EMAIL_POLL_SECONDS='90'))
    assert env.read_bytes() == before
    assert not list(env.parent.glob('.settings-*'))


def test_live_read_overrides_stale_inherited_environment(configured, monkeypatch):
    service, env = configured
    monkeypatch.setenv('EMAIL_APP_PASSWORD', 'old-environment-password')
    monkeypatch.setenv('EMAIL_POLL_SECONDS', '31')
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    baseline = Config.from_env()
    assert baseline.poll_seconds == 31
    worker = SettingsService(SettingsRepository(env), baseline)
    service.save(form(service, EMAIL_POLL_SECONDS='89', EMAIL_APP_PASSWORD='fresh-password'))
    cfg, _ = worker.read()
    assert cfg.poll_seconds == 89 and cfg.email_password == 'fresh-password'
    assert os.environ['EMAIL_APP_PASSWORD'] == 'old-environment-password'
    assert service.read()[0].poll_seconds == 89


def test_secrets_are_never_part_of_public_values_or_config_repr(configured):
    service, _ = configured
    cfg, _ = service.read()
    assert 'EMAIL_APP_PASSWORD' not in service.public_values(cfg)
    assert cfg.email_password not in repr(cfg) and cfg.secret_key not in repr(cfg)


def test_probe_does_not_save_and_uses_entered_password(configured):
    service, env = configured
    seen = []
    service.email_probe = lambda cfg: (seen.append(cfg) is None, 'Connected')
    before = env.read_bytes()
    ok, _ = service.test_email(form(service, EMAIL_APP_PASSWORD='unsaved-password'))
    assert ok and seen[0].email_password == 'unsaved-password'
    assert env.read_bytes() == before


def test_probe_failure_cannot_echo_credentials(configured):
    service, _ = configured
    def failure(cfg):
        raise RuntimeError(cfg.email_password)
    service.email_probe = failure
    ok, message = service.test_email(form(service))
    assert not ok and 'stored-app-password' not in message


def test_gmail_probe_only_logs_in_and_opens_readonly_mailbox(configured, monkeypatch):
    service, _ = configured
    calls = []
    class IMAP:
        def __init__(self, host, port, **kwargs):
            assert host == 'imap.gmail.com' and port == 993 and kwargs['timeout'] == 10
        def __enter__(self): return self
        def __exit__(self, *args): calls.append('logout')
        def login(self, user, password): calls.append('login')
        def select(self, mailbox, readonly):
            assert readonly is True
            calls.append('select')
            return 'OK', []
        def uid(self, *args): pytest.fail('A connection test must not search or download emails')
    monkeypatch.setattr('printer_app.gmail_client.imaplib.IMAP4_SSL', IMAP)
    assert probe_gmail(service.read()[0])[0] is True
    assert calls == ['login', 'select', 'logout']


def test_log_redaction_updates_after_password_change(configured):
    service, _ = configured
    cfg, _ = service.read()
    formatter = RedactingFormatter(cfg)
    formatter.update(replace(cfg, email_password='replacement-password'))
    record = logging.LogRecord('printer', logging.ERROR, '', 0,
                               'stored-app-password replacement-password', (), None)
    assert 'password' not in formatter.format(record)


@pytest.fixture
def ui(configured):
    pytest.importorskip('flask')
    from printer_app.app import create_app
    service, env = configured
    app = create_app(service.baseline, settings_service=service)
    app.testing = True
    client = app.test_client()
    client.get('/settings')
    with client.session_transaction() as session:
        csrf = session['csrf']
    return service, env, app, client, csrf


def test_ui_direct_access_and_password_never_returned(ui):
    service, _, _, client, csrf = ui
    for route in ('/settings', '/', '/api/status'):
        response = client.get(route)
        assert response.status_code == 200
        assert b'stored-app-password' not in response.data
    assert client.get('/login').status_code == 404
    response = client.post('/settings', data=form(service, csrf=csrf, EMAIL_APP_PASSWORD='new-secret'), follow_redirects=True)
    assert response.status_code == 200
    assert b'new-secret' not in response.data
    assert all('new-secret' not in c for c in response.headers.getlist('Set-Cookie'))
    assert b'Settings saved' in response.data


def test_ui_writes_require_csrf_and_same_origin(ui):
    service, env, _, client, csrf = ui
    before = env.read_bytes()
    assert client.post('/settings', data=form(service)).status_code == 400
    assert client.post('/settings', data=form(service, csrf='\u2603')).status_code == 400
    assert client.post('/settings', data=form(service, csrf=csrf), headers={'Origin':'https://other.example'}).status_code == 403
    assert client.post('/settings/test-email', data=form(service)).status_code == 400
    assert env.read_bytes() == before


def test_browser_test_does_not_save_or_enqueue_printing(ui):
    service, env, app, client, csrf = ui
    before = env.read_bytes()
    service.email_probe = lambda cfg: (True, 'Connected without printing')
    response = client.post('/settings/test-email', data=form(service, csrf=csrf, EMAIL_APP_PASSWORD='unsaved-secret'))
    assert response.json['ok'] is True and b'unsaved-secret' not in response.data
    assert env.read_bytes() == before
    assert not app.extensions['printer_db'].rows('SELECT * FROM commands')
    assert not app.extensions['printer_db'].rows('SELECT * FROM jobs')


def test_settings_owner_boundaries():
    root = Path(__file__).resolve().parents[1]
    for filename in ('settings.py', 'settings_repository.py'):
        tree = ast.parse((root / filename).read_text())
        imports = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {(n.module or '').split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not imports & {'flask','sqlite3','subprocess','server','stats_core','update_delivery'}
    web_unit = (root / 'systemd/printer-app-web.service').read_text()
    worker_unit = (root / 'systemd/printer-app-worker.service').read_text()
    assert 'ReadWritePaths=@DATA@ @CONFIG@' in web_unit
    assert 'ReadWritePaths=@DATA@' in worker_unit and '@CONFIG@' not in worker_unit
