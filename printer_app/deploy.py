#!/usr/bin/env python3
"""Deploy immutable printer-only releases. Never imports the host application."""
import argparse
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

UNITS = ('printer-app-web.service', 'printer-app-worker.service')
IGNORED = {'__pycache__', '.pytest_cache', '.venv', 'data', '.git'}


def source_files(source):
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if any(part in IGNORED for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError('Source symlinks are not allowed in printer releases')
        if not path.is_file() or path.suffix in {'.pyc', '.db'} or (path.name.startswith('.env') and path.name != '.env.example'):
            continue
        yield path, relative


def source_hash(source):
    digest = hashlib.sha256()
    for path, relative in source_files(source):
        digest.update(str(relative).encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def link(target, destination):
    temporary = destination.with_name(destination.name + '.new')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, destination)


def install_units(source, home):
    with tempfile.TemporaryDirectory() as temporary:
        for unit in UNITS:
            path = Path(temporary) / unit
            path.write_text((source / 'systemd' / unit).read_text().replace('@HOME@', str(home)))
            run(['sudo', 'install', '-m', '0644', path, '/etc/systemd/system/' + unit])
    run(['sudo', 'systemctl', 'daemon-reload'])


def health(port):
    for _ in range(45):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                if all(json.load(response).values()):
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError('Printer deployment health check failed; inspect its journal')


def port_for(release):
    result = run([release / '.venv/bin/python', '-c', 'from printer_app.config import Config; print(Config.load().port)'], cwd=release, capture_output=True, text=True)
    return int(result.stdout.strip())


def activate(release, state, home, initial=False):
    current, previous = state / 'current', state / 'previous'
    old = current.resolve() if current.is_symlink() else None
    install_units(release / 'printer_app', home)
    run(['sudo', 'systemctl', 'stop', *UNITS])
    try:
        if old and (old / '.venv/bin/python').exists():
            backups = state / 'backups'
            backups.mkdir(exist_ok=True, mode=0o700)
            run([old / '.venv/bin/python', '-m', 'printer_app', 'backup-db', '--destination', backups / f'pre-deploy-{time.time_ns()}.db'], cwd=old)
        run([release / '.venv/bin/python', '-m', 'printer_app', 'init-db'], cwd=release)
        link(release, current)
        if initial:
            run(['sudo', 'systemctl', 'enable', *UNITS])
        run(['sudo', 'systemctl', 'start', *UNITS])
        health(port_for(release))
    except Exception:
        if old:
            link(old, current)
            install_units(old / 'printer_app', home)
            run(['sudo', 'systemctl', 'restart', *UNITS])
        raise
    if old and old != release:
        link(old, previous)
    print(f'Printer services healthy. URL: http://<pi-ip>:{port_for(release)}/system/print-control')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'deploy', 'rollback'])
    args = parser.parse_args()
    if getpass.getuser() != 'scoreboard' or os.geteuid() == 0:
        raise SystemExit('Run as scoreboard. Only service installation/restarts use sudo.')
    if sys.version_info < (3, 10):
        raise SystemExit('Python 3.10+ is required')
    os.umask(0o077)
    home = Path.home()
    state = home / '.local/share/printer-app'
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / 'deploy.lock').open('a') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if args.action == 'rollback':
            previous = state / 'previous'
            if not previous.is_symlink():
                raise SystemExit('No previous printer release is available')
            activate(previous.resolve(), state, home)
            return
        source = Path(__file__).resolve().parent
        fingerprint = source_hash(source)
        release = state / 'releases' / fingerprint[:20]
        current = state / 'current'
        if current.is_symlink() and current.resolve() == release:
            print('Printer code unchanged; no dependencies installed and no service restarted.')
            return
        if not (release / '.ready').exists():
            if release.exists():
                shutil.rmtree(release)
            package = release / 'printer_app'
            package.mkdir(parents=True, mode=0o700)
            for path, relative in source_files(source):
                destination = package / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            run([sys.executable, '-m', 'venv', release / '.venv'])
            run([release / '.venv/bin/python', '-m', 'pip', 'install', '-r', package / 'requirements.txt'])
            run([release / '.venv/bin/python', '-m', 'compileall', '-q', package])
            (release / '.ready').write_text(fingerprint + '\n')
        env = home / '.config/printer-app/env'
        if args.action == 'install' and not env.exists():
            run([release / '.venv/bin/python', '-m', 'printer_app', 'configure'], cwd=release)
        if not env.exists():
            raise SystemExit('Printer environment is missing; run install.sh first')
        if env.stat().st_mode & 0o077:
            raise SystemExit('Printer environment must be private: chmod 600 ~/.config/printer-app/env')
        activate(release, state, home, initial=args.action == 'install')


if __name__ == '__main__':
    main()
