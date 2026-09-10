"""Repository distribution only: launch a detached installer, never a printer runtime.

Boundary: Git revision/tree in, public deployment receipt out. The only printer
entrypoint is its standalone install.sh CLI. No Flask, Stats DB, printer imports,
Gmail, CUPS or application scheduler belongs here. This file lives under app/
because old ZIP updaters already deliver that directory on the first upgrade.
"""
from __future__ import annotations

import fcntl
import pwd
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
import uuid
import zipfile

REPOSITORY = 'matijepekovic/pi-sales-leaderboard'
UNIT = 'printer-app-install.service'
MAX_ARCHIVE = 128 * 1024 * 1024
log = logging.getLogger(__name__)


def state_dir() -> Path:
    return Path.home() / '.local/share/leaderboard-distribution'


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def api_json(path: str) -> dict:
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + path,
        headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'leaderboard-distribution'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read(2 * 1024 * 1024))


def validate_bundle(bundle: dict) -> dict:
    if not isinstance(bundle, dict) or any(not re.fullmatch(r'[0-9a-f]{40}', str(bundle.get(k, '')))
                                          for k in ('revision', 'tree')):
        raise ValueError('Invalid bundled application revision')
    return {k: bundle[k] for k in ('revision', 'tree')}


def remote_bundle(revision: str | None = None) -> dict:
    if revision is None:
        revision = api_json('/git/ref/heads/main')['object']['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', str(revision)):
        raise ValueError('Invalid repository revision')
    tree = api_json('/git/trees/' + revision)
    entries = [e for e in tree.get('tree', []) if e.get('path') == 'printer_app' and e.get('type') == 'tree']
    if len(entries) != 1:
        raise ValueError('Update does not contain the printer application')
    return validate_bundle({'revision': revision, 'tree': entries[0]['sha']})


def needs_install(bundle: dict) -> bool:
    bundle = validate_bundle(bundle)
    receipt = read_json(state_dir() / 'status.json')
    return receipt.get('state') != 'READY' or receipt.get('tree') != bundle['tree']


def status() -> dict:
    receipt = read_json(state_dir() / 'status.json')
    # Never expose raw command output, paths, environment or initial credentials.
    result = {key: receipt[key] for key in ('state', 'message', 'updated', 'port') if key in receipt}
    result.setdefault('state', 'NOT INSTALLED')
    result.setdefault('message', 'The Update button installs the bundled printer application.')
    if result['state'] in ('QUEUED', 'INSTALLING') and time.time() - receipt.get('updated', 0) > 20:
        try:
            if not unit_active():
                result.update(state='ERROR', message='Printer setup was interrupted. Use Check for Updates → Update to retry.')
        except (OSError, subprocess.SubprocessError):
            pass
    result['initial_login_available'] = (state_dir() / 'initial-login.json').is_file()
    return result


def initial_login() -> dict:
    value = read_json(state_dir() / 'initial-login.json')
    return {key: str(value[key]) for key in ('username', 'password') if key in value}


def forget_initial_login() -> None:
    (state_dir() / 'initial-login.json').unlink(missing_ok=True)


def unit_active() -> bool:
    result = subprocess.run(['systemctl', 'show', '--property=ActiveState', '--value', UNIT],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, check=False)
    return result.returncode == 0 and result.stdout.strip() in ('active', 'activating', 'reloading', 'deactivating')


def request_install(bundle: dict | None = None, *, initial: bool = False) -> dict:
    """Only setup is triggered here. systemd owns the detached install process.

    A boot-time call bridges the old updater's allowlist once. Explicit Update
    calls can retry failures or deliver a new printer tree without a Stats restart.
    """
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'request.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = read_json(directory / 'status.json')
        if initial and receipt:
            return status()
        if bundle is not None:
            bundle = validate_bundle(bundle)
            if not needs_install(bundle):
                return status()
        try:
            if unit_active():
                return status()
            if pwd.getpwuid(os.geteuid()).pw_name != 'scoreboard' or os.geteuid() == 0:
                raise RuntimeError('Automatic printer setup must run as the scoreboard user.')
            # Never execute from the Stats folder: an update may replace it or
            # stop Stats while apt, pip or a printer migration is still running.
            source = Path(__file__).resolve().read_bytes()
            runner = directory / 'runners' / (hashlib.sha256(source).hexdigest() + '.py')
            runner.parent.mkdir(mode=0o700, exist_ok=True)
            if not runner.exists():
                runner.write_bytes(source)
                runner.chmod(0o600)
            request_id = uuid.uuid4().hex
            request_file = directory / 'requests' / (request_id + '.json')
            write_json(request_file, {'bundle': bundle, 'request_id': request_id})
            write_json(directory / 'status.json', dict(state='QUEUED', message='Printer installation queued.',
                updated=time.time(), request_id=request_id, **(bundle or {})))
            command = ['sudo', '-n', 'systemd-run', '--quiet', '--collect', '--no-block',
                '--unit=' + UNIT, '--uid=scoreboard', '--gid=scoreboard',
                '--property=Type=exec', '--property=UMask=0077', '--property=Nice=10',
                '--property=StandardOutput=journal', '--property=StandardError=journal',
                '--setenv=HOME=' + str(Path.home()), '--setenv=USER=scoreboard',
                '--setenv=LOGNAME=scoreboard', '--setenv=PYTHONUNBUFFERED=1',
                '--working-directory=' + str(directory), '/usr/bin/python3', str(runner), str(request_file)]
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=10, check=False)
            if result.returncode:
                raise RuntimeError('Automatic printer setup needs existing passwordless sudo permission '
                    'for systemd and package installation on this Pi. No permissions were changed.')
        except Exception as exc:
            message = str(exc) if isinstance(exc, RuntimeError) else 'Could not launch printer setup (' + type(exc).__name__ + ').'
            write_json(directory / 'status.json', dict(state='ERROR', message=message, updated=time.time()))
            log.warning('%s', message)
        return status()


