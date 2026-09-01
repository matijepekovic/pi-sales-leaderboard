#!/usr/bin/env python3
"""Behavior tests for repositories that directly own SQLite domains."""
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

    def test_settings_meta_and_products_on_isolated_database(self):
        with tempfile.TemporaryDirectory() as temp:
            self.run_isolated(temp, """
settings = repos.settings.get()
assert settings["active_mode"] == "whole_office", settings
assert settings["rank_direction"]["whole_office"] == "desc", settings
settings["title"] = "Repository Test"
settings["visible_metrics"] = {"whole_office": ["rank", "rep_name"]}
repos.settings.save(settings)
loaded = repos.settings.get()
assert loaded["title"] == "Repository Test", loaded
assert loaded["visible_metrics"]["whole_office"] == ["rank", "rep_name"], loaded
assert "per_team" in loaded["visible_metrics"], loaded
assert loaded["rank_direction"] == {
    "whole_office": "desc",
    "team_vs_team": "desc",
    "all_teams": "desc",
    "per_team": "desc",
}, loaded

assert repos.meta.get("missing", "fallback") == "fallback"
repos.meta.set("example", 7)
assert repos.meta.get("example") == "7"
assert repos.meta.bump("example") == 8
assert repos.meta.get("example") == "8"

repos.products.replace([
    {"product": "Bath", "close_rate": 0.25},
    {"product": "Roof", "close_rate": 0.5},
    {"product": "", "close_rate": 0.9},
])
products = repos.products.list()
assert [row["product"] for row in products] == ["Roof", "Bath"], products
assert products[0]["close_rate"] == 0.5, products
assert products[1]["close_rate"] == 0.25, products
""")

    def test_reps_and_organization_on_isolated_database(self):
        with tempfile.TemporaryDirectory() as temp:
            self.run_isolated(temp, """
repos.reps.replace([
    {"rep_key": "r1", "rep_name": "Alice", "team": "Red", "sold_leads": 3},
    {"rep_key": "r2", "rep_name": "Bob", "team": "Blue", "sold_leads": 2},
])
assert repos.meta.get("data_version") == "1"
assert [team["name"] for team in repos.organization.definitions()] == ["Blue", "Red"]

manual_id = repos.organization.create("Manual")
repos.organization.assign_reps([
    {"rep_key": "r1", "team_id": manual_id},
])
rows = {row["rep_key"]: row for row in repos.reps.list()}
assert rows["r1"]["source_team"] == "Red", rows["r1"]
assert rows["r1"]["team"] == "Manual", rows["r1"]
assert rows["r1"]["assigned_team_id"] == manual_id, rows["r1"]
assert rows["r1"]["local_team_override"] is True, rows["r1"]
assert rows["r2"]["team"] == "Blue", rows["r2"]
assert rows["r2"]["local_team_override"] is False, rows["r2"]

saved_id = repos.organization.save_builder(
    manual_id,
    "Manual Renamed",
    "Manager One",
    "Sales Manager",
    ["r1", "r2"],
)
assert saved_id == manual_id
manual = next(
    team for team in repos.organization.definitions()
    if team["team_id"] == manual_id
)
assert manual["name"] == "Manual Renamed", manual
assert manual["rep_count"] == 2, manual
assert manual["assigned_rep_count"] == 2, manual
assert manual["leader"]["lead_name"] == "Manager One", manual
assert repos.meta.get("organization_version") == "3"

destination_id = repos.organization.create("Destination")
result = repos.organization.delete(manual_id, [
    {"rep_key": "r1", "team_id": destination_id},
    {"rep_key": "r2", "team_id": destination_id},
])
assert result["member_count"] == 2, result
assert result["destination_team_ids"] == [destination_id], result
assert repos.meta.get("organization_version") == "5"
rows = {row["rep_key"]: row for row in repos.reps.list()}
assert rows["r1"]["team"] == "Destination", rows["r1"]
assert rows["r2"]["team"] == "Destination", rows["r2"]

changed = repos.reps.scrub_source_organization()
assert changed == 2, changed
assert repos.meta.get("data_version") == "2"
raw = {row["rep_key"]: row for row in repos.reps.raw_list()}
assert raw["r1"]["team"] == "Unassigned", raw["r1"]
assert raw["r2"]["team"] == "Unassigned", raw["r2"]
""")


if __name__ == "__main__":
    unittest.main()
