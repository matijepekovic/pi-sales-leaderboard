"""Private Outlook sandbox mailbox settings, OAuth registration and staged files."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from ..config import environment_file, parse_env, safe_name


class SandboxError(ValueError):
    """An actionable but non-sensitive Outlook sandbox error."""


@dataclass(frozen=True)
class OutlookConfig:
    """Mailbox choices users can change without knowing Microsoft app identifiers."""
    mailbox: str
    folder: str

    @classmethod
    def from_form(cls, values: dict[str, str]) -> 'OutlookConfig':
        if set(values) - {'mailbox', 'folder'}:
            raise SandboxError('Only Outlook email and folder can be changed here.')
        mailbox = str(values.get('mailbox', '')).strip()
        folder = str(values.get('folder', '')).strip()
        if (not re.fullmatch(r'[^\s@]{1,100}@[^\s@]{1,150}', mailbox)
                or any(ord(c) < 33 or ord(c) == 127 for c in mailbox)):
            raise SandboxError('Enter a valid work Outlook email address.')
        if not folder or len(folder) > 200 or any(ord(c) < 32 or ord(c) > 126 for c in folder):
            raise SandboxError('Enter the exact Outlook IMAP folder name (such as Printer).')
        return cls(mailbox, folder)

    def identity(self) -> str:
        return self.mailbox.casefold()


@dataclass(frozen=True)
class OAuthRegistration:
    """Provisioned once by the printer administrator, not by mailbox users."""
    client_id: str
    tenant: str = 'organizations'

    @classmethod
    def checked(cls, client_id: str, tenant: str) -> 'OAuthRegistration':
        try:
            client = str(uuid.UUID(client_id))
        except (ValueError, TypeError, AttributeError):
            raise SandboxError('The printer OAuth app registration is invalid. Check OUTLOOK_OAUTH_CLIENT_ID.') from None
        tenant = str(tenant or 'organizations').strip().lower()
        valid_domain = bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', tenant))
        if tenant != 'organizations' and not valid_domain:
            raise SandboxError('The printer OAuth tenant setting is invalid.')
        return cls(client, tenant)


class SandboxRepository:
    """No SQL queue, print storage, or Gmail settings are accessible here."""

    def __init__(self, data_dir: Path, env_file: Path | None = None):
        self.root = Path(data_dir) / 'outlook_sandbox'
        self.settings_path = self.root / 'settings.json'
        self.tokens_path = self.root / 'tokens.json'
        self.staged_root = self.root / 'staged'
        self.env_file = Path(env_file) if env_file is not None else environment_file()

    @staticmethod
    def _private_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        fd, temp = tempfile.mkstemp(prefix='.write-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def _settings(self) -> dict:
        if not self.settings_path.exists():
            return {}
        values = json.loads(self.settings_path.read_text(encoding='utf-8'))
        if not isinstance(values, dict):
            raise SandboxError('Outlook sandbox configuration is unreadable.')
        return values

    def read_config(self) -> OutlookConfig | None:
        values = self._settings()
        if not values:
            return None
        # Prior sandbox versions stored client_id and tenant_id in this file.
        # Keep reading the mailbox without exposing those old fields in the UI.
        return OutlookConfig.from_form({key: values.get(key, '') for key in ('mailbox', 'folder')})

    def registration(self) -> OAuthRegistration | None:
        """Resolve trusted Microsoft app configuration without asking mailbox users.

        Use the Pi's existing private environment file; allow explicit process
        overrides. Retain legacy app registration for previous sandbox users.
        """
        settings = parse_env(self.env_file.read_text(encoding='utf-8')) if self.env_file.exists() else {}
        settings.update(os.environ)
        client_id = str(settings.get('OUTLOOK_OAUTH_CLIENT_ID', '')).strip()
        tenant = str(settings.get('OUTLOOK_OAUTH_TENANT', 'organizations')).strip()
        if not client_id:
            legacy = self._settings()
            client_id = str(legacy.get('client_id', '')).strip()
            tenant = str(legacy.get('tenant_id', 'organizations')).strip()
        if not client_id:
            return None
        return OAuthRegistration.checked(client_id, tenant)

    def save_config(self, cfg: OutlookConfig) -> None:
        current = self.read_config()
        # Preserve any legacy app registration, so upgrades don't invalidate an
        # already-approved OAuth client or discard an existing token cache.
        values = self._settings()
        values.update(mailbox=cfg.mailbox, folder=cfg.folder)
        self._private_write(self.settings_path, json.dumps(values, sort_keys=True).encode('utf-8'))
        if current is not None and current.identity() != cfg.identity():
            self.clear_tokens()

    def read_tokens(self) -> str:
        return self.tokens_path.read_text(encoding='utf-8') if self.tokens_path.exists() else ''

    def write_tokens(self, data: str) -> None:
        self._private_write(self.tokens_path, data.encode('utf-8'))

    def clear_tokens(self) -> None:
        self.tokens_path.unlink(missing_ok=True)

    @staticmethod
    def stage_id(cfg: OutlookConfig, validity: str, uid: str) -> str:
        key = '\0'.join((cfg.mailbox.casefold(), cfg.folder, validity, uid))
        return hashlib.sha256(key.encode('utf-8')).hexdigest()

    def save_attachments(self, stage_id: str, attachments: list[tuple[str, bytes]]) -> list[dict]:
        if not re.fullmatch(r'[0-9a-f]{64}', stage_id):
            raise SandboxError('Invalid sandbox item.')
        target = self.staged_root / stage_id
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        items = []
        for number, (filename, payload) in enumerate(attachments):
            name = f'{number + 1:02d}-{safe_name(filename)}'
            self._private_write(target / name, payload)
            items.append(dict(name=name, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), index=number))
        self._private_write(target / 'manifest.json', json.dumps(items).encode('utf-8'))
        return items

    def file(self, stage_id: str, index: int) -> tuple[Path, str]:
        if not re.fullmatch(r'[0-9a-f]{64}', stage_id) or not (0 <= index < 100):
            raise SandboxError('Invalid sandbox item.')
        folder = self.staged_root / stage_id
        try:
            items = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
            item = items[index]
            name = item['name']
            if not isinstance(name, str) or not name or name in ('.', '..') or '/' in name or '\\' in name:
                raise ValueError
            target = folder / name
            if not target.is_file() or target.is_symlink():
                raise ValueError
            return target, name
        except (OSError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            raise SandboxError('Sandbox attachment not found.') from None
