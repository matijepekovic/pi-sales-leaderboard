"""Printer-only retention settings and normalized remote deletion identity."""
from dataclasses import dataclass, replace
import hashlib

FIELDS = {'CLEANUP_ENABLED', 'CLEANUP_DAYS', 'CLEANUP_EMAILS'}


def mailbox_scope(account: str, mailbox: str) -> str:
    return hashlib.sha256((account.strip().casefold() + '\0' + mailbox).encode()).hexdigest()


@dataclass(frozen=True)
class ExpiredEmail:
    key: str  # Opaque stable identity owned by the email adapter, not an IMAP UID.
    received_at: float
    local_identity: str


@dataclass(frozen=True)
class RetentionPolicy:
    enabled: bool = False
    days: int = 7
    delete_emails: bool = False
    email_scope: str = ''

    def __post_init__(self):
        if type(self.days) is not int or not 1 <= self.days <= 365:
            raise ValueError('Keep for must be a whole number between 1 and 365 days.')
        if type(self.enabled) is not bool or type(self.delete_emails) is not bool:
            raise ValueError('Invalid automatic cleanup switch.')

    def apply(self, values):
        patch = {}
        for key, value in values.items():
            if key == 'CLEANUP_DAYS':
                if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
                    raise ValueError('Invalid cleanup retention days.')
                patch['days'] = int(value)
            elif key in ('CLEANUP_ENABLED', 'CLEANUP_EMAILS'):
                if value not in ('0', '1'):
                    raise ValueError('Invalid automatic cleanup switch.')
                patch['enabled' if key == 'CLEANUP_ENABLED' else 'delete_emails'] = value == '1'
            else:
                raise ValueError('Unsupported cleanup setting.')
        return replace(self, **patch)

    def mail_allowed(self, account, mailbox):
        return (self.enabled and self.delete_emails and bool(account)
                and self.email_scope == mailbox_scope(account, mailbox))

    def environment(self):
        return dict(CLEANUP_ENABLED=str(int(self.enabled)), CLEANUP_DAYS=str(self.days),
                    CLEANUP_EMAILS=str(int(self.delete_emails)))
