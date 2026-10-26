"""Printer-only software update: authenticated requests and isolated deployment."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from printer_app import deploy, update
from printer_app.app import create_app
from printer_app.config import Config
from printer_app.tests.auth_helpers import login_admin


def test_admin_controls_one_fixed_printer_update_request(tmp_path):
    cfg = Config(data_dir=tmp_path, secret_key='s' * 64, email_enabled=False)
    app = create_app(cfg)
    client = app.test_client()

    assert client.get('/settings').status_code == 302
    assert client.get('/api/printer-update').status_code == 401
    assert client.post('/settings/update-printer').status_code != 303

    csrf = login_admin(client)
    page = client.get('/settings').get_data(as_text=True)
    assert 'Update Printer' in page
    assert 'only the independent printer app' in page
    assert 'name="csrf"' in page
    assert client.post('/settings/update-printer').status_code == 400
    assert client.post('/settings/update-printer',
                       data={'csrf': csrf}, headers={'Origin': 'https://other.example'}).status_code == 403
    assert not (tmp_path / 'updates/request.json').exists()

    response = client.post('/settings/update-printer', data={'csrf': csrf})
    assert response.status_code == 303
    assert response.headers['Location'].endswith('#printerUpdate')
    first = json.loads((tmp_path / 'updates/request.json').read_text())
    assert set(first) == {'request_id'}
    assert len(first['request_id']) == 32
    assert client.get('/api/printer-update').json['state'] == 'QUEUED'

    assert client.post('/settings/update-printer', data={'csrf': csrf}).status_code == 303
    assert json.loads((tmp_path / 'updates/request.json').read_text()) == first
    assert not list(tmp_path.glob('**/stats*'))


def test_update_request_reports_safe_states_and_resets_stale_attempt(tmp_path):
    service = update.PrinterUpdateService(tmp_path)
    assert service.status()['state'] == 'NOT CHECKED'
    assert service.request()['state'] == 'QUEUED'
    assert service.status()['state'] == 'QUEUED'
    current = update._read_json(service.directory / 'status.json')
    update._write_json(service.directory / 'status.json',
                       dict(current, state='INSTALLING', updated=0))
    assert service.status()['state'] == 'ERROR'
    assert service.request()['state'] == 'QUEUED'


def _mock_checkout(monkeypatch, destination_fixture):
    """Fake Git transport while inspecting exact arguments sent to Git."""
    calls = []
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if 'clone' in args:
            root = Path(args[-1]) / 'printer_app'
            root.mkdir(parents=True)
            (root / 'install.sh').write_text('#!/bin/bash\nexit 0\n')
            return SimpleNamespace(returncode=0)
        if args[-1] == 'HEAD':
            return SimpleNamespace(returncode=0, stdout='a' * 40 + '\n')
        if args[-1] == 'HEAD:printer_app':
            return SimpleNamespace(returncode=0, stdout='b' * 40 + '\n')
        raise AssertionError(f'Unexpected Git invocation: {args}')
    monkeypatch.setattr(update.subprocess, 'run', fake_run)
    source, bundle = update._checkout(destination_fixture)
    return source, bundle, calls


def test_git_checkout_is_fixed_branch_and_only_printer_source(tmp_path, monkeypatch):
    source, bundle, calls = _mock_checkout(monkeypatch, tmp_path)
    assert source == tmp_path / 'repository/printer_app'
    assert (source / 'install.sh').is_file()
    assert bundle == {'revision': 'a' * 40, 'tree': 'b' * 40}
    clone, options = calls[0]
    assert clone[:2] == ['git', '-c']
    assert '--depth' in clone and clone[clone.index('--depth') + 1] == '1'
    assert '--single-branch' in clone and '--no-tags' in clone
    assert clone[clone.index('--branch') + 1] == 'main'
    assert clone[clone.index('--') + 1] == 'https://github.com/' + update.REPOSITORY + '.git'
    assert options['stdin'] == subprocess.DEVNULL
    assert options['env']['GIT_TERMINAL_PROMPT'] == '0'
    assert options['env']['GIT_CONFIG_GLOBAL'] == '/dev/null'
    assert calls[1][0][-1] == 'HEAD'
    assert calls[2][0][-1] == 'HEAD:printer_app'
    assert all(call[1]['check'] is True for call in calls)


def test_git_checkout_rejects_symlinked_printer_source(tmp_path, monkeypatch):
    def fake_run(args, **options):
        if 'clone' in args:
            root = Path(args[-1]) / 'printer_app'
            root.mkdir(parents=True)
            (root / 'external').symlink_to('/etc/passwd')
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0, stdout=('a' * 40) + '\n')
    monkeypatch.setattr(update.subprocess, 'run', fake_run)
    with pytest.raises(ValueError, match='Links are not allowed'):
        update._checkout(tmp_path)


def test_git_checkout_rejects_untrusted_tree_id(tmp_path, monkeypatch):
    def fake_run(args, **options):
        if 'clone' in args:
            (Path(args[-1]) / 'printer_app').mkdir(parents=True)
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0, stdout='not-a-git-object\n')
    monkeypatch.setattr(update.subprocess, 'run', fake_run)
    with pytest.raises(ValueError, match='Invalid printer source'):
        update._checkout(tmp_path)


def test_worker_up_to_date_never_restarts_any_service(tmp_path, monkeypatch):
    service = update.PrinterUpdateService(tmp_path)
    service.request()
    def checkout(destination):
        package = destination / 'printer_app'
        package.mkdir()
        return package, {'revision': 'a' * 40, 'tree': 'b' * 40}
    monkeypatch.setattr(update, '_checkout', checkout)
    monkeypatch.setattr(update, 'fingerprint', lambda source: 'same-source')
    monkeypatch.setattr(update.subprocess, 'run', lambda *args, **kwargs: pytest.fail('No reinstall for same printer release'))
    assert update.run_update(tmp_path) == 0
    assert service.status()['state'] == 'UP TO DATE'
    assert not (tmp_path / 'updates/request.json').exists()


def test_worker_installs_only_verified_printer_package(tmp_path, monkeypatch):
    service = update.PrinterUpdateService(tmp_path)
    service.request()
    def checkout(destination):
        package = destination / 'printer_app'
        package.mkdir()
        (package / 'install.sh').write_text('echo fixture')
        return package, {'revision': 'a' * 40, 'tree': 'b' * 40}
    monkeypatch.setattr(update, '_checkout', checkout)
    monkeypatch.setattr(update, 'fingerprint',
                        lambda source: 'new-release' if Path(source).is_relative_to(tmp_path / 'updates')
                        else 'old-release')
    commands = []
    monkeypatch.setattr(update.subprocess, 'run',
                        lambda args, **kwargs: commands.append((args, kwargs)) or SimpleNamespace(returncode=0))
    assert update.run_update(tmp_path) == 0
    assert len(commands) == 1
    cmd, options = commands[0]
    assert cmd[0] == 'bash' and cmd[1].endswith('/printer_app/install.sh')
    assert cmd[2:] == ['--unattended']
    assert options['stdin'] == subprocess.DEVNULL
    assert not any('pi-tableau-leaderboard' in item for item in cmd)
    assert service.status()['state'] == 'READY'
    assert update.run_update(tmp_path) == 0


def test_updater_path_unit_is_enabled_but_never_the_one_shot_service(tmp_path, monkeypatch):
    root = tmp_path / 'release/printer_app/systemd'
    root.mkdir(parents=True)
    for name in (*deploy.UNITS, deploy.UPDATE_SERVICE, deploy.UPDATE_PATH):
        (root / name).write_text((Path(deploy.__file__).parent / 'systemd' / name).read_text())
    units = deploy.release_units(tmp_path / 'release')
    assert deploy.UPDATE_SERVICE in units
    assert deploy.UPDATE_PATH in units
    assert 'pi-tableau-leaderboard.service' not in units

    commands = []
    monkeypatch.setattr(deploy, 'run', lambda args, **kwargs: commands.append(args))
    deploy.install_units(tmp_path / 'release', tmp_path / 'releases',
                         {'data': str(tmp_path / 'data'), 'env': str(tmp_path / 'env')},
                         unattended=True)
    enabled = next(x for x in commands if x[:3] == ['sudo', 'systemctl', 'enable'])
    assert deploy.UPDATE_PATH in enabled
    assert deploy.UPDATE_SERVICE not in enabled
    service_text = (root / deploy.UPDATE_SERVICE).read_text()
    assert 'User=scoreboard' in service_text and 'pi-tableau-leaderboard.service' not in service_text
    assert 'PathExists=@DATA@/updates/request.json' in (root / deploy.UPDATE_PATH).read_text()
