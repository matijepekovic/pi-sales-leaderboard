#!/usr/bin/env python3
"""Isolated, content-addressed releases. Never operate on the Stats installation."""
from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

UNITS = ['printer-app-web.service', 'printer-app-worker.service']
SKIP = {'data', '.venv', '__pycache__', '.pytest_cache', '.git'}


def run(command, *, unattended=False, **kwargs):
    if unattended:
        kwargs.setdefault('stdin', subprocess.DEVNULL)
        if command[0] == 'sudo':
            command = ['sudo', '-n', *command[1:]]
    return subprocess.run(command, check=True, **kwargs)


def source_files(source: Path):
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if any(part in SKIP for part in relative.parts) or path.is_symlink():
            continue
        if path.name.startswith('.env') and path.name != '.env.example':
            continue
        if path.is_file() and path.suffix not in ('.pyc', '.db', '.log'):
            yield path, relative


def fingerprint(source: Path) -> str:
    digest = hashlib.sha256()
    for path, relative in source_files(source):
        digest.update(str(relative).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()[:20]


def atomic_link(link: Path, target: Path):
    temporary = link.with_name('.' + link.name + '-' + uuid.uuid4().hex)
    temporary.symlink_to(target)
    temporary.replace(link)


def release_paths(release: Path):
    result = run([str(release / '.venv/bin/python'), '-m', 'printer_app.bootstrap', 'paths'],
                 cwd=release, capture_output=True, text=True)
    return json.loads(result.stdout)


def install_units(release: Path, base: Path, paths: dict, *, unattended=False):
    with tempfile.TemporaryDirectory() as temp:
        for unit in UNITS:
            text = (release / 'printer_app/systemd' / unit).read_text()
            for key, value in {'BASE': str(base), 'ENV': paths['env'], 'DATA': paths['data']}.items():
                if any(c.isspace() for c in value) or any(c in value for c in ('%', '\n', '"', '\\')):
                    raise ValueError('Installation paths must not contain whitespace, percent signs or quotes')
                text = text.replace('@' + key + '@', value)
            target = Path(temp) / unit
            target.write_text(text)
            run(['sudo', 'install', '-m', '0644', str(target), '/etc/systemd/system/' + unit], unattended=unattended)
    run(['sudo', 'systemctl', 'daemon-reload'], unattended=unattended)
    run(['sudo', 'systemctl', 'enable', *UNITS], unattended=unattended)


def healthy(paths: dict) -> bool:
    host = '127.0.0.1' if paths['host'] == '0.0.0.0' else paths['host']
    for _ in range(30):
        try:
            with urllib.request.urlopen(f'http://{host}:{paths["port"]}/health', timeout=2) as response:
                if response.status == 200 and all(json.load(response).values()):
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def activate(base: Path, release: Path, *, unattended=False):
    current = base / 'current'
    old = current.resolve() if current.is_symlink() else None
    paths = release_paths(release)
    install_units(release, base, paths, unattended=unattended)
    if old and old != release:
        atomic_link(base / 'previous', old)
    atomic_link(current, release)
    try:
        run(['sudo', 'systemctl', 'restart', *UNITS], unattended=unattended)
        if not healthy(paths):
            raise RuntimeError('Printer health check failed after deployment')
    except Exception:
        if old and old != release:
            atomic_link(current, old)
            install_units(old, base, release_paths(old), unattended=unattended)
            run(['sudo', 'systemctl', 'restart', *UNITS], unattended=unattended)
            print('Restored previous printer release. Database was NOT rolled back.', file=sys.stderr)
        raise
    print('Printer release: ' + release.name)
    print(f'Web URL: http://<pi-ip>:{paths["port"]}/system/print-control')
    print('Database: ' + paths['data'] + '/printer_app.db')
    print('Stats files, service and database were not touched.')


def save_result(target: Path | None, release: Path, *, changed: bool):
    if target is not None:
        paths = release_paths(release)
        target.write_text(json.dumps({'port': paths['port'], 'changed': changed}), encoding='utf-8')
        target.chmod(0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'update', 'rollback'])
    parser.add_argument('--unattended', action='store_true')
    parser.add_argument('--initial-login-file', type=Path)
    parser.add_argument('--result-file', type=Path)
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit('Python 3.10 or newer is required')
    if getpass.getuser() != 'scoreboard' or os.geteuid() == 0:
        raise SystemExit('Run as scoreboard, not root. sudo is used only for system setup/service management.')
    os.umask(0o077)
    base = Path.home() / '.local/lib/printer-app'
    releases = base / 'releases'
    releases.mkdir(parents=True, exist_ok=True)
    with (base / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == 'rollback':
            previous = base / 'previous'
            if not previous.is_symlink() or not (previous.resolve() / '.ready').exists():
                raise SystemExit('No previous printer release is available')
            release = previous.resolve()
            # Refuse incompatible schemas; NEVER restore an older deduplication DB.
            run([str(release / '.venv/bin/python'), '-m', 'printer_app.bootstrap', 'migrate'], cwd=release)
            activate(base, release, unattended=args.unattended)
            return
        source = Path(__file__).resolve().parent
        release = releases / fingerprint(source)
        current = base / 'current'
        if current.is_symlink() and current.resolve() == release and (release / '.ready').exists():
            if args.action == 'install':
                activate(base, release, unattended=args.unattended)
            else:
                print('printer_app is unchanged; no dependency install or service restart.')
            save_result(args.result_file, release, changed=False)
            return
        if not (release / '.ready').exists():
            if current.is_symlink() and current.resolve() == release:
                raise RuntimeError('Active printer release is incomplete; refusing to delete it')
            if release.exists():
                shutil.rmtree(release)
            (release / 'printer_app').mkdir(parents=True)
            for path, relative in source_files(source):
                target = release / 'printer_app' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            run([sys.executable, '-m', 'venv', str(release / '.venv')])
            python = str(release / '.venv/bin/python')
            run([python, '-m', 'pip', 'install', '-r', str(release / 'printer_app/requirements.txt')])
            run([python, '-m', 'compileall', '-q', str(release / 'printer_app')])
            (release / '.ready').write_text(release.name + '\n')
        python = str(release / '.venv/bin/python')
        init = [python, '-m', 'printer_app.bootstrap', 'init']
        if args.initial_login_file:
            init.extend(['--initial-login-file', str(args.initial_login_file)])
        elif args.unattended:
            raise SystemExit('Unattended setup requires a private --initial-login-file')
        run(init, cwd=release)
        run([python, '-m', 'printer_app.bootstrap', 'migrate'], cwd=release)
        activate(base, release, unattended=args.unattended)
        save_result(args.result_file, release, changed=True)


if __name__ == '__main__':
    main()
