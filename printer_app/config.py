"""Configuration belongs exclusively to printer-app; never load the repository .env."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from .print_options import PrintOptions, FIELDS as PRINT_FIELDS
from .print_schedule import PrintSchedule, FIELDS as SCHEDULE_FIELDS


def clean_text(value: object, limit: int = 1000) -> str:
    return ''.join(c if c.isprintable() or c == '\n' else ' ' for c in str(value))[:limit]


def safe_name(value: str, fallback: str = 'attachment') -> str:
    # Paths, options, collisions and user-provided names never select an output directory.
    value = value.replace('\\', '/').rsplit('/', 1)[-1]
    value = re.sub(r'[^\w. -]', '_', value, flags=re.UNICODE).strip(' .-')
    return value[:150] or fallback


def environment_file() -> Path:
    return Path(os.environ.get('PRINTER_ENV_FILE', '~/.config/printer-app/env')).expanduser()


def parse_env(text: str) -> dict[str, str]:
    """Literal env syntax; no expansion, evaluation, or shell execution."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError('Invalid printer-app environment file')
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            quote, value = value[0], value[1:-1]
            if quote == '"':
                value = re.sub(r'\\(["\\$`])', r'\1', value)
        values[key] = value
    return values


@dataclass(frozen=True)
class Config:
    data_dir: Path
    email_user: str = ''
    email_password: str = field(default='', repr=False)
    email_enabled: bool = True
    mailbox: str = 'INBOX'
    subject_contains: str = ''
    from_contains: str = ''
    lookback_days: int = 3
    poll_seconds: int = 60
    queue: str = 'konicaa'
    host: str = '0.0.0.0'
    port: int = 5055
    secret_key: str = field(default='', repr=False)
    # Existing v134 installs may still contain this hash. It is ignored by the
    # UI and retained only so the worker can redact it if it appears in logs.
    password_hash: str = field(default='', repr=False)
    secure_cookie: bool = False
    timezone: str = 'America/Los_Angeles'
    attachment_limit: int = 20 * 1024 * 1024
    conversion_timeout: int = 120
    retry_seconds: int = 60
    libreoffice: str = '/usr/bin/libreoffice'
    env_file: Path | None = None
    print_options: PrintOptions = field(default_factory=PrintOptions)
    print_schedule: PrintSchedule = field(default_factory=PrintSchedule)

    @property
    def db_path(self) -> Path:
        return self.data_dir / 'printer_app.db'

    @classmethod
    def from_env(cls) -> 'Config':
        path = environment_file()
        e = parse_env(path.read_text()) if path.exists() else {}
        e.update(os.environ)  # Keep explicit process overrides at startup.
        # Live editable settings are re-read by SettingsService, not os.environ.
        cfg = cls(
            data_dir=Path(e.get('PRINTER_DATA_DIR', '~/.local/share/printer-app')).expanduser().resolve(),
            env_file=path,
            print_options=PrintOptions().apply({k: v for k, v in e.items() if k in PRINT_FIELDS}),
            print_schedule=PrintSchedule().apply({k: v for k, v in e.items() if k in SCHEDULE_FIELDS}),
            email_enabled=e.get('EMAIL_ENABLED', '1') == '1',
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
            secret_key=e.get('PRINTER_SECRET_KEY', ''),
            password_hash=e.get('PRINTER_UI_PASSWORD_HASH', ''),
            secure_cookie=e.get('PRINTER_SECURE_COOKIE', '0') == '1',
            timezone=e.get('PRINTER_TIMEZONE', 'America/Los_Angeles'),
            attachment_limit=int(e.get('MAX_ATTACHMENT_MB', '20')) * 1024 * 1024,
            conversion_timeout=int(e.get('CONVERSION_TIMEOUT_SECONDS', '120')),
            retry_seconds=int(e.get('PRINTER_RETRY_SECONDS', '60')),
            libreoffice=e.get('LIBREOFFICE_BIN', '/usr/bin/libreoffice'),
        )
        cfg.validate()
        cfg.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return cfg

    def validate(self) -> None:
        cfg = self
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,126}', cfg.queue):
            raise ValueError('Invalid PRINTER_QUEUE')
        if not (1 <= cfg.lookback_days <= 3650 and 10 <= cfg.poll_seconds <= 86400):
            raise ValueError('Invalid email lookback or poll interval')
        if not (1 <= cfg.port <= 65535 and 1 <= cfg.attachment_limit // 1048576 <= 100):
            raise ValueError('Invalid port or attachment size limit')
        if not (10 <= cfg.conversion_timeout <= 600 and 10 <= cfg.retry_seconds <= 3600):
            raise ValueError('Invalid conversion or retry interval')
        ZoneInfo(cfg.timezone)
