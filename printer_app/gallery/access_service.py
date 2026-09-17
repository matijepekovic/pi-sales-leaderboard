"""Gallery authorization and invitation workflow.

HTTP owns cookies/redirects. This service owns roles, capabilities, token issuance,
expiry and redemption through the access repository.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
import time


CAPABILITIES = {
    'full': frozenset({'browse', 'notes', 'offline', 'share'}),
    'guest': frozenset({'browse', 'notes'}),
}
GUEST_SESSION_SECONDS = 86400


@dataclass(frozen=True)
class GalleryIdentity:
    subject: str
    role: str
    expires: float | None

    @property
    def capabilities(self):
        return CAPABILITIES[self.role]

    def allows(self, capability):
        return capability in self.capabilities


@dataclass(frozen=True)
class GalleryGrant:
    token: str
    identity: GalleryIdentity


class GalleryAccessService:
    def __init__(self, repository):
        self.repository = repository
        self.initialized = False

    def initialize(self):
        if not self.initialized:
            self.repository.initialize()
            self.initialized = True

    @staticmethod
    def _hash(token):
        return hashlib.sha256(token.encode('ascii')).hexdigest()

    def issue_full_invite(self, ttl=600):
        return self._issue_invite('full', ttl, one_time=False)

    def issue_guest_invite(self, ttl=86400):
        return self._issue_invite('guest', ttl, one_time=True)

    def _issue_invite(self, role, ttl, one_time):
        self.initialize()
        if role not in CAPABILITIES:
            raise ValueError('Invalid gallery access role')
        ttl = max(60, min(int(ttl), 7 * 86400))
        token = secrets.token_urlsafe(32)
        self.repository.create_invite(self._hash(token), role, time.time() + ttl, one_time)
        return token

    def redeem(self, invite_token):
        self.initialize()
        if not invite_token or len(invite_token) > 200:
            return None
        row = self.repository.redeem_invite(self._hash(invite_token))
        if not row:
            return None
        role = row['role']
        if role not in CAPABILITIES:
            return None
        # The link may wait before the recipient opens it. Guest access lasts a
        # full 24 hours from redemption, not from the sender creating the link.
        expires = time.time() + GUEST_SESSION_SECONDS if role == 'guest' else None
        credential = secrets.token_urlsafe(32)
        subject = secrets.token_hex(16)
        self.repository.create_credential(
            self._hash(credential), subject, role, expires=expires
        )
        return GalleryGrant(credential, GalleryIdentity(subject, role, expires))

    def resolve(self, credential_token):
        self.initialize()
        if not credential_token or len(credential_token) > 200:
            return None
        row = self.repository.credential(self._hash(credential_token))
        if not row or row['role'] not in CAPABILITIES:
            return None
        return GalleryIdentity(row['subject'], row['role'], row['expires'])
