"""Named temporary Gallery access is owner-scoped, six-hour and revocable."""
import sqlite3
import time
from pathlib import Path

import pytest

from printer_app.gallery.access_repository import GalleryAccessRepository
from printer_app.gallery.access_service import GalleryAccessService


def service(tmp_path):
    return GalleryAccessService(GalleryAccessRepository(tmp_path / 'gallery-access.db'))


def test_named_guest_session_is_six_hours_and_owner_can_revoke_open_access(tmp_path):
    access = service(tmp_path)
    before = time.time()
    shared = access.create_guest_share('owner-a', 'Installer John')
    assert shared['name'] == 'Installer John'
    assert 6 * 3600 - 5 <= shared['expires'] - before <= 6 * 3600 + 5

    mine = access.active_shares('owner-a')
    assert [(row['id'], row['name'], row['opened']) for row in mine] == [
        (shared['id'], 'Installer John', False)
    ]
    assert access.active_shares('owner-b') == []

    grant = access.redeem(shared['token'])
    assert grant and grant.identity.role == 'guest'
    assert grant.identity.expires == shared['expires']
    assert access.resolve(grant.token) is not None
    assert access.active_shares('owner-a')[0]['opened'] is True

    with pytest.raises(LookupError):
        access.revoke_share('owner-b', shared['id'])

    access.revoke_share('owner-a', shared['id'])
    assert access.active_shares('owner-a') == []
    assert access.resolve(grant.token) is None


def test_share_name_is_required_and_bounded(tmp_path):
    access = service(tmp_path)
    with pytest.raises(ValueError):
        access.create_guest_share('owner-a', '   ')
    with pytest.raises(ValueError):
        access.create_guest_share('owner-a', 'x' * 81)
    with pytest.raises(ValueError):
        access.create_guest_share('', 'Someone')


def test_existing_access_database_migrates_and_legacy_guest_access_is_invalidated(tmp_path):
    path = tmp_path / 'gallery-access.db'
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE access_invites (
          token_hash TEXT PRIMARY KEY, role TEXT NOT NULL, created REAL NOT NULL,
          expires REAL NOT NULL, one_time INTEGER NOT NULL, used REAL);
        CREATE TABLE access_credentials (
          token_hash TEXT PRIMARY KEY, subject TEXT NOT NULL, role TEXT NOT NULL,
          created REAL NOT NULL, expires REAL, revoked REAL, last_seen REAL NOT NULL);
        """)
        now = time.time()
        conn.execute(
            "INSERT INTO access_invites VALUES(?,?,?,?,?,NULL)",
            ('legacy-invite', 'guest', now, now + 86400, 1),
        )
        conn.execute(
            "INSERT INTO access_credentials VALUES(?,?,?,?,?,NULL,?)",
            ('legacy-cookie', 'legacy-subject', 'guest', now, now + 86400, now),
        )

    repository = GalleryAccessRepository(path)
    repository.initialize()

    with repository.connect() as conn:
        invite_columns = {row['name'] for row in conn.execute('PRAGMA table_info(access_invites)')}
        credential_columns = {row['name'] for row in conn.execute('PRAGMA table_info(access_credentials)')}
        assert {'share_id', 'issuer_subject', 'label', 'revoked'} <= invite_columns
        assert 'invite_hash' in credential_columns
        assert conn.execute("SELECT 1 FROM access_invites WHERE token_hash='legacy-invite'").fetchone() is None
        legacy = conn.execute(
            "SELECT revoked FROM access_credentials WHERE token_hash='legacy-cookie'"
        ).fetchone()
        assert legacy['revoked'] is not None


def test_gallery_access_owners_stay_separate():
    root = Path(__file__).resolve().parents[1]
    service_source = (root / 'gallery/access_service.py').read_text()
    repository_source = (root / 'gallery/access_repository.py').read_text()
    web_source = (root / 'gallery/web.py').read_text()
    assert 'sqlite3' not in service_source and 'flask' not in service_source
    assert 'flask' not in repository_source and 'reportlab' not in repository_source
    assert 'reportlab' in web_source
