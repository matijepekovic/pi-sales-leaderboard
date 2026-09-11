"""Retention must free finished output without losing queued work or replay receipts."""
from dataclasses import replace
from pathlib import Path
import ast
import os

import pytest

from printer_app.config import Config
from printer_app.db import Database
from printer_app.retention import RetentionService
from printer_app.retention_files import RetentionFiles
from printer_app.retention_policy import RetentionPolicy, mailbox_scope
from printer_app.retention_repository import RetentionRepository
from printer_app.settings import SettingsService, SettingsError
from printer_app.settings_repository import SettingsRepository

NOW = 2_000_000_000
OLD = NOW - 8 * 86400


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr('printer_app.retention.time.time', lambda: NOW)
    cfg = Config(data_dir=tmp_path / 'data', retention=RetentionPolicy(enabled=True), email_enabled=False)
    db = Database(cfg.db_path)
    repository = RetentionRepository(db)
    def no_mail(*args):
        raise AssertionError('No real email connection is permitted')
    return cfg, db, repository, RetentionService(cfg, repository, RetentionFiles(cfg.data_dir), no_mail)


def seed(cfg, db, state='PRINTED', completed=OLD, created=OLD, message_state='COMPLETE'):
    mid = db.execute('''INSERT INTO processed_messages
        (identity,account,mailbox,uidvalidity,uid,message_id,subject,sender,state,created)
        VALUES (?,?,?,?,?,?,?,?,?,?)''', ('private-hash', 'fixture@example.test', 'INBOX', '1', '1',
        '<fixture>', 'Private report', 'Private sender', message_state, created))
    aid = db.execute('''INSERT INTO attachments(message_id,part,filename,state,created)
        VALUES (?,'2','source.xlsx','DONE',?)''', (mid, created))
    jid = db.create_job(aid, 'workbook', cfg.print_options.snapshot())
    db.execute('UPDATE jobs SET status=?,created=?,completed=?,updated=? WHERE id=?',
                (state, created, completed, completed or created, jid))
    for category, ident in [('attachments', aid), ('jobs', jid)]:
        folder = cfg.data_dir / category / str(ident)
        folder.mkdir(parents=True)
        (folder / 'document').write_text('private report')
    db.output(jid, 'PDF', cfg.data_dir / 'jobs' / str(jid) / 'document')
    db.step(jid, 'Detailed private step')
    db.execute("INSERT INTO print_attempts(job_id,token,created,updated) VALUES (?,'fixture',?,?)", (jid, OLD, OLD))
    db.execute("INSERT INTO print_queue_releases VALUES (?,?,'weekly')", (aid, OLD))
    return mid, aid, jid


def test_finished_data_and_files_expire_but_receipt_remains(storage):
    cfg, db, repo, service = storage
    seed(cfg, db)
    service.run()
    for table in ('processed_messages', 'attachments', 'jobs', 'steps', 'outputs', 'print_attempts', 'print_queue_releases'):
        assert db.rows('SELECT * FROM ' + table) == []
    assert db.rows("SELECT * FROM meta WHERE key LIKE 'job_print_settings:%'") == []
    assert repo.seen('private-hash')
    assert db.rows('SELECT * FROM retained_message_receipts') == [{'identity': 'private-hash'}]
    assert list((cfg.data_dir / 'jobs').iterdir()) == []
    assert list((cfg.data_dir / 'attachments').iterdir()) == []
    assert service.repository.state()['local_jobs'] == 1
    assert not service.due(NOW + 10)
    assert service.due(NOW + 3600)
    assert RetentionRepository(Database(cfg.db_path)).seen('private-hash')


@pytest.mark.parametrize('status', ['READY', 'PREPARING', 'SUBMITTED', 'PRINTER ERROR', 'PRINT UNKNOWN'])
def test_unfinished_and_ambiguous_work_never_expires(storage, status):
    cfg, db, repo, service = storage
    _, aid, jid = seed(cfg, db, state=status)
    service.run()
    assert db.job(jid) and not repo.seen('private-hash')
    assert (cfg.data_dir / 'attachments' / str(aid) / 'document').exists()


@pytest.mark.parametrize('completed', [None, NOW - 7*86400, NOW - 1])
def test_retention_is_measured_after_completion(storage, completed):
    cfg, db, _, service = storage
    _, _, jid = seed(cfg, db, completed=completed)
    service.run()
    assert db.job(jid)


def test_interrupted_download_is_not_expired(storage):
    cfg, db, repo, service = storage
    seed(cfg, db, message_state='FETCHING')
    service.run()
    assert repo.download_pending('private-hash')
    assert db.rows('SELECT * FROM jobs')


def test_symlink_cannot_delete_outside_printer_data(storage, tmp_path):
    cfg, db, _, service = storage
    _, _, jid = seed(cfg, db)
    target = cfg.data_dir / 'jobs' / str(jid)
    (target / 'document').unlink()
    target.rmdir()
    outside = tmp_path / 'stats'
    outside.mkdir()
    (outside / 'keep').write_text('Stats data')
    target.symlink_to(outside, target_is_directory=True)
    service.run()
    assert (outside / 'keep').read_text() == 'Stats data'
    assert db.job(jid)
    assert service.repository.state()['error']


