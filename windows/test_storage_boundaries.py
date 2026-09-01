#!/usr/bin/env python3
"""Static and behavioral ownership/source contract tests."""
from __future__ import annotations

import unittest
from pathlib import Path

from test_filter_repository import FilterRepositoryTests  # noqa: F401
from test_repository_persistence import RepositoryPersistenceTests  # noqa: F401
from test_tableau_source import TableauSourceContractTests  # noqa: F401

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
            "filters.py",
        ):
            text = (repository_root / filename).read_text(encoding="utf-8")
            self.assertIn("stats_core.storage", text, filename)

    def test_domains_own_their_sql(self):
        repository_root = APP / "stats_core" / "repositories"
        forbidden_delegates = {
            "settings.py": ("sqlite.get_settings", "sqlite.save_settings"),
            "meta.py": ("sqlite.get_meta", "sqlite.set_meta"),
            "products.py": ("sqlite.get_product_close", "sqlite.replace_product_close"),
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

    def test_sqlite_module_is_storage_kernel_not_domain_facade(self):
        text = (APP / "stats_core" / "storage" / "sqlite.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def connect()", text)
        self.assertIn("def init_db()", text)
        self.assertIn("SCHEMA =", text)
        for function_name in (
            "get_settings",
            "save_settings",
            "get_meta",
            "set_meta",
            "bump_meta",
            "bump_version",
            "replace_reps",
            "replace_product_close",
            "get_product_close",
            "create_team",
            "rename_team",
            "delete_team",
            "set_team_lead",
            "delete_team_lead",
            "assign_rep_to_team",
            "set_rep_team_assignments",
            "set_team_logo",
            "save_team_builder",
            "get_team_definitions",
            "apply_team_overlay",
            "list_reps",
            "list_teams",
        ):
            self.assertNotIn(f"def {function_name}(", text, function_name)


if __name__ == "__main__":
    unittest.main()
