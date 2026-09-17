"""Printer-admin authentication workflow.

The printer admin account is intentionally separate from Gallery full/guest access.
"""
from dataclasses import dataclass
import secrets

from werkzeug.security import check_password_hash, generate_password_hash


ADMIN_USERNAME = 'admin'
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256


@dataclass(frozen=True)
class AdminState:
    revision: int
    must_change: bool


class AdminAuthService:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _hash(password):
        return generate_password_hash(password, method='scrypt')

    def ensure_temporary_password(self):
        """Create the first admin credential once and return its cleartext password."""
        if self.repository.state():
            return None
        password = secrets.token_urlsafe(15)
        if self.repository.create(self._hash(password), must_change=True):
            return password
        return None

    def authenticate(self, username, password, address):
        blocked = self.repository.blocked_until(address)
        if blocked is not None:
            return None, 'Too many failed attempts. Try again in about 15 minutes.'
        state = self.repository.state()
        valid = (
            state
            and username == ADMIN_USERNAME
            and isinstance(password, str)
            and len(password) <= MAX_PASSWORD_LENGTH
            and check_password_hash(state['password_hash'], password)
        )
        if not valid:
            attempts, _ = self.repository.record_failure(address)
            remaining = max(0, 5 - attempts)
            message = 'Invalid username or password.'
            if remaining:
                message += f' {remaining} attempt{"s" if remaining != 1 else ""} before temporary lockout.'
            return None, message
        self.repository.clear_failures(address)
        return AdminState(int(state['revision']), bool(state['must_change'])), ''

    def session_state(self, revision):
        if not isinstance(revision, int):
            return None
        state = self.repository.state()
        if not state or int(state['revision']) != revision:
            return None
        return AdminState(revision, bool(state['must_change']))

    def change_password(self, current_password, new_password, confirmation):
        state = self.repository.state()
        if not state or not check_password_hash(state['password_hash'], str(current_password)):
            raise ValueError('Current password is incorrect.')
        if new_password != confirmation:
            raise ValueError('New passwords do not match.')
        if not isinstance(new_password, str) or not (MIN_PASSWORD_LENGTH <= len(new_password) <= MAX_PASSWORD_LENGTH):
            raise ValueError(f'Use a password between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters.')
        if check_password_hash(state['password_hash'], new_password):
            raise ValueError('Choose a new password different from the current password.')
        return self.repository.replace_password(self._hash(new_password))
