"""Local setup commands; secrets are created outside source control."""
import argparse
import json
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

from .admin_auth import ADMIN_USERNAME, AdminAuthService
from .admin_auth_repository import AdminAuthRepository
from .config import Config
from .db import Database


def write_initial_login(target, password):
    value = {'username': ADMIN_USERNAME, 'password': password}
    if target is None:
        print('Temporary printer admin username: ' + ADMIN_USERNAME)
        print('Temporary printer admin password: ' + password)
        print('Sign in once and choose a new password immediately.')
        return
    target = target.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_name('.' + target.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
        target.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init', 'migrate', 'ensure-admin', 'paths'])
    parser.add_argument('--initial-login-file', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    env = Path(os.environ.get('PRINTER_ENV_FILE', '~/.config/printer-app/env')).expanduser()

    if args.action == 'init':
        if env.exists():
            print('Existing printer environment preserved: ' + str(env))
            return
        env.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        text = (Path(__file__).with_name('.env.example')).read_text()
        text = text.replace('PRINTER_SECRET_KEY=\n', 'PRINTER_SECRET_KEY=' + secrets.token_hex(32) + '\n')
        with env.open('x') as stream:
            stream.write(text)
        env.chmod(0o600)
        print('Printer environment created: ' + str(env))
        return

    cfg = Config.from_env()
    if args.action == 'paths':
        print(json.dumps(dict(data=str(cfg.data_dir), env=str(env), port=cfg.port, host=cfg.host)))
        return

    if args.action == 'migrate':
        if cfg.db_path.exists():
            backups = cfg.data_dir / 'backups'
            backups.mkdir(mode=0o700, exist_ok=True)
            target = backups / ('printer-app-' + time.strftime('%Y%m%d-%H%M%S') + '.db')
            with sqlite3.connect(cfg.db_path) as source, sqlite3.connect(target) as destination:
                source.backup(destination)
        Database(cfg.db_path)
        print('Printer database initialized/migrated: ' + str(cfg.db_path))
        return

    # Run only after migrate so an existing database was backed up before the
    # additive admin-auth schema/credential becomes active.
    db = Database(cfg.db_path)
    auth = AdminAuthService(AdminAuthRepository(db))
    if auth.has_credential():
        print('Existing printer admin credential preserved.')
        return

    # The private handoff is created before the hash becomes active. If handoff
    # creation fails, no unknown credential can lock the administrator out.
    password = auth.generate_temporary_password()
    write_initial_login(args.initial_login_file, password)
    try:
        if not auth.install_temporary_password(password):
            if args.initial_login_file:
                args.initial_login_file.expanduser().unlink(missing_ok=True)
            print('Existing printer admin credential preserved.')
            return
    except Exception:
        if args.initial_login_file:
            args.initial_login_file.expanduser().unlink(missing_ok=True)
        raise
    print('Printer admin login initialized. Sign in once and choose a new password.')


if __name__ == '__main__':
    main()
