"""The standalone setup CLI supports UI-driven delivery without sharing auth."""
import json
from pathlib import Path
import subprocess
import sys

from printer_app import bootstrap, deploy


def test_v134_login_handoff_is_removed_and_no_credentials_are_created(tmp_path, monkeypatch, capsys):
    env = tmp_path / 'private/env'
    login = tmp_path / 'delivery/initial-login.json'
    login.parent.mkdir(parents=True)
    login.write_text(json.dumps({'username': 'admin', 'password': 'old-cleartext-password'}))
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setattr(sys, 'argv', ['bootstrap', 'init', '--initial-login-file', str(login)])
    bootstrap.main()
    assert not login.exists()
    text = env.read_text()
    assert 'PRINTER_UI_USER=' not in text
    assert 'PRINTER_UI_PASSWORD_HASH=' not in text
    assert 'PRINTER_SECRET_KEY=' in text
    output = capsys.readouterr().out
    assert 'old-cleartext-password' not in output
    assert 'no login' in output.lower()


def test_existing_configuration_is_never_reset(tmp_path, monkeypatch, capsys):
    env = tmp_path / 'env'
    original = b'EMAIL_USER=existing@example.test\nPRINTER_UI_PASSWORD_HASH=existing\nPRINTER_SECRET_KEY=existing-secret-key-value-that-is-long-enough-123456\n'
    env.write_bytes(original)
    login = tmp_path / 'initial-login.json'
    login.write_text(json.dumps({'username': 'admin', 'password': 'stale-password'}))
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setattr(sys, 'argv', ['bootstrap', 'init', '--initial-login-file', str(login)])
    bootstrap.main()
    assert env.read_bytes() == original
    assert not login.exists()
    assert 'existing@example.test' not in capsys.readouterr().out


def test_interrupted_old_handoff_is_deleted_not_recovered(tmp_path, monkeypatch):
    env = tmp_path / 'env'
    login = tmp_path / 'initial-login.json'
    login.write_text(json.dumps({'username': 'admin', 'password': 'fixture-recovery-password-123'}))
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setattr(sys, 'argv', ['bootstrap', 'init', '--initial-login-file', str(login)])
    bootstrap.main()
    assert not login.exists()
    text = env.read_text()
    assert 'PRINTER_UI_PASSWORD_HASH=' not in text
    before = env.read_bytes()
    bootstrap.main()
    assert env.read_bytes() == before
    assert not login.exists()


def test_unattended_service_setup_uses_noninteractive_sudo(monkeypatch):
    calls = []
    monkeypatch.setattr(deploy.subprocess, 'run', lambda command, **kwargs: calls.append((command, kwargs)))
    deploy.run(['sudo', 'systemctl', 'restart', *deploy.UNITS], unattended=True)
    command, options = calls[0]
    assert command[:3] == ['sudo', '-n', 'systemctl']
    assert options['stdin'] == subprocess.DEVNULL
    assert 'pi-tableau-leaderboard.service' not in command


def test_same_release_unattended_update_is_noop(tmp_path, monkeypatch):
    release = tmp_path / '.local/lib/printer-app/releases' / deploy.fingerprint(Path(deploy.__file__).parent)
    release.mkdir(parents=True)
    (release / '.ready').write_text('ready')
    (release.parent.parent / 'current').symlink_to(release)
    result_file = tmp_path / 'result.json'
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(deploy.getpass, 'getuser', lambda: 'scoreboard')
    monkeypatch.setattr(deploy.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(deploy, 'release_paths', lambda release: {'port':5055})
    monkeypatch.setattr(deploy, 'run', lambda *a, **k: (_ for _ in ()).throw(AssertionError('No process for unchanged release')))
    monkeypatch.setattr(sys, 'argv', ['deploy', 'update', '--unattended', '--result-file', str(result_file)])
    deploy.main()
    assert json.loads(result_file.read_text()) == {'port':5055, 'changed':False}
