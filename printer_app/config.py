"""Configuration belongs exclusively to printer-app; never load the repository .env."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


def clean_text(value: object, limit: int = 1000) -> str:
    return ''.join(c if c.isprintable() or c == '\n' else ' ' for c in str(value))[:limit]


def safe_name(value: str, fallback: str = 'attachment') -> str:
    # Paths, options, collisions and user-provided names never select an output directory.
    value = value.replace('\\', '/').rsplit('/', 1)[-1]
    value = re.sub(r'[^\w. -]', '_', value, flags=re.UNICODE).strip(' .-')
    return value[:150] or fallback


def load_env(path: Path) -> None:
    """Small literal env reader. No shell expansion, command execution or dotenv search."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError('Invalid printer-app environment file')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Config:
    data_dir: Path
    email_user: str = ''
    email_password: str = ''
    mailbox: str = 'INBOX'
    subject_contains: str = ''
    from_contains: str = ''
    lookback_days: int = 3
    poll_seconds: int = 60
    queue: str = 'konicaa'
    host: str = '0.0.0.0'
    port: int = 5055
    ui_user: str = 'admin'
    password_hash: str = ''
    secret_key: str = ''
    secure_cookie: bool = False
    timezone: str = 'America/Los_Angeles'
    attachment_limit: int = 20 * 1024 * 1024
    conversion_timeout: int = 120
    retry_seconds: int = 60
    libreoffice: str = '/usr/bin/libreoffice'

    @property
    def db_path(self) -> Path:
        return self.data_dir / 'printer_app.db'

    @classmethod
    def from_env(cls) -> 'Config':
        load_env(Path(os.environ.get('PRINTER_ENV_FILE', '~/.config/printer-app/env')).expanduser())
        e = os.environ
        cfg = cls(
            data_dir=Path(e.get('PRINTER_DATA_DIR', '~/.local/share/printer-app')).expanduser().resolve(),
            email_user=e.get('EMAIL_USER', '').strip(),
            email_password=e.get('EMAIL_APP_PASSWORD', '').replace(' ', ''),
            mailbox=e.get('EMAIL_MAILBOX', 'INBOX'),
            subject_contains=e.get('EMAIL_SUBJECT_CONTAINS', ''),
            from_contains=e.get('EMAIL_FROM_CONTAINS', ''),
            lookback_days=int(e.get('EMAIL_LOOKBACK_DAYS', '3')),
            poll_seconds=int(e.get('EMAIL_POLL_SECONDS', '60')),
            queue=e.get('PRINTER_QUEUE', 'konicaa'),
            host=e.get('PRINTER_HOST', '0.0.0.0'),
            port=int(e.get('PRINTER_PORT', '5055')),
            ui_user=e.get('PRINTER_UI_USER', 'admin'),
            password_hash=e.get('PRINTER_UI_PASSWORD_HASH', ''),
            secret_key=e.get('PRINTER_SECRET_KEY', ''),
            secure_cookie=e.get('PRINTER_SECURE_COOKIE', '0') == '1',
            timezone=e.get('PRINTER_TIMEZONE', 'America/Los_Angeles'),
            attachment_limit=int(e.get('MAX_ATTACHMENT_MB', '20')) * 1024 * 1024,
            conversion_timeout=int(e.get('CONVERSION_TIMEOUT_SECONDS', '120')),
            retry_seconds=int(e.get('PRINTER_RETRY_SECONDS', '60')),
            libreoffice=e.get('LIBREOFFICE_BIN', '/usr/bin/libreoffice'),
        )
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,126}', cfg.queue):
            raise ValueError('Invalid PRINTER_QUEUE')
        if not (1 <= cfg.lookback_days <= 3650 and 10 <= cfg.poll_seconds <= 86400):
            raise ValueError('Invalid email lookback or poll interval')
        if not (1 <= cfg.port <= 65535 and 1 <= cfg.attachment_limit // 1048576 <= 100):
            raise ValueError('Invalid port or attachment size limit')
        if not (10 <= cfg.conversion_timeout <= 600 and 10 <= cfg.retry_seconds <= 3600):
            raise ValueError('Invalid conversion or retry interval')
        ZoneInfo(cfg.timezone)
        cfg.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return cfg
