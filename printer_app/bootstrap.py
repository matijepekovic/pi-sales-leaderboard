"""Local setup commands; secrets are created outside source control."""
import argparse
import getpass
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from werkzeug.security import generate_password_hash

from .config import Config
from .db import Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init', 'migrate', 'paths', 'set-password'])
    parser.add_argument('--initial-login-file', type=Path, help='Private credential handoff for unattended installation')
    args = parser.parse_args()
    os.umask(0o077)
    env = Path(os.environ.get('PRINTER_ENV_FILE', '~/.config/printer-app/env')).expanduser()
    if args.action == 'init':
        if env.exists():
            print('Existing printer environment preserved: ' + str(env))
            return
        env.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        password = secrets.token_urlsafe(18)
        if args.initial_login_file:
            # Persist the handoff before the environment so an interrupted first
            # install can recover the same password without leaking it to logs.
            target = args.initial_login_file.expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if target.exists():
                previous = json.loads(target.read_text())
                if previous.get('username') != 'admin' or len(previous.get('password', '')) < 20:
                    raise SystemExit('Invalid private initial-login handoff; refusing to overwrite it')
                password = previous['password']
            else:
                temporary = target.with_name(target.name + '.new')
                with temporary.open('w') as stream:
                    os.chmod(temporary, 0o600)
                    json.dump({'username': 'admin', 'password': password}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(target)
        text = (Path(__file__).with_name('.env.example')).read_text()
        text = text.replace('PRINTER_UI_PASSWORD_HASH=\n', 'PRINTER_UI_PASSWORD_HASH=' + generate_password_hash(password, method='pbkdf2:sha256:600000') + '\n')
        text = text.replace('PRINTER_SECRET_KEY=\n', 'PRINTER_SECRET_KEY=' + secrets.token_hex(32) + '\n')
        with env.open('x') as stream:
            stream.write(text)
        env.chmod(0o600)
        if args.initial_login_file:
            # Setup-only handoff; never emit an unattended password into journals.
            print('Printer UI credentials created; private setup handoff saved.')
        else:
            print('Printer UI username: admin\nInitial printer UI password: ' + password)
            print('Save this password. It is shown only once. Gmail is not configured yet.')
        return
    if args.action == 'set-password':
        if not env.exists():
            raise SystemExit('Run init first')
        first = getpass.getpass('New printer UI password (at least 12 characters): ')
        if len(first) < 12 or first != getpass.getpass('Repeat password: '):
            raise SystemExit('Passwords do not match or are too short')
        lines = [line for line in env.read_text().splitlines() if not line.startswith('PRINTER_UI_PASSWORD_HASH=')]
        lines.append('PRINTER_UI_PASSWORD_HASH=' + generate_password_hash(first, method='pbkdf2:sha256:600000'))
        temp = env.with_name(env.name + '.new')
        temp.write_text('\n'.join(lines) + '\n')
        temp.chmod(0o600)
        temp.replace(env)
        print('Password updated. Restart printer-app-web.service to invalidate old sessions.')
        return
    cfg = Config.from_env()
    if args.action == 'paths':
        print(json.dumps(dict(data=str(cfg.data_dir), env=str(env), port=cfg.port, host=cfg.host)))
        return
    if cfg.db_path.exists():
        backups = cfg.data_dir / 'backups'
        backups.mkdir(mode=0o700, exist_ok=True)
        target = backups / ('printer-app-' + time.strftime('%Y%m%d-%H%M%S') + '.db')
        with sqlite3.connect(cfg.db_path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
    Database(cfg.db_path)
    print('Printer database initialized/migrated: ' + str(cfg.db_path))


if __name__ == '__main__':
    main()
