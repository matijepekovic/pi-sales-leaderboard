"""Entrypoints for web, worker and administrative setup; all owned by printer_app."""
import argparse
import getpass
import logging
import os
from pathlib import Path
import secrets
from .config import Config


def configure():
    from dotenv import set_key
    from werkzeug.security import generate_password_hash
    path = Path(os.environ.get('PRINTER_ENV', str(Path.home() / '.config/printer-app/env')))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        path.write_text((Path(__file__).parent / '.env.example').read_text())
    path.chmod(0o600)
    password = getpass.getpass('Choose a printer UI password (at least 12 characters): ')
    if len(password) < 12 or password != getpass.getpass('Repeat printer UI password: '):
        raise SystemExit('Passwords did not match or were shorter than 12 characters')
    set_key(str(path), 'UI_PASSWORD_HASH', generate_password_hash(password))
    set_key(str(path), 'SESSION_SECRET', secrets.token_hex(32))
    path.chmod(0o600)
    print('Printer UI credentials saved. Configure Gmail in ' + str(path))


def main():
    parser = argparse.ArgumentParser(description='Independent printer automation')
    parser.add_argument('command', choices=['web', 'worker', 'init-db', 'backup-db', 'configure'])
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    if args.command == 'configure':
        configure()
        return
    config = Config.load()
    if args.command in {'init-db', 'backup-db'}:
        from .db import migrate, backup
        migrate(config.database)
        if args.command == 'backup-db':
            if not args.destination:
                parser.error('--destination is required for backup-db')
            backup(config.database, args.destination)
    elif args.command == 'web':
        from waitress import serve
        from .bootstrap import build_web
        serve(build_web(config), host=config.host, port=config.port, threads=4)
    else:
        from .bootstrap import build_worker
        build_worker(config).run()


if __name__ == '__main__':
    main()
