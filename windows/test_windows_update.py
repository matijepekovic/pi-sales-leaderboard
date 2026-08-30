#!/usr/bin/env python3
"""Deterministic tests for the signed Windows update client."""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from stats_core.windows import update  # noqa: E402


class WindowsUpdateTests(unittest.TestCase):
    def test_semver_comparison_parts(self):
        self.assertEqual(update._version_tuple("1.0.2"), (1, 0, 2))
        self.assertGreater(
            update._version_tuple("1.1.0"),
            update._version_tuple("1.0.99"),
        )
        with self.assertRaises(ValueError):
            update._version_tuple("v1.0.2")

    def test_only_expected_release_asset_urls_are_trusted(self):
        good = (
            "https://github.com/matijepekovic/pi-sales-leaderboard-updates/"
            "releases/download/v1.0.2/Stats-Setup-1.0.2-windows-x64.exe"
        )
        self.assertTrue(update._trusted_release_asset_url(good))
        self.assertFalse(
            update._trusted_release_asset_url("http://github.com/example.exe")
        )
        self.assertFalse(
            update._trusted_release_asset_url("https://example.com/example.exe")
        )

    def test_ed25519_manifest_verification(self):
        private = Ed25519PrivateKey.generate()
        public_raw = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        public_b64 = base64.b64encode(public_raw).decode("ascii")
        payload = b"installer-test"
        manifest = {
            "schema": 1,
            "version": "1.0.2",
            "assets": [{
                "name": "Stats-Setup-1.0.2-windows-x64.exe",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }],
        }
        manifest_bytes = (
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        signature_bytes = base64.b64encode(private.sign(manifest_bytes)) + b"\n"

        verified = update.verify_manifest(
            manifest_bytes,
            signature_bytes,
            public_b64,
        )
        self.assertEqual(verified["version"], "1.0.2")

        with self.assertRaises(ValueError):
            update.verify_manifest(
                manifest_bytes + b" ",
                signature_bytes,
                public_b64,
            )


if __name__ == "__main__":
    unittest.main()
