"""The standalone setup CLI delivers printer-admin bootstrap credentials privately."""
import json
from pathlib import Path
import subprocess
import sys

from printer_app import bootstrap, deploy


def run_bootstrap(monkeypatch, *args):
    monkeypatch.setattr(sys, 'argv', ['bootstrap', *map(str, args)])
    bootstrap.main()


def test_setup_creates_one_temporary_admin_login_outside_environment(tmp_path, monkeypatch):
    from printer_app.admin_auth_repository import AdminAuthRepository
    from printer_app.db import Database
    from werkzeug.security import check_password_hash

    env = tmp_path / 'private/env'
    data = tmp_path / 'data'
    login = tmp_path / 'delivery/initial-login.json'
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setenv('PRINTER_DATA_DIR', str(data))

    run_bootstrap(monkeypatch, 'init')
    run_bootstrap(monkeypatch, 'migrate')
    run_bootstrap(monkeypatch, 'ensure-admin', '--initial-login-file', login)

    delivered = json.loads(login.read_text())
    assert delivered['username'] == 'admin'
    assert len(delivered['password']) >= 15
    assert login.stat().st_mode & 0o777 == 0o600
    assert delivered['password'] not in env.read_text()
    state = AdminAuthRepository(Database(data / 'printer_app.db')).state()
    assert state['must_change'] == 1
    assert check_password_hash(state['password_hash'], delivered['password'])


def test_existing_configuration_is_preserved_when_admin_auth_is_added(tmp_path, monkeypatch):
    env = tmp_path / 'env'
    data = tmp_path / 'data'
    original = b'EMAIL_USER=existing@example.test\nPRINTER_SECRET_KEY=existing-secret-key-value-that-is-long-enough-123456\n'
    env.write_bytes(original)
    login = tmp_path / 'initial-login.json'
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setenv('PRINTER_DATA_DIR', str(data))

    run_bootstrap(monkeypatch, 'init')
    assert env.read_bytes() == original
    run_bootstrap(monkeypatch, 'migrate')
    run_bootstrap(monkeypatch, 'ensure-admin', '--initial-login-file', login)
    assert env.read_bytes() == original
    assert json.loads(login.read_text())['username'] == 'admin'


def test_retries_preserve_existing_admin_password_and_handoff(tmp_path, monkeypatch):
    env = tmp_path / 'env'
    data = tmp_path / 'data'
    login = tmp_path / 'initial-login.json'
    monkeypatch.setenv('PRINTER_ENV_FILE', str(env))
    monkeypatch.setenv('PRINTER_DATA_DIR', str(data))

    run_bootstrap(monkeypatch, 'init')
    run_bootstrap(monkeypatch, 'migrate')
    run_bootstrap(monkeypatch, 'ensure-admin', '--initial-login-file', login)
    first = login.read_bytes()
    run_bootstrap(monkeypatch, 'ensure-admin', '--initial-login-file', login)
    assert login.read_bytes() == first


def test_unattended_service_setup_uses_noninteractive_sudo(monkeypatch):
    calls = []
    monkeypatch.setattr(deploy.subprocess, 'run', lambda command, **kwargs: calls.append((command, kwargs)))
    deploy.run(['sudo', 'systemctl', 'restart', *deploy.UNITS], unattended=True)
    command, options = calls[0]
    assert command[:3] == ['sudo', '-n', 'systemctl']
    assert options['stdin'] == subprocess.DEVNULL
    assert 'pi-tableau-leaderboard.service' not in command


def test_same_release_update_retries_optional_https_without_restarting_core(tmp_path, monkeypatch):
    release = tmp_path / '.local/lib/printer-app/releases' / deploy.fingerprint(Path(deploy.__file__).parent)
    release.mkdir(parents=True)
    (release / '.ready').write_text('ready')
    (release / 'printer_app/systemd').mkdir(parents=True)
    (release / 'printer_app/systemd/printer-app-https.service').write_text('fixture')
    (release.parent.parent / 'current').symlink_to(release)
    result_file = tmp_path / 'result.json'
    prepared, calls = [], []
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(deploy.getpass, 'getuser', lambda: 'scoreboard')
    monkeypatch.setattr(deploy.os, 'geteuid', lambda: 1000)
    monkeypatch.setattr(deploy, 'release_paths',
                        lambda release: {'port':5055, 'data':str(tmp_path / 'data')})
    monkeypatch.setattr(
        deploy, 'prepare_gallery_https',
        lambda release, paths, unattended=False: prepared.append((release, paths, unattended)) or True,
    )
    monkeypatch.setattr(deploy, 'run', lambda command, **kwargs: calls.append(command))
    monkeypatch.setattr(sys, 'argv', ['deploy', 'update', '--unattended', '--result-file', str(result_file)])
    deploy.main()
    assert prepared and prepared[0][2] is True
    assert calls == [['sudo', 'systemctl', 'restart', 'printer-app-https.service']]
    assert json.loads(result_file.read_text()) == {'port':5055, 'changed':False}