def test_old_backups_only_and_no_live_database_removal(storage):
    cfg, _, _, service = storage
    backups = cfg.data_dir / 'backups'
    backups.mkdir()
    old = backups / 'printer-app-20260101-000000.db'
    current = backups / 'printer-app-20260102-000000.db'
    foreign = backups / 'unrelated.db'
    for p in (old, current, foreign):
        p.write_text('backup')
        os.utime(p, (OLD, OLD))
    os.utime(current, (NOW, NOW))
    service.run()
    assert not old.exists() and current.exists() and foreign.exists()
    assert cfg.db_path.exists()


def test_mail_outage_does_not_block_local_cleanup(storage):
    cfg, db, repo, _ = storage
    cfg = replace(cfg, email_user='fixture@example.test', email_password='fixture-password',
        retention=RetentionPolicy(True, 7, True, mailbox_scope('fixture@example.test', 'INBOX')))
    seed(cfg, db)
    def offline(*args):
        raise OSError('remote unavailable')
    RetentionService(cfg, repo, RetentionFiles(cfg.data_dir), offline).run()
    assert db.rows('SELECT * FROM jobs') == []
    assert 'Gmail cleanup failed' in repo.state()['error']


def test_settings_require_opt_in_and_bind_it_to_the_inbox(tmp_path):
    env = tmp_path / 'env'
    env.write_text('EMAIL_USER=fixture@example.test\nEMAIL_APP_PASSWORD=fixture-password\nEMAIL_MAILBOX=INBOX\n')
    cfg = Config(data_dir=tmp_path / 'data', env_file=env)
    svc = SettingsService(SettingsRepository(env), cfg)
    current, revision = svc.read()
    assert not current.retention.enabled and not current.retention.delete_emails
    values = dict(svc.public_values(current), revision=revision, CLEANUP_ENABLED='1', CLEANUP_EMAILS='1')
    svc.save(values)
    current, revision = svc.read()
    assert current.retention.mail_allowed(current.email_user, 'INBOX')
    assert not current.retention.mail_allowed(current.email_user, '[Gmail]/All Mail')
    with pytest.raises(SettingsError):
        svc.save(dict(svc.public_values(current), revision=revision, EMAIL_MAILBOX='Other'))
    svc.save(dict(svc.public_values(current), revision=revision, EMAIL_MAILBOX='Other', CLEANUP_EMAILS='0'))
    assert not svc.read()[0].retention.delete_emails
    with pytest.raises(SettingsError):
        svc.candidate({'CLEANUP_EMAIL_SCOPE': 'forged'})


@pytest.mark.parametrize('days', ['0', '-1', '1.5', '366', 'NaN'])
def test_invalid_retention_is_rejected(days):
    with pytest.raises(ValueError):
        RetentionPolicy().apply({'CLEANUP_DAYS': days})


def test_cleanup_owners_and_dedup_integration():
    root = Path(__file__).resolve().parents[1]
    for name in ('retention.py', 'retention_files.py', 'retention_repository.py', 'retention_policy.py', 'gmail_cleanup.py'):
        source = (root / name).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(('stats_core', 'app.', 'tableau'))
        if name in ('retention.py', 'retention_files.py', 'retention_policy.py', 'gmail_cleanup.py'):
            assert 'SELECT ' not in source and 'DELETE FROM ' not in source
    source = (root / 'gmail_client.py').read_text()
    assert 'RetentionRepository(self.db).seen(identity)' in source
    assert source.index('seen(identity)') < source.index('qualifies =')
    worker = (root / 'worker.py').read_text()
    assert 'cleaning is None and polling is None and retention.due(now)' in worker
    assert 'polling is None and cleaning is None and' in worker


def test_browser_cleanup_switches_save_and_uncheck(tmp_path):
    from printer_app.app import create_app
    env = tmp_path / 'env'
    env.write_text('EMAIL_USER=fixture@example.test\nEMAIL_APP_PASSWORD=fixture-password\nEMAIL_MAILBOX=INBOX\n')
    cfg = Config(data_dir=tmp_path / 'data', env_file=env, secret_key='s' * 64)
    service = SettingsService(SettingsRepository(env), cfg)
    app = create_app(cfg, service)
    client = app.test_client()
    for enabled in (True, False):
        assert client.get('/settings').status_code == 200
        current, revision = service.read()
        with client.session_transaction() as session:
            csrf = session['csrf']
        values = dict(service.public_values(current), revision=revision, csrf=csrf, cleanup_present='1')
        for key in ('CLEANUP_ENABLED', 'CLEANUP_EMAILS'):
            values.pop(key)
            if enabled:
                values[key] = '1'
        assert client.post('/settings', data=values, headers={'Origin': 'http://localhost'}).status_code == 303
        assert service.read()[0].retention.enabled is enabled
        assert service.read()[0].retention.delete_emails is enabled
    assert client.post('/settings', data={'cleanup_present': '1', 'CLEANUP_EMAILS': '1'}).status_code == 400
