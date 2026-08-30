"""Settings authentication service."""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import threading
import time
from dataclasses import dataclass

from stats_core.errors import ValidationError

PIN_ITERATIONS = 200_000
MAX_UNLOCK_FAILURES = 5
UNLOCK_LOCK_SECONDS = 60


@dataclass(frozen=True)
class UnlockResult:
    unlocked: bool
    retry_after: int = 0


class AuthService:
    def __init__(self, settings_repo, meta_repo):
        self.settings_repo = settings_repo
        self.meta_repo = meta_repo
        self._unlock_failures = {}
        self._unlock_lock = threading.Lock()

    def app_secret_key(self):
        key = self.meta_repo.get("flask_secret_key", "")
        if not key:
            key = secrets.token_hex(32)
            self.meta_repo.set("flask_secret_key", key)
        return key

    @staticmethod
    def hash_pin(pin, salt=None, iterations=PIN_ITERATIONS):
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(pin).encode(),
            bytes.fromhex(salt),
            iterations,
        ).hex()
        return f"pbkdf2${iterations}${salt}${digest}"

    @staticmethod
    def verify_pin(pin, stored):
        try:
            algo, iterations, salt, digest = str(stored).split("$")
            if algo != "pbkdf2":
                return False
            candidate = hashlib.pbkdf2_hmac(
                "sha256",
                str(pin).encode(),
                bytes.fromhex(salt),
                int(iterations),
            ).hex()
            return hmac.compare_digest(candidate, digest)
        except Exception:
            return False

    def pin_hash(self, settings=None):
        # Callers that already hold a settings dict pass it in rather than
        # re-reading, so a decision about that dict cannot disagree with it.
        data = self.settings_repo.get() if settings is None else settings
        return str(data.get("settings_pin_hash") or "")

    def pin_is_set(self, settings=None):
        return bool(self.pin_hash(settings).strip())

    def attempt_unlock(self, pin, client_key="default", now=None):
        """Verify a PIN and throttle repeated failures from one client."""
        stored = self.pin_hash()
        if not stored:
            self._clear_unlock_failures(client_key)
            return UnlockResult(True)

        now = time.monotonic() if now is None else float(now)
        client_key = str(client_key or "default")

        with self._unlock_lock:
            state = self._unlock_failures.get(client_key)
            if state and now < state["locked_until"]:
                return UnlockResult(
                    False,
                    max(1, math.ceil(state["locked_until"] - now)),
                )
            if state and state["locked_until"]:
                self._unlock_failures.pop(client_key, None)

        if self.verify_pin(str(pin or ""), stored):
            self._clear_unlock_failures(client_key)
            return UnlockResult(True)

        with self._unlock_lock:
            state = self._unlock_failures.setdefault(
                client_key,
                {"failures": 0, "locked_until": 0.0},
            )
            state["failures"] += 1
            if state["failures"] >= MAX_UNLOCK_FAILURES:
                state["failures"] = 0
                state["locked_until"] = now + UNLOCK_LOCK_SECONDS
                return UnlockResult(False, UNLOCK_LOCK_SECONDS)

        return UnlockResult(False)

    def _clear_unlock_failures(self, client_key):
        with self._unlock_lock:
            self._unlock_failures.pop(str(client_key or "default"), None)

    def change_pin(self, current_pin, new_pin, already_unlocked=False):
        settings = self.settings_repo.get()
        stored = str(settings.get("settings_pin_hash") or "")
        if (
            stored
            and not already_unlocked
            and not self.verify_pin(current_pin, stored)
        ):
            raise PermissionError("Current PIN is incorrect.")

        new_pin = str(new_pin or "").strip()
        if not new_pin:
            settings["settings_pin_hash"] = ""
            self.settings_repo.save(settings)
            self._clear_all_unlock_failures()
            return False
        if len(new_pin) < 4 or not new_pin.isdigit():
            raise ValidationError("PIN must be at least 4 digits.")

        settings["settings_pin_hash"] = self.hash_pin(new_pin)
        self.settings_repo.save(settings)
        self._clear_all_unlock_failures()
        return True

    def _clear_all_unlock_failures(self):
        with self._unlock_lock:
            self._unlock_failures.clear()
