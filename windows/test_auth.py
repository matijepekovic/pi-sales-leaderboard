#!/usr/bin/env python3
"""Deterministic tests for settings PIN authentication."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

from stats_core.services.auth import (  # noqa: E402
    AuthService,
    MAX_UNLOCK_FAILURES,
    UNLOCK_LOCK_SECONDS,
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


if __name__ == "__main__":
    unittest.main()
