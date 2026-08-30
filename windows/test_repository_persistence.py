#!/usr/bin/env python3
"""Behavior tests for repositories that directly own simple SQLite domains."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class RepositoryPersistenceTests(unittest.TestCase):
    def test_settings_meta_and_products_on_isolated_database(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ)
            env["STATS_DATA_DIR"] = temp
            code = f"""
import sys
sys.path.insert(0, {str(APP)!r})
from stats_core.repositories import Repositories

Repositories.initialize()
repos = Repositories(data_root={temp!r})

settings = repos.settings.get()
assert settings["active_mode"] == "whole_office", settings
assert settings["rank_direction"]["whole_office"] == "desc", settings
settings["title"] = "Repository Test"
settings["visible_metrics"] = {{"whole_office": ["rank", "rep_name"]}}
repos.settings.save(settings)
loaded = repos.settings.get()
assert loaded["title"] == "Repository Test", loaded
assert loaded["visible_metrics"]["whole_office"] == ["rank", "rep_name"], loaded
assert "per_team" in loaded["visible_metrics"], loaded
assert loaded["rank_direction"] == {{
    "whole_office": "desc",
    "team_vs_team": "desc",
    "all_teams": "desc",
    "per_team": "desc",
}}, loaded

assert repos.meta.get("missing", "fallback") == "fallback"
repos.meta.set("example", 7)
assert repos.meta.get("example") == "7"
assert repos.meta.bump("example") == 8
assert repos.meta.get("example") == "8"

repos.products.replace([
    {{"product": "Bath", "close_rate": 0.25}},
    {{"product": "Roof", "close_rate": 0.5}},
    {{"product": "", "close_rate": 0.9}},
])
products = repos.products.list()
assert [row["product"] for row in products] == ["Roof", "Bath"], products
assert products[0]["close_rate"] == 0.5, products
assert products[1]["close_rate"] == 0.25, products
"""
            subprocess.run([sys.executable, "-c", code], env=env, check=True)


if __name__ == "__main__":
    unittest.main()
