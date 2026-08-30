#!/usr/bin/env python3
"""Static ownership tests for persistent storage."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class StorageBoundaryTests(unittest.TestCase):
    def test_top_level_database_module_is_gone(self):
        self.assertFalse((APP / "database.py").exists())
        self.assertTrue((APP / "stats_core" / "storage" / "sqlite.py").is_file())

    def test_python_code_does_not_import_retired_database_module(self):
        violations = []
        for path in APP.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "import database" in text or "from database" in text:
                violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_repository_adapters_use_explicit_storage_module(self):
        repository_root = APP / "stats_core" / "repositories"
        for filename in (
            "__init__.py",
            "reps.py",
            "organization.py",
            "settings.py",
            "meta.py",
            "products.py",
        ):
            text = (repository_root / filename).read_text(encoding="utf-8")
            self.assertIn("from stats_core.storage import sqlite as database", text, filename)


if __name__ == "__main__":
    unittest.main()
