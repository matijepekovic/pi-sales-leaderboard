#!/usr/bin/env python3
"""Static and behavioral ownership tests for persistent storage."""
from __future__ import annotations

import unittest
from pathlib import Path

from test_repository_persistence import RepositoryPersistenceTests  # noqa: F401

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

    def test_domains_own_their_sql(self):
        repository_root = APP / "stats_core" / "repositories"
        forbidden_delegates = {
            "settings.py": ("database.get_settings", "database.save_settings"),
            "meta.py": ("database.get_meta", "database.set_meta"),
            "products.py": ("database.get_product_close", "database.replace_product_close"),
            "reps.py": (
                "database.list_reps",
                "database.replace_reps",
                "database.apply_team_overlay",
                "database.bump_version",
            ),
            "organization.py": (
                "database.list_teams",
                "database.get_team_definitions",
                "database.save_team_builder",
                "database.create_team",
                "database.rename_team",
                "database.delete_team",
                "database.set_team_lead",
                "database.delete_team_lead",
                "database.set_rep_team_assignments",
                "database.set_team_logo",
                "database.apply_team_overlay",
            ),
        }
        for filename, tokens in forbidden_delegates.items():
            text = (repository_root / filename).read_text(encoding="utf-8")
            self.assertIn(".execute(", text, filename)
            for token in tokens:
                self.assertNotIn(token, text, filename)

    def test_rep_organization_dependencies_are_explicit(self):
        wiring = (APP / "stats_core" / "repositories" / "__init__.py").read_text(
            encoding="utf-8"
        )
        reps = (APP / "stats_core" / "repositories" / "reps.py").read_text(
            encoding="utf-8"
        )
        organization = (
            APP / "stats_core" / "repositories" / "organization.py"
        ).read_text(encoding="utf-8")
        self.assertIn("OrganizationRepository(self.meta)", wiring)
        self.assertIn("RepRepository(self.meta, self.organization)", wiring)
        self.assertIn("self.organization.apply_overlay", reps)
        self.assertIn("self.meta.bump(\"data_version\")", reps)
        self.assertIn("self.meta.bump(\"organization_version\")", organization)


if __name__ == "__main__":
    unittest.main()
