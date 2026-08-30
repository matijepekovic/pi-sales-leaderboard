#!/usr/bin/env python3
"""Deterministic tests for canonical persistent application paths."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from stats_core import paths  # noqa: E402


class PersistentPathTests(unittest.TestCase):
    def test_explicit_override_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            custom = Path(temp) / "custom-data"
            with mock.patch.dict(os.environ, {"STATS_DATA_DIR": str(custom)}, clear=False):
                self.assertEqual(paths.persistent_data_dir(), custom)

    def test_windows_default_uses_local_app_data(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ)
            env.pop("STATS_DATA_DIR", None)
            env["LOCALAPPDATA"] = temp
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(paths.os, "name", "nt"):
                self.assertEqual(
                    paths.persistent_data_dir(),
                    Path(temp) / "Stats" / "data",
                )

    def test_legacy_migration_copies_missing_files_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "legacy"
            target = root / "current"
            (source / "nested").mkdir(parents=True)
            (source / "leaderboard.db").write_text("legacy-db", encoding="utf-8")
            (source / "nested" / "asset.txt").write_text("legacy-asset", encoding="utf-8")

            target.mkdir(parents=True)
            (target / "leaderboard.db").write_text("current-db", encoding="utf-8")

            self.assertTrue(paths.migrate_legacy_data(source, target))
            self.assertEqual((target / "leaderboard.db").read_text(encoding="utf-8"), "current-db")
            self.assertEqual((target / "nested" / "asset.txt").read_text(encoding="utf-8"), "legacy-asset")
            self.assertTrue((target / paths.MIGRATION_MARKER).is_file())

            (source / "later.txt").write_text("later", encoding="utf-8")
            self.assertFalse(paths.migrate_legacy_data(source, target))
            self.assertFalse((target / "later.txt").exists())


if __name__ == "__main__":
    unittest.main()
