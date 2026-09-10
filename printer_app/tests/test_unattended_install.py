"""The standalone setup CLI supports a UI-driven installer without sharing auth."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from werkzeug.security import check_password_hash

from printer_app import bootstrap, deploy


def test_private_initial_login_is_not_logged(tmp_path, monkeypatch, capsys):
    env = tmp_path / 'private/env'
    login = tmp_path / 'delivery/initial-login.json'
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setattr(sys, 'argv', ['bootstrap', 'init', '--initial-login-file', str(login)])
    bootstrap.main()
    credentials = json.loads(login.read_text())
    assert len(credentials['password']) >= 20
    assert credentials['password'] not in capsys.readouterr().out
    password_hash = next(line.partition('=')[2] for line in env.read_text().splitlines() if line.startswith('PRINTER_UI_PASSWORD_HASH='))
    assert check_password_hash(password_hash, credentials['password'])
    assert credentials['password'] not in env.read_text()
    assert stat.S_IMODE(login.stat().st_mode) == stat.S_IMODE(env.stat().st_mode) == 0o600
    before = env.read_bytes()
    bootstrap.main()
    assert env.read_bytes() == before
    assert json.loads(login.read_text()) == credentials


def test_existing_configuration_is_never_reset(tmp_path, monkeypatch, capsys):
    env = tmp_path / 'env'
    original = b'EMAIL_USER=existing@example.test\nPRINTER_UI_PASSWORD_HASH=existing\n'
    env.write_bytes(original)
    login = tmp_path / 'initial-login.json'
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setattr(sys, 'argv', ['bootstrap', 'init', '--initial-login-file', str(login)])
    bootstrap.main()
    assert env.read_bytes() == original
    assert not login.exists()
    assert 'existing@example.test' not in capsys.readouterr().out


def test_interrupted_initial_handoff_recovers_same_credentials(tmp_path, monkeypatch):
    env = tmp_path / 'env'
    login = tmp_path / 'initial-login.json'
    password = 'fixture-recovery-password-123'
    login.write_text(json.dumps({'username':'admin', 'password':password}))
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setattr(sys, 'argv', ['bootstrap', 'init', '--initial-login-file', str(login)])
    bootstrap.main()
    value = next(line.partition('=')[2] for line in env.read_text().splitlines() if line.startswith('PRINTER_UI_PASSWORD_HASH='))
    assert check_password_hash(value, password)


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
