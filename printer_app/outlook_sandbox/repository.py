"""Private Outlook sandbox configuration, token cache, and staged file storage."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from ..config import safe_name


class SandboxError(ValueError):
    """An actionable but non-sensitive Outlook sandbox error."""


@dataclass(frozen=True)
class OutlookConfig:
    tenant_id: str
    client_id: str
    mailbox: str
    folder: str

    @classmethod
    def from_form(cls, values: dict[str, str]) -> 'OutlookConfig':
        tenant = str(values.get('tenant_id', '')).strip()
        client = str(values.get('client_id', '')).strip()
        mailbox = str(values.get('mailbox', '')).strip()
        folder = str(values.get('folder', '')).strip()
        for identifier in (tenant, client):
            try:
                if str(uuid.UUID(identifier)) != identifier.lower():
                    raise ValueError
            except (ValueError, AttributeError):
                raise SandboxError('Enter the Microsoft Entra Tenant ID and Application (Client) ID as UUIDs.') from None
        if (not re.fullmatch(r'[^\s@]{1,100}@[^\s@]{1,150}', mailbox)
                or any(ord(c) < 33 or ord(c) == 127 for c in mailbox)):
            raise SandboxError('Enter a valid work Outlook email address.')
        if not folder or len(folder) > 200 or any(ord(c) < 32 or ord(c) > 126 for c in folder):
            raise SandboxError('Enter the exact Outlook IMAP folder name (such as Printer).')
        return cls(tenant.lower(), client.lower(), mailbox, folder)

    def identity(self) -> tuple[str, str, str]:
        return self.tenant_id, self.client_id, self.mailbox.casefold()


class SandboxRepository:
    """No SQL queue, print storage, or Gmail settings are accessible here."""

    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / 'outlook_sandbox'
        self.settings_path = self.root / 'settings.json'
        self.tokens_path = self.root / 'tokens.json'
        self.staged_root = self.root / 'staged'

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

    def read_config(self) -> OutlookConfig | None:
        if not self.settings_path.exists():
            return None
        data = json.loads(self.settings_path.read_text(encoding='utf-8'))
        return OutlookConfig.from_form(data)

    def save_config(self, cfg: OutlookConfig) -> None:
        old = self.read_config()
        self._private_write(self.settings_path, json.dumps(cfg.__dict__, sort_keys=True).encode('utf-8'))
        if old is None or old.identity() != cfg.identity():
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
