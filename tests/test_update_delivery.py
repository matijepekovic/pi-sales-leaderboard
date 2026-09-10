"""Distribution boundary, genuine old-updater compatibility, and restart isolation."""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('update_delivery', ROOT / 'app/update_delivery.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)
BUNDLE = {'revision': 'a' * 40, 'tree': 'b' * 40}


def functions(path, names, namespace=None):
    nodes = [n for n in ast.parse(Path(path).read_text()).body if isinstance(n, ast.FunctionDef) and n.name in names]
    for node in nodes:
        node.decorator_list = []
    result = dict(namespace or {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), result)
    return result


@pytest.fixture
def private(tmp_path, monkeypatch):
    directory = tmp_path / 'delivery'
    directory.mkdir()
    monkeypatch.setattr(delivery, 'state_dir', lambda: directory)
    monkeypatch.setattr(delivery, 'unit_active', lambda: False)
    monkeypatch.setattr(delivery.pwd, 'getpwuid', lambda uid: SimpleNamespace(pw_name='scoreboard'))
    monkeypatch.setattr(delivery.os, 'geteuid', lambda: 1000)
    return directory


def test_initial_upgrade_launch_is_detached_and_not_a_runtime(private, monkeypatch):
    calls = []
    monkeypatch.setattr(delivery.subprocess, 'run', lambda args, **kw: calls.append((args, kw)) or SimpleNamespace(returncode=0))
    delivery.start_initial_install()
    command, options = calls[0]
    assert command[:3] == ['sudo', '-n', 'systemd-run']
    assert '--uid=scoreboard' in command and '--gid=scoreboard' in command
    assert '--collect' in command and '--no-block' in command and '--scope' not in command
    assert not any('pi-tableau-leaderboard' in v or 'PartOf=' in v or 'BindsTo=' in v for v in command)
    assert command[-3] == '/usr/bin/python3'
    runner = Path(command[-2])
    assert runner.is_relative_to(private) and runner.read_bytes() == (ROOT / 'app/update_delivery.py').read_bytes()
    assert delivery.read_json(Path(command[-1]))['bundle'] is None
    assert options['stdin'] == subprocess.DEVNULL and options['timeout'] == 10
    assert delivery.status()['state'] == 'QUEUED'
    delivery.start_initial_install()
    assert len(calls) == 1  # One upgrade handoff, not another app scheduler.


def test_unchanged_printer_does_not_install_or_restart(private, monkeypatch):
    delivery.write_json(private / 'status.json', dict(state='READY', **BUNDLE))
    monkeypatch.setattr(delivery.subprocess, 'run', lambda *a, **k: pytest.fail('No subprocess for an unchanged printer'))
    assert not delivery.needs_install(BUNDLE)
    assert delivery.request_install(BUNDLE)['state'] == 'READY'
    assert delivery.needs_install(dict(BUNDLE, tree='c' * 40))


def test_permission_failure_is_visible_and_never_prompts(private, monkeypatch):
    def fail(command, **options):
        assert command[1] == '-n' and options['stdin'] == subprocess.DEVNULL
        return SimpleNamespace(returncode=1, stderr='sudo: a password is required')
    monkeypatch.setattr(delivery.subprocess, 'run', fail)
    assert delivery.request_install(BUNDLE)['state'] == 'ERROR'
    assert 'permission' in delivery.status()['message']


def test_inflight_request_not_duplicated_and_interruption_is_visible(private, monkeypatch):
    delivery.write_json(private / 'status.json', dict(state='INSTALLING', updated=time.time(), **BUNDLE))
    monkeypatch.setattr(delivery, 'unit_active', lambda: True)
    monkeypatch.setattr(delivery.subprocess, 'run', lambda *a, **k: pytest.fail('Duplicate installer'))
    assert delivery.request_install(BUNDLE)['state'] == 'INSTALLING'
    monkeypatch.setattr(delivery, 'unit_active', lambda: False)
    delivery.write_json(private / 'status.json', dict(state='INSTALLING', updated=0, **BUNDLE))
    assert delivery.status()['state'] == 'ERROR'


def test_no_credentials_or_environment_in_public_status(private):
    delivery.write_json(private / 'status.json', dict(state='READY', password='never-expose', environment={'secret': 'x'}, **BUNDLE))
    delivery.write_json(private / 'initial-login.json', {'username': 'admin', 'password': 'test-password'})
    public = delivery.status()
    assert public['initial_login_available'] is True
    assert 'password' not in json.dumps(public) and 'environment' not in public and 'revision' not in public
    assert delivery.initial_login()['password'] == 'test-password'
    delivery.forget_initial_login()
    assert delivery.initial_login() == {}
    assert stat.S_IMODE((private / 'status.json').stat().st_mode) == 0o600


def test_git_tree_verifies_bytes_names_and_executable_modes(tmp_path):
    package = tmp_path / 'printer_app'
    package.mkdir()
    (package / 'file.py').write_text('print("hello")\n')
    (package / 'script.sh').write_text('#!/bin/bash\nexit 0\n')
    (package / 'script.sh').chmod(0o755)
    (package / 'nested').mkdir()
    (package / 'nested/file').write_text('nested')
    subprocess.run(['git', 'init', '-q', str(package)], check=True)
    subprocess.run(['git', '-C', str(package), 'add', '.'], check=True)
    expected = subprocess.check_output(['git', '-C', str(package), 'write-tree'], text=True).strip()
    shutil.rmtree(package / '.git')
    assert delivery.git_tree(package) == expected
    (package / 'script.sh').chmod(0o644)
    assert delivery.git_tree(package) != expected


def archive(package: Path, extra=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as zipped:
        for path in package.rglob('*'):
            if path.is_file():
                zipped.write(path, 'repo-revision/printer_app/' + path.relative_to(package).as_posix())
        if extra:
            zipped.writestr(*extra)
    return stream.getvalue()


def test_archive_is_pinned_validated_and_sandboxed(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'install.sh').write_text('echo installer')
    bundle = dict(BUNDLE, tree=delivery.git_tree(source))
    urls = []
    def response(request, **kwargs):
        urls.append(request.full_url)
        return io.BytesIO(archive(source))
    monkeypatch.setattr(delivery.urllib.request, 'urlopen', response)
    work = tmp_path / 'download'
    work.mkdir()
    assert (delivery.download_bundle(bundle, work) / 'install.sh').read_text() == 'echo installer'
    assert urls[0].endswith('/zipball/' + BUNDLE['revision'])
    work2 = tmp_path / 'tampered'
    work2.mkdir()
    with pytest.raises(ValueError, match='published Git tree'):
        delivery.download_bundle(BUNDLE, work2)


@pytest.mark.parametrize('name,mode', [('repo/printer_app/../../escape', 0o100644), ('repo/printer_app/link', 0o120777)])
def test_archive_refuses_traversal_and_links(tmp_path, monkeypatch, name, mode):
    info = zipfile.ZipInfo(name)
    info.external_attr = mode << 16
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as z:
        z.writestr(info, '/etc/passwd')
    monkeypatch.setattr(delivery.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(raw.getvalue()))
    with pytest.raises(ValueError):
        delivery.download_bundle(BUNDLE, tmp_path)
    assert not (tmp_path / 'escape').exists()


def test_installer_calls_only_standalone_cli_and_can_retry(private, monkeypatch):
    calls = []
    monkeypatch.setattr(delivery, 'remote_bundle', lambda: BUNDLE)
    def download(bundle, work):
        package = work / 'printer_app'
        package.mkdir()
        return package
    monkeypatch.setattr(delivery, 'download_bundle', download)
    def install(command, **kwargs):
        calls.append(command)
        assert '--unattended' in command
        assert '--initial-login-file' in command
        Path(command[-1]).write_text('{"port":5055}')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(delivery.subprocess, 'run', install)
    request = private / 'request.json'
    delivery.write_json(request, {'bundle': BUNDLE, 'request_id': 'fixture'})
    assert delivery.run_install(request) == 0
    assert delivery.status()['state'] == 'READY'
    assert calls[0][:1] == ['bash'] and calls[0][1].endswith('/printer_app/install.sh')
    assert not request.exists()
    monkeypatch.setattr(delivery.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    delivery.write_json(request, {'bundle': BUNDLE})
    assert delivery.run_install(request) == 1
    assert delivery.status()['state'] == 'ERROR'
    assert delivery.needs_install(BUNDLE)


def test_network_outage_is_an_install_error_not_a_stats_failure(private, monkeypatch):
    def outage():
        raise OSError('network down')
    monkeypatch.setattr(delivery, 'remote_bundle', outage)
    request = private / 'request.json'
    delivery.write_json(request, {'bundle': None})
    assert delivery.run_install(request) == 1
    assert delivery.status()['state'] == 'ERROR'


@pytest.fixture
def legacy_source(tmp_path):
    supplied = os.environ.get('LEGACY_SERVER_FILE')
    if supplied:
        return Path(supplied)
    value = subprocess.check_output(['git', 'show', '59c25897c7ee002e658608a48e89bb91089375eb:app/server.py'], cwd=ROOT)
    path = tmp_path / 'legacy-server.py'
    path.write_bytes(value)
    return path


def test_actual_old_zip_updater_delivers_bootstrap_without_printer_folder(tmp_path, legacy_source):
    installed = tmp_path / 'installed'
    installed.mkdir()
    (installed / 'app').mkdir()
    (installed / 'app/server.py').write_text('# previous release')
    old = functions(legacy_source, {'_safe_zip_member', '_find_update_root', 'install_update_zip'},
        dict(Path=Path, APP_ROOT=installed, UPDATE_DIR=tmp_path/'updates', tempfile=tempfile,
             shutil=shutil, zipfile=zipfile, time=time, subprocess=subprocess))
    package = tmp_path / 'new.zip'
    with zipfile.ZipFile(package, 'w') as z:
        for name in ('app/server.py', 'app/database.py', 'app/templates/display.html', 'app/templates/settings.html',
                     'app/update_delivery.py', 'requirements.txt', 'VERSION', 'printer_app/install.sh'):
            z.write(ROOT/name, 'repo/' + name)
    old['install_update_zip'](package)
    assert (installed/'app/update_delivery.py').read_bytes() == (ROOT/'app/update_delivery.py').read_bytes()
    assert not (installed/'printer_app').exists()  # This is the real old allowlist, not an imagined git checkout.
    assert (installed/'VERSION').read_text().strip() == '134'
    current = ast.parse((installed/'app/server.py').read_text())
    assert any(isinstance(n, ast.Expr) and ast.unparse(n) == 'update_delivery.start_initial_install()' for n in current.body)


def test_all_non_update_stats_functions_are_unchanged(legacy_source):
    before = {n.name: ast.dump(n) for n in ast.parse(legacy_source.read_text()).body if isinstance(n, ast.FunctionDef)}
    after = {n.name: ast.dump(n) for n in ast.parse((ROOT/'app/server.py').read_text()).body if isinstance(n, ast.FunctionDef)}
    allowed = {'github_remote_info', 'check_github_update', 'api_github_status'}
    assert {name for name in before if before[name] != after.get(name)} <= allowed


def backend(private):
    ns = dict(HARD_CODED_GITHUB_REPO=delivery.REPOSITORY, _GITHUB_UPDATE_LOCK=threading.Lock(),
        time=time, set_meta=lambda *a: None, software_version=lambda: '134', version_key=lambda x: (int(x),),
        github_remote_info=lambda repo: dict(repo=repo, branch='main', version='134', revision=BUNDLE['revision']),
        update_delivery=SimpleNamespace(remote_bundle=lambda revision: BUNDLE, needs_install=lambda b: True,
            request_install=lambda b: {'state':'QUEUED'}, status=lambda: {'state':'QUEUED'}),
        app=SimpleNamespace(logger=SimpleNamespace(exception=lambda *a: None)),
        UPDATE_DIR=private, tempfile=tempfile, os=os, Path=Path,
        download_github_repo_zip=lambda *a: None, install_update_zip=lambda *a: {'version':'135'})
    return functions(ROOT/'app/server.py', {'check_github_update', 'api_github_available'}, ns)


def test_printer_only_update_does_not_replace_or_restart_stats(private):
    ns = backend(private)
    ns['install_update_zip'] = lambda *a: pytest.fail('Stats source must not be installed for a printer-only update')
    result = ns['check_github_update'](install=True)
    assert result['installed'] is False
    assert result['printer_update_available'] is True
    assert result['bundled_app']['state'] == 'QUEUED'


def test_stats_update_succeeds_even_when_printer_check_fails(private):
    ns = backend(private)
    ns['github_remote_info'] = lambda repo: dict(repo=repo, branch='main', version='135', revision=BUNDLE['revision'])
    ns['update_delivery'].remote_bundle = lambda revision: (_ for _ in ()).throw(OSError('printer lookup offline'))
    assert ns['check_github_update'](install=True)['installed'] is True


def test_printer_login_requires_pin_unlock_and_same_origin(private):
    flask = pytest.importorskip('flask')
    app = flask.Flask('delivery-web-contract')
    locked = {'pin': False, 'unlocked': False}
    ns = functions(ROOT/'app/server.py', {'api_github_printer_login'}, dict(
        pin_is_set=lambda: locked['pin'], is_unlocked=lambda: locked['unlocked'],
        jsonify=flask.jsonify, abort=flask.abort, request=flask.request, update_delivery=delivery))
    app.add_url_rule('/login-handoff', view_func=ns['api_github_printer_login'], methods=['POST'])
    client = app.test_client()
    delivery.write_json(private/'initial-login.json', {'username':'admin','password':'initial-test-only'})
    headers = {'X-Requested-With': 'Stats-Update'}
    assert client.post('/login-handoff', json={}, headers=headers).status_code == 403
    locked.update(pin=True, unlocked=True)
    assert client.post('/login-handoff', json={}).status_code == 400
    assert client.post('/login-handoff', json={}, headers=dict(headers, Origin='https://other.example')).status_code == 403
    assert client.post('/login-handoff', json=['bad'], headers=headers).status_code == 400
    response = client.post('/login-handoff', json={}, headers=headers)
    assert response.json['login']['password'] == 'initial-test-only'
    assert 'no-store' in response.headers['Cache-Control']
    assert client.post('/login-handoff', json={'saved': True}, headers=headers).status_code == 200
    assert delivery.initial_login() == {}


def test_distribution_and_printer_import_boundaries():
    module = ast.parse((ROOT/'app/update_delivery.py').read_text())
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            assert not {n.name.split('.')[0] for n in node.names} & {'printer_app','server','database','flask','stats_core'}
        if isinstance(node, ast.ImportFrom):
            assert (node.module or '').split('.')[0] not in {'printer_app','server','database','flask','stats_core'}
    for path in (ROOT/'printer_app').glob('*.py'):
        assert 'import update_delivery' not in path.read_text()
        assert 'leaderboard-distribution' not in path.read_text()
    for path in (ROOT/'printer_app/systemd').glob('*.service'):
        text = path.read_text()
        assert not any(value in text for value in ('PartOf=', 'BindsTo=', 'pi-tableau-leaderboard'))