def start_initial_install() -> None:
    """Upgrade bridge only; never let optional package installation break Stats."""
    try:
        request_install(initial=True)
    except Exception:
        log.exception('Bundled application setup could not be queued; Stats continues normally')


def git_tree(directory: Path) -> str:
    """Verify extracted bytes and executable bits against Git's published tree ID."""
    entries = []
    for path in directory.iterdir():
        if path.is_symlink():
            raise ValueError('Links are not allowed in a bundled application')
        name = path.name.encode('utf-8')
        if path.is_dir():
            mode, digest, key = b'40000', git_tree(path), name + b'/'
        elif path.is_file():
            data = path.read_bytes()
            mode = b'100755' if path.stat().st_mode & 0o111 else b'100644'
            digest = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            key = name
        else:
            raise ValueError('Unsupported bundle file')
        entries.append((key, mode + b' ' + name + b'\0' + bytes.fromhex(digest)))
    data = b''.join(record for _, record in sorted(entries))
    return hashlib.sha1(b'tree ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def download_bundle(bundle: dict, directory: Path) -> Path:
    bundle = validate_bundle(bundle)
    archive = directory / 'source.zip'
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/zipball/' + bundle['revision'],
                                     headers={'User-Agent': 'leaderboard-distribution'})
    with urllib.request.urlopen(request, timeout=60) as response, archive.open('xb') as target:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE:
                raise ValueError('Repository archive is too large')
            target.write(chunk)
    package = directory / 'printer_app'
    package.mkdir(mode=0o700)
    with zipfile.ZipFile(archive) as source:
        selected = set()
        total = 0
        for info in source.infolist():
            parts = PurePosixPath(info.filename).parts
            if len(parts) < 2 or parts[1] != 'printer_app':
                continue
            if PurePosixPath(info.filename).is_absolute() or '..' in parts or '\\' in info.filename:
                raise ValueError('Unsafe bundle path')
            if info.is_dir():
                continue
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError('Links/devices are not allowed in bundles')
            relative = Path(*parts[2:])
            if not relative.parts or relative in selected:
                raise ValueError('Duplicate or invalid bundle entry')
            selected.add(relative)
            total += info.file_size
            if total > MAX_ARCHIVE:
                raise ValueError('Extracted bundle is too large')
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with source.open(info) as incoming, target.open('xb') as output:
                shutil.copyfileobj(incoming, output)
            target.chmod(0o755 if mode & 0o111 else 0o644)
    if git_tree(package) != bundle['tree']:
        raise ValueError('Printer package does not match the published Git tree')
    return package


def run_install(request_file: Path) -> int:
    """Executed by systemd, outside the Stats service/cgroup and source tree."""
    os.umask(0o077)
    directory = state_dir()
    request_data = read_json(request_file)
    request_id = request_data.get('request_id', '')
    with (directory / 'installer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        def record(state: str, message: str, **fields) -> None:
            write_json(directory / 'status.json', dict(state=state, message=message,
                       request_id=request_id, updated=time.time(), **fields))
        try:
            record('INSTALLING', 'Checking the bundled printer release…')
            bundle = request_data.get('bundle') or remote_bundle()
            bundle = validate_bundle(bundle)
            record('INSTALLING', 'Downloading printer application…', **bundle)
            with tempfile.TemporaryDirectory(prefix='printer-setup-', dir=directory) as temporary:
                package = download_bundle(bundle, Path(temporary))
                result_file = Path(temporary) / 'deployment.json'
                record('INSTALLING', 'Installing printer dependencies and its separate services…', **bundle)
                result = subprocess.run(['bash', str(package / 'install.sh'), '--unattended',
                    '--initial-login-file', str(directory / 'initial-login.json'),
                    '--result-file', str(result_file)], stdin=subprocess.DEVNULL, check=False)
                if result.returncode:
                    raise RuntimeError('Printer installer failed. Stats is unaffected. Check printer-app-install logs; '
                                       'then use Check for Updates → Update to retry.')
                deployment = read_json(result_file)
                port = int(deployment['port'])
                if not 1 <= port <= 65535:
                    raise ValueError('Invalid printer port')
                record('READY', 'Printer app installed. Open its separate Print Control page.', port=port, **bundle)
            return 0
        except Exception as exc:
            message = str(exc) if isinstance(exc, RuntimeError) else 'Printer setup failed (' + type(exc).__name__ + '). Use Update to retry.'
            record('ERROR', message)
            log.error('%s', message)
            return 1
        finally:
            request_file.unlink(missing_ok=True)


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 2:
        raise SystemExit('Expected an installation request file')
    raise SystemExit(run_install(Path(sys.argv[1])))
