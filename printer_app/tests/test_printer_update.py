"""Printer-only software update: authenticated request, verified runner, no Stats writes."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
import zipfile

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


def test_update_request_reports_safe_states_and_resets_stale_attempt(tmp_path, monkeypatch):
    service = update.PrinterUpdateService(tmp_path)
    assert service.status()['state'] == 'NOT CHECKED'
    assert service.request()['state'] == 'QUEUED'
    assert service.status()['state'] == 'QUEUED'
    # The web does not display exception strings, credentials, source paths,
    # or other private data from the stored installer receipt.
    current = update._read_json(service.directory / 'status.json')
    update._write_json(service.directory / 'status.json',
                       dict(current, state='INSTALLING', updated=0))
    assert service.status()['state'] == 'ERROR'
    assert service.request()['state'] == 'QUEUED'


def _archive(folder: Path, *, extra=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as source:
        for path in folder.rglob('*'):
            if path.is_file():
                source.write(path, 'repo/printer_app/' + path.relative_to(folder).as_posix())
        if extra:
            source.writestr(*extra)
    return buffer.getvalue()


def test_git_tree_and_pinned_archive_reject_tampering(tmp_path, monkeypatch):
    folder = tmp_path / 'source'
    folder.mkdir()
    (folder / 'install.sh').write_text('#!/bin/bash\nexit 0\n')
    (folder / 'install.sh').chmod(0o755)
    (folder / 'worker.py').write_text('print("printer only")\n')
    bundle = {'revision': 'a' * 40, 'tree': update._git_tree(folder)}
    urls = []
    def get_archive(request, **kwargs):
        urls.append(request.full_url)
        return io.BytesIO(_archive(folder))
    monkeypatch.setattr(update.urllib.request, 'urlopen', get_archive)
    output = tmp_path / 'download'
    output.mkdir()
    package = update._download(bundle, output)
    assert (package / 'worker.py').read_text() == 'print("printer only")\n'
    assert urls == ['https://api.github.com/repos/' + update.REPOSITORY
                    + '/zipball/' + 'a' * 40]
    assert update._git_tree(package) == bundle['tree']
    with pytest.raises(ValueError, match='Git tree'):
        failed = tmp_path / 'wrong-hash'
        failed.mkdir()
        update._download(dict(bundle, tree='b' * 40), failed)

    path = zipfile.ZipInfo('repo/printer_app/link')
    path.external_attr = 0o120777 << 16
    monkeypatch.setattr(update.urllib.request, 'urlopen',
                        lambda *a, **k: io.BytesIO(_archive(folder, extra=(path, 'bad'))))
    with pytest.raises(ValueError, match='Unsupported'):
        failed = tmp_path / 'unsafe'
        failed.mkdir()
        update._download(bundle, failed)


def test_worker_up_to_date_never_restarts_any_service(tmp_path, monkeypatch):
    service = update.PrinterUpdateService(tmp_path)
    service.request()
    monkeypatch.setattr(update, '_remote_bundle', lambda: {'revision': 'a' * 40, 'tree': 'b' * 40})
    def download(bundle, directory):
        package = directory / 'printer_app'
        package.mkdir()
        return package
    monkeypatch.setattr(update, '_download', download)
    monkeypatch.setattr(update, 'fingerprint', lambda source: 'same-source')
    monkeypatch.setattr(update.subprocess, 'run', lambda *args, **kwargs: pytest.fail('No reinstall for same printer release'))
    assert update.run_update(tmp_path) == 0
    assert service.status()['state'] == 'UP TO DATE'
    assert not (tmp_path / 'updates/request.json').exists()


def test_worker_installs_only_verified_printer_package(tmp_path, monkeypatch):
    service = update.PrinterUpdateService(tmp_path)
    service.request()
    monkeypatch.setattr(update, '_remote_bundle', lambda: {'revision': 'a' * 40, 'tree': 'b' * 40})
    def download(bundle, directory):
        package = directory / 'printer_app'
        package.mkdir()
        (package / 'install.sh').write_text('echo fixture')
        return package
    monkeypatch.setattr(update, '_download', download)
    monkeypatch.setattr(update, 'fingerprint',
                        lambda source: 'new-release' if source.name == 'printer_app' else 'old-release')
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
    assert update.run_update(tmp_path) == 0  # No second request, no second install


def test_updater_path_unit_is_enabled_but_never_the_one_shot_service(tmp_path, monkeypatch):
    root = tmp_path / 'release/printer_app/systemd'
    root.mkdir(parents=True)
    for name in (deploy.UPDATE_SERVICE, deploy.UPDATE_PATH):
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
