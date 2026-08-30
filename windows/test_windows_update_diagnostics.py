#!/usr/bin/env python3
"""Tests for the read-only Windows updater diagnostics service."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from stats_core.windows import update as windows_update  # noqa: E402
from stats_core.windows import update_diagnostics as windows_update_diagnostics  # noqa: E402


class FakeServer:
    @staticmethod
    def software_version():
        return "1.0.20"


class WindowsUpdateDiagnosticsTests(unittest.TestCase):
    def test_successful_diagnostics_report_each_stage(self):
        with mock.patch.object(windows_update, "_read_url", return_value=b"metadata"), \
             mock.patch.object(
                 windows_update,
                 "verify_manifest",
                 return_value={"version": "1.0.20"},
             ), \
             mock.patch.object(
                 windows_update,
                 "latest_release_info",
                 return_value={
                     "latest": "1.0.20",
                     "available": False,
                     "installer_name": "Stats-Setup-1.0.20-windows-x64.exe",
                 },
             ):
            result = windows_update_diagnostics.collect_diagnostics(FakeServer)

        self.assertTrue(result["ok"])
        self.assertEqual(result["installed_version"], "1.0.20")
        self.assertEqual(
            [item["name"] for item in result["checks"]],
            [
                "installed_version",
                "https_trust",
                "manifest_download",
                "signature_download",
                "signature_verification",
                "latest_release_resolution",
            ],
        )
        self.assertTrue(all(item["ok"] for item in result["checks"]))

    def test_download_failure_is_reported_instead_of_raised(self):
        with mock.patch.object(
            windows_update,
            "_read_url",
            side_effect=OSError("test network failure"),
        ), mock.patch.object(
            windows_update,
            "latest_release_info",
            side_effect=OSError("test network failure"),
        ):
            result = windows_update_diagnostics.collect_diagnostics(FakeServer)

        self.assertFalse(result["ok"])
        failures = {item["name"]: item for item in result["checks"] if not item["ok"]}
        self.assertIn("manifest_download", failures)
        self.assertIn("signature_download", failures)
        self.assertIn("signature_verification", failures)
        self.assertIn("latest_release_resolution", failures)
        self.assertIn("test network failure", failures["manifest_download"]["error"])


if __name__ == "__main__":
    unittest.main()
