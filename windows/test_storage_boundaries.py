#!/usr/bin/env python3
"""Storage ownership tests for current Stats repositories."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class StorageBoundaryTests(unittest.TestCase):
    def run_isolated(self, temp, code):
        env = dict(os.environ)
        env["STATS_DATA_DIR"] = temp
        source = f"""
import sys
sys.path.insert(0, {str(APP)!r})
from stats_core.repositories import Repositories
Repositories.initialize()
repos = Repositories(data_root={temp!r})
{code}
"""
        subprocess.run([sys.executable, "-c", source], env=env, check=True)

    def test_sqlite_is_storage_kernel_not_domain_facade(self):
        path = APP / "stats_core" / "storage" / "sqlite.py"
        text = path.read_text(encoding="utf-8")
        self.assertIn("def connect()", text)
        self.assertIn("def init_db()", text)
        self.assertIn("SCHEMA =", text)
        for name in (
            "save_filter", "save_screen", "save_source", "save_report",
            "save_display", "save_theme", "replace_report_data",
        ):
            self.assertNotIn(f"def {name}(", text)

    def test_current_sql_repositories_use_storage_boundary(self):
        repository_root = APP / "stats_core" / "repositories"
        for filename in (
            "data_catalog.py", "display.py", "filters.py", "meta.py",
            "screens.py", "settings.py", "source_credentials.py",
        ):
            text = (repository_root / filename).read_text(encoding="utf-8")
            self.assertIn("stats_core.storage", text, filename)
            self.assertIn("sqlite.connect()", text, filename)

    def test_runtime_repository_composition_has_no_retired_sales_domains(self):
        text = (APP / "stats_core" / "repositories" / "__init__.py").read_text(encoding="utf-8")
        for current in (
            "DataCatalogRepository", "SourceCredentialRepository", "ReportDataRepository",
            "FilterRepository", "ScreenRepository", "DisplayRepository", "ThemeRepository",
            "AppliedAssetRepository", "AssetLibraryRepository",
        ):
            self.assertIn(current, text)
        for retired in ("OrganizationRepository", "RepRepository", "ProductRepository"):
            self.assertNotIn(retired, text)

    def test_current_repositories_persist_independently(self):
        with tempfile.TemporaryDirectory() as temp:
            self.run_isolated(temp, """
repos.data_catalog.save({
    "sources": [{"id":"source-a","name":"A","adapter":"tableau","enabled":True,"connection":{}}],
    "reports": [{"id":"report-a","source_id":"source-a","name":"Report A","source_config":{},"runtime":{}}],
})
assert repos.data_catalog.source("source-a")["name"] == "A"
assert repos.data_catalog.report("report-a")["name"] == "Report A"

repos.source_credentials.set("source-a", "secret")
assert repos.source_credentials.get("source-a") == "secret"

repos.report_data.replace(
    "report-a",
    [{"key":"Office","label":"Office","type":"text"}],
    [{"Office":"Olympia"}],
    {"status":"1 row"},
)
assert repos.report_data.read("report-a")["rows"] == [{"Office":"Olympia"}]

repos.filters.save({
    "id":"filter-a",
    "name":"Olympia",
    "rules":[{"report_id":"report-a","field":"Office","operator":"equals","value":"Olympia"}],
})
assert repos.filters.get("filter-a")["name"] == "Olympia"

repos.screens.save({
    "id":"screen-a",
    "name":"Olympia Screen",
    "reports":["report-a"],
    "filter_ids":["filter-a"],
    "tables":[],
    "theme_mode":"inherited",
})
assert repos.screens.get("screen-a")["filter_ids"] == ["filter-a"]

repos.display.save({"active_screen_id":"screen-a","rotation_enabled":False,"rotation_screen_ids":[],"rotation_seconds":15})
assert repos.display.get()["active_screen_id"] == "screen-a"

repos.themes.save("screen-a", {"base":"starter","colors":{"primary":"#ffffff"}})
assert repos.themes.get("screen-a")["base"] == "starter"
""")

    def test_repositories_do_not_import_source_adapters(self):
        violations = []
        for path in (APP / "stats_core" / "repositories").rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            if "sources.tableau" in text or "from sources" in text:
                violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
