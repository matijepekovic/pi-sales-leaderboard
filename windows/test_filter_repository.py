#!/usr/bin/env python3
"""Persistence contract for reusable display Filters."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class FilterRepositoryTests(unittest.TestCase):
    def test_filters_persist_without_report_field_knowledge(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ)
            env["STATS_DATA_DIR"] = temp
            code = f"""
import sys
sys.path.insert(0, {str(APP)!r})
from stats_core.repositories import Repositories
Repositories.initialize()
repos = Repositories(data_root={temp!r})
repos.filters.save({{"id":"filter-team","name":"Team"}})
repos.filters.save({{"id":"filter-office","name":"Office"}})
assert repos.filters.get("filter-team") == {{"id":"filter-team","name":"Team"}}
assert [row["name"] for row in repos.filters.list()] == ["Team", "Office"]
assert "field" not in repos.filters.get("filter-team")
assert repos.filters.delete("filter-team") is True
assert repos.filters.get("filter-team") is None
"""
            subprocess.run([sys.executable, "-c", code], env=env, check=True)


if __name__ == "__main__":
    unittest.main()
