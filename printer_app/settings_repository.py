"""Atomic private environment storage. No HTTP, worker, or Stats dependencies."""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping

from .config import parse_env


class SettingsStorageError(RuntimeError):
    pass


class SettingsConflict(SettingsStorageError):
    pass


class SettingsRepository:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser()

    def _read(self) -> str:
        if not self.path.exists():
            return ''
        with self.path.open('r', encoding='utf-8') as stream:
            text = stream.read(65537)
        if len(text) > 65536:
            raise SettingsStorageError('Settings file is too large.')
        return text

    @staticmethod
    def revision(text: str) -> str:
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def read(self) -> tuple[dict[str, str], str]:
        try:
            text = self._read()
            return parse_env(text), self.revision(text)
        except (OSError, ValueError) as exc:
            raise SettingsStorageError('Could not read printer settings.') from exc

    def save(self, changes: Mapping[str, str], expected: str) -> str:
        """Preserve unrelated keys, secrets and comments; reject stale form writes."""
        for key, value in changes.items():
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or not isinstance(value, str):
                raise SettingsStorageError('Invalid settings key or value.')
            if len(value) > 1024 or any(not c.isprintable() for c in value):
                raise SettingsStorageError('Settings must be single-line text.')
        try:
            # Setup owns creation, location and permissions of this directory.
            if not self.path.is_file():
                raise SettingsStorageError('Printer setup is incomplete. Use the leaderboard Update button.')
            fd = os.open(self.path.with_name('settings.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                original = self._read()
                if self.revision(original) != expected:
                    raise SettingsConflict('Settings changed in another window. Refresh before saving again.')
                lines = [line for line in original.splitlines()
                         if line.strip().partition('=')[0] not in changes]
                for key, value in changes.items():
                    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
                    lines.append(f'{key}="{escaped}"')
                text = '\n'.join(lines) + '\n'
                # Write+rename in the same directory: readers see an entire old/new file.
                fd, name = tempfile.mkstemp(prefix='.settings-', dir=self.path.parent)
                temporary = Path(name)
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                        os.fchmod(stream.fileno(), 0o600)
                        stream.write(text)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, self.path)
                    directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    temporary.unlink(missing_ok=True)
                return self.revision(text)
        except OSError as exc:
            raise SettingsStorageError('Could not save printer settings. Existing settings were not intentionally cleared.') from exc
