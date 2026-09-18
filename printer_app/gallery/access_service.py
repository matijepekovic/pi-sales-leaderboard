"""Gallery authorization and temporary-sharing workflow.

HTTP owns cookies/QR rendering. This service owns roles, capabilities, named shares,
expiry, redemption and revocation through the access repository.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import secrets
import time


CAPABILITIES = {
    'full': frozenset({'browse', 'notes', 'share', 'edit_identity'}),
    'guest': frozenset({'browse', 'notes'}),
}
GUEST_SESSION_SECONDS = 6 * 3600
MAX_SHARE_NAME = 80


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

    def offline_owner(self):
        self.initialize()
        return self.repository.offline_owner()

    def claim_offline_owner(self, subject):
        self.initialize()
        return self.repository.claim_offline_owner(subject) == subject

    def capabilities(self, identity):
        capabilities = set(CAPABILITIES[identity.role])
        if identity.role == 'full' and self.repository.offline_owner() == identity.subject:
            capabilities.add('offline')
        return frozenset(capabilities)

    def allows(self, identity, capability):
        return capability in self.capabilities(identity)

    def issue_full_invite(self, ttl=600):
        return self._issue_invite('full', ttl, one_time=False)

    def _issue_invite(self, role, ttl, one_time):
        self.initialize()
        if role not in CAPABILITIES:
            raise ValueError('Invalid gallery access role')
        ttl = max(60, min(int(ttl), 7 * 86400))
        token = secrets.token_urlsafe(32)
        self.repository.create_invite(self._hash(token), role, time.time() + ttl, one_time)
        return token

    @staticmethod
    def checked_share_name(value):
        name = ' '.join(str(value or '').split())
        if not name or len(name) > MAX_SHARE_NAME or not all(c.isprintable() for c in name):
            raise ValueError(f'Name this access session using up to {MAX_SHARE_NAME} characters.')
        return name

    def create_guest_share(self, issuer_subject, name):
        self.initialize()
        if not issuer_subject:
            raise ValueError('Full Gallery access is required to share.')
        label = self.checked_share_name(name)
        token = secrets.token_urlsafe(32)
        share_id = secrets.token_hex(16)
        expires = time.time() + GUEST_SESSION_SECONDS
        self.repository.create_invite(
            self._hash(token),
            'guest',
            expires,
            True,
            share_id=share_id,
            issuer_subject=issuer_subject,
            label=label,
        )
        return dict(id=share_id, name=label, expires=expires, token=token)

    def active_shares(self, issuer_subject):
        self.initialize()
        return [
            dict(id=row['share_id'], name=row['label'], created=row['created'],
                 expires=row['expires'], opened=row['used'] is not None)
            for row in self.repository.active_shares(issuer_subject)
        ]

    def revoke_share(self, issuer_subject, share_id):
        self.initialize()
        if not isinstance(share_id, str) or len(share_id) != 32:
            raise LookupError('This access session is unavailable.')
        int(share_id, 16)
        self.repository.revoke_share(issuer_subject, share_id)

    def redeem(self, invite_token):
        self.initialize()
        if not invite_token or len(invite_token) > 200:
            return None
        invite_hash = self._hash(invite_token)
        row = self.repository.redeem_invite(invite_hash)
        if not row:
            return None
        role = row['role']
        if role not in CAPABILITIES:
            return None
        expires = float(row['expires']) if role == 'guest' else None
        credential = secrets.token_urlsafe(32)
        subject = secrets.token_hex(16)
        self.repository.create_credential(
            self._hash(credential),
            subject,
            role,
            expires=expires,
            invite_hash=invite_hash if role == 'guest' else None,
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
