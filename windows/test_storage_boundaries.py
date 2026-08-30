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

    def test_repositories_use_explicit_storage_boundary(self):
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
            self.assertIn("stats_core.storage", text, filename)

    def test_simple_domains_own_their_sql(self):
        repository_root = APP / "stats_core" / "repositories"
        forbidden_delegates = {
            "settings.py": ("get_settings(", "save_settings("),
            "meta.py": ("get_meta(", "set_meta("),
            "products.py": ("get_product_close(", "replace_product_close("),
        }
        for filename, tokens in forbidden_delegates.items():
            text = (repository_root / filename).read_text(encoding="utf-8")
            self.assertIn(".execute(", text, filename)
            for token in tokens:
                self.assertNotIn(token, text, filename)


if __name__ == "__main__":
    unittest.main()
