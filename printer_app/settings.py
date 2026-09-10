"""Printer configuration workflow; HTTP and environment storage stay at the edges."""
from __future__ import annotations

from dataclasses import replace
import threading
from typing import Callable, Mapping

from .config import Config
from .settings_repository import SettingsRepository

# Only operational settings are editable. Paths, session secrets, binaries,
# listening addresses, and the working CUPS/Account Track setup are not web inputs.
TEXT_FIELDS = {
    'EMAIL_USER': 'email_user', 'EMAIL_MAILBOX': 'mailbox',
    'EMAIL_SUBJECT_CONTAINS': 'subject_contains', 'EMAIL_FROM_CONTAINS': 'from_contains',
    'PRINTER_TIMEZONE': 'timezone',
}
NUMBER_FIELDS = {
    'EMAIL_LOOKBACK_DAYS': ('lookback_days', 1, 3650),
    'EMAIL_POLL_SECONDS': ('poll_seconds', 10, 86400),
    'MAX_ATTACHMENT_MB': ('attachment_limit', 1, 100),
    'CONVERSION_TIMEOUT_SECONDS': ('conversion_timeout', 10, 600),
    'PRINTER_RETRY_SECONDS': ('retry_seconds', 10, 3600),
}
EDITABLE = set(TEXT_FIELDS) | set(NUMBER_FIELDS) | {'EMAIL_APP_PASSWORD', 'EMAIL_ENABLED'}


class SettingsError(ValueError):
    pass


class SettingsService:
    def __init__(self, repository: SettingsRepository, baseline: Config,
                 email_probe: Callable[[Config], tuple[bool, str]] | None = None):
        self.repository, self.baseline, self.email_probe = repository, baseline, email_probe
        self._probe_lock = threading.Lock()

    def _apply(self, current: Config, patch: Mapping[str, str]) -> Config:
        values = {}
        for key, value in patch.items():
            if key not in EDITABLE:
                raise SettingsError('This setting cannot be changed from the printer webpage.')
            if not isinstance(value, str) or len(value) > 512 or any(not c.isprintable() for c in value):
                raise SettingsError('Settings must contain single-line text of at most 512 characters.')
            if key in TEXT_FIELDS:
                values[TEXT_FIELDS[key]] = value.strip()
            elif key in NUMBER_FIELDS:
                attr, low, high = NUMBER_FIELDS[key]
                if not value.isascii() or not value.isdecimal() or not low <= int(value) <= high:
                    raise SettingsError(f'{key} must be a whole number between {low} and {high}.')
                values[attr] = int(value) * (1048576 if key == 'MAX_ATTACHMENT_MB' else 1)
            elif key == 'EMAIL_ENABLED':
                if value not in ('0', '1'):
                    raise SettingsError('Invalid email monitoring setting.')
                values['email_enabled'] = value == '1'
            else:
                values['email_password'] = value.replace(' ', '')
        cfg = replace(current, **values)
        if not cfg.mailbox:
            raise SettingsError('Enter a mailbox, usually INBOX.')
        try:
            cfg.validate()
        except (ValueError, KeyError):
            raise SettingsError('Invalid settings. Check the timezone and numeric ranges.') from None
        return cfg

    def read(self) -> tuple[Config, str]:
        stored, revision = self.repository.read()
        # File values override the environment captured by systemd at startup.
        return self._apply(self.baseline, {k: v for k, v in stored.items() if k in EDITABLE}), revision

    @staticmethod
    def public_values(cfg: Config) -> dict[str, str]:
        result = {key: str(getattr(cfg, attr)) for key, attr in TEXT_FIELDS.items()}
        result.update({key: str(getattr(cfg, spec[0]) // (1048576 if key == 'MAX_ATTACHMENT_MB' else 1))
                       for key, spec in NUMBER_FIELDS.items()})
        result['EMAIL_ENABLED'] = '1' if cfg.email_enabled else '0'
        return result

    def candidate(self, form: Mapping[str, str]) -> tuple[Config, dict[str, str], str]:
        if set(form) - EDITABLE - {'csrf', 'revision', 'clear_password'}:
            raise SettingsError('An unsupported setting was submitted.')
        current, revision = self.read()
        patch = {key: form[key] for key in EDITABLE if key in form}
        patch['EMAIL_ENABLED'] = form.get('EMAIL_ENABLED', '0')
        password = patch.get('EMAIL_APP_PASSWORD', '').replace(' ', '')
        if form.get('clear_password') == '1':
            if password:
                raise SettingsError('Either enter a new app password or remove the saved password, not both.')
            patch['EMAIL_APP_PASSWORD'] = ''
        elif not password:
            patch.pop('EMAIL_APP_PASSWORD', None)
            if patch.get('EMAIL_USER', current.email_user).strip() != current.email_user:
                raise SettingsError('Enter a new app password when changing the Gmail account.')
        cfg = self._apply(current, patch)
        return cfg, patch, revision

    def save(self, form: Mapping[str, str]) -> str:
        cfg, patch, _ = self.candidate(form)
        if cfg.email_enabled and (not cfg.email_user or not cfg.email_password):
            raise SettingsError('Enter the Gmail address and app password, or switch email monitoring off.')
        if cfg.email_user and ('@' not in cfg.email_user or any(c.isspace() for c in cfg.email_user)):
            raise SettingsError('Enter a valid Gmail account email address.')
        return self.repository.save(patch, form.get('revision', ''))

    def test_email(self, form: Mapping[str, str]) -> tuple[bool, str]:
        cfg, _, _ = self.candidate(form)
        if not cfg.email_user or not cfg.email_password:
            raise SettingsError('Enter a Gmail address and app password before testing.')
        if self.email_probe is None:
            raise SettingsError('Email connection testing is unavailable.')
        if not self._probe_lock.acquire(blocking=False):
            raise SettingsError('An email connection test is already running.')
        try:
            return self.email_probe(cfg)
        except Exception:
            # Network libraries may include credentials in an exception. Never echo it.
            return False, 'Could not connect to Gmail. Check the account, app password, mailbox, and network.'
        finally:
            self._probe_lock.release()
