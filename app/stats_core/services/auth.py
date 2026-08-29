"""Settings authentication service."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from stats_core.errors import ValidationError

PIN_ITERATIONS = 200_000


class AuthService:
    def __init__(self, settings_repo, meta_repo):
        self.settings_repo = settings_repo
        self.meta_repo = meta_repo

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
            "sha256", str(pin).encode(), bytes.fromhex(salt), iterations
        ).hex()
        return f"pbkdf2${iterations}${salt}${digest}"

    @staticmethod
    def verify_pin(pin, stored):
        try:
            algo, iterations, salt, digest = str(stored).split("$")
            if algo != "pbkdf2":
                return False
            candidate = hashlib.pbkdf2_hmac(
                "sha256", str(pin).encode(), bytes.fromhex(salt), int(iterations)
            ).hex()
            return hmac.compare_digest(candidate, digest)
        except Exception:
            return False

    def pin_hash(self):
        return str(self.settings_repo.get().get("settings_pin_hash") or "")

    def pin_is_set(self):
        return bool(self.pin_hash().strip())

    def change_pin(self, current_pin, new_pin, already_unlocked=False):
        settings = self.settings_repo.get()
        stored = str(settings.get("settings_pin_hash") or "")
        if stored and not already_unlocked and not self.verify_pin(current_pin, stored):
            raise PermissionError("Current PIN is incorrect.")
        new_pin = str(new_pin or "").strip()
        if not new_pin:
            settings["settings_pin_hash"] = ""
            self.settings_repo.save(settings)
            return False
        if len(new_pin) < 4 or not new_pin.isdigit():
            raise ValidationError("PIN must be at least 4 digits.")
        settings["settings_pin_hash"] = self.hash_pin(new_pin)
        self.settings_repo.save(settings)
        return True
