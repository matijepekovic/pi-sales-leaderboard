#!/usr/bin/env python3
"""Deterministic tests for settings PIN authentication."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from flask import Flask

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

from stats_core.services.auth import (  # noqa: E402
    AuthService,
    MAX_UNLOCK_FAILURES,
    UNLOCK_LOCK_SECONDS,
)
from stats_core.web.auth import (  # noqa: E402
    UNLOCK_SESSION_KEY,
    blueprint as auth_blueprint,
)


class FakeSettingsRepository:
    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    def get(self):
        return dict(self.settings)

    def save(self, settings):
        self.settings = dict(settings)


class FakeMetaRepository:
    def __init__(self):
        self.values = {}

    def get(self, key, default=""):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class AuthServiceTests(unittest.TestCase):
    def service_with_pin(self, pin="1234"):
        stored = AuthService.hash_pin(
            pin,
            salt="00112233445566778899aabbccddeeff",
            iterations=200_000,
        )
        settings = FakeSettingsRepository({"settings_pin_hash": stored})
        return AuthService(settings, FakeMetaRepository())

    def test_existing_pbkdf2_pin_hash_still_unlocks(self):
        service = self.service_with_pin("2468")
        result = service.attempt_unlock("2468", client_key="client", now=10)
        self.assertTrue(result.unlocked)
        self.assertEqual(result.retry_after, 0)

    def test_repeated_wrong_pins_are_temporarily_locked(self):
        service = self.service_with_pin()
        for attempt in range(MAX_UNLOCK_FAILURES - 1):
            result = service.attempt_unlock(
                "0000",
                client_key="client",
                now=10 + attempt,
            )
            self.assertFalse(result.unlocked)
            self.assertEqual(result.retry_after, 0)

        locked = service.attempt_unlock(
            "0000",
            client_key="client",
            now=20,
        )
        self.assertFalse(locked.unlocked)
        self.assertEqual(locked.retry_after, UNLOCK_LOCK_SECONDS)

        still_locked = service.attempt_unlock(
            "1234",
            client_key="client",
            now=21,
        )
        self.assertFalse(still_locked.unlocked)
        self.assertGreater(still_locked.retry_after, 0)

        unlocked = service.attempt_unlock(
            "1234",
            client_key="client",
            now=20 + UNLOCK_LOCK_SECONDS,
        )
        self.assertTrue(unlocked.unlocked)

    def test_clients_are_throttled_independently(self):
        service = self.service_with_pin()
        for attempt in range(MAX_UNLOCK_FAILURES):
            service.attempt_unlock(
                "0000",
                client_key="noisy-client",
                now=10 + attempt,
            )

        other = service.attempt_unlock(
            "1234",
            client_key="other-client",
            now=20,
        )
        self.assertTrue(other.unlocked)

    def test_no_pin_needs_no_unlock(self):
        service = AuthService(
            FakeSettingsRepository({"settings_pin_hash": ""}),
            FakeMetaRepository(),
        )
        self.assertTrue(service.attempt_unlock("", now=10).unlocked)

    def test_settings_unlock_expires_with_server_process(self):
        service = self.service_with_pin()
        marker = service.session_marker()
        self.assertTrue(service.session_is_unlocked(marker))

        restarted = AuthService(service.settings_repo, service.meta_repo)
        self.assertFalse(restarted.session_is_unlocked(marker))
        self.assertTrue(restarted.session_is_unlocked(restarted.session_marker()))

    def test_unlock_uses_non_permanent_browser_session(self):
        service = self.service_with_pin("2468")
        app = Flask("stats-auth-test")
        app.secret_key = "test-secret"
        app.register_blueprint(auth_blueprint(service))
        client = app.test_client()

        response = client.post("/api/auth/unlock", json={"pin": "2468"})
        self.assertEqual(response.status_code, 200)

        with client.session_transaction() as browser_session:
            self.assertFalse(browser_session.permanent)
            marker = browser_session.get(UNLOCK_SESSION_KEY)
            self.assertTrue(service.session_is_unlocked(marker))
            self.assertNotIn("settings_unlocked", browser_session)


if __name__ == "__main__":
    unittest.main()
