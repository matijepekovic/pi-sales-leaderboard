"""Local setup commands; secrets are created outside source control."""
import argparse
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from .config import Config
from .db import Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init', 'migrate', 'paths'])
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
        print('Printer control UI has no login. Gmail is not configured yet.')
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
