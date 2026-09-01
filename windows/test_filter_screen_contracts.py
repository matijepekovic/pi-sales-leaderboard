#!/usr/bin/env python3
"""Behavioral contract for reusable Filters matched by Screens."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


class FilterScreenContractTests(unittest.TestCase):
    def test_same_filter_can_match_different_report_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ)
            env["STATS_DATA_DIR"] = temp
            code = f"""
import sys
sys.path.insert(0, {str(APP)!r})
from stats_core.repositories import Repositories
from stats_core.services.filters import FilterService
from stats_core.services.screens import ScreenService

Repositories.initialize()
repos = Repositories(data_root={temp!r})
repos.filters.save({{"id":"filter-team","name":"Team"}})
repos.data_catalog.save({{
  "sources": [{{"id":"source-test","name":"Test","adapter":"fake","enabled":True,"connection":{{}}}}],
  "reports": [
    {{"id":"report-a","source_id":"source-test","name":"A","kind":"table","source_config":{{}},"runtime":{{}}}},
    {{"id":"report-b","source_id":"source-test","name":"B","kind":"table","source_config":{{}},"runtime":{{}}}},
  ],
}})
repos.report_data.replace("report-a", [{{"key":"team_name","label":"Team Name","type":"text"}},{{"key":"sales","label":"Sales","type":"number"}}], [{{"team_name":"Red","sales":10}},{{"team_name":"Blue","sales":8}}], {{}})
repos.report_data.replace("report-b", [{{"key":"division","label":"Division","type":"text"}},{{"key":"close","label":"Close","type":"percent"}}], [{{"division":"Red","close":20}},{{"division":"Green","close":15}}], {{}})

class Reports:
  def get(self, report_id): return repos.data_catalog.report(report_id)
  def fields(self, report_id): return repos.report_data.read(report_id).get("fields") or []
  def rows(self, report_id): return repos.report_data.read(report_id).get("rows") or []
class Builtin:
  def modes(self): return []
  def cycle_views(self): return []
  def render(self,*args,**kwargs): return {{"mode":"builtin"}}
class Org:
  def definitions_for_api(self): return []

service=ScreenService(repos, Reports(), FilterService(repos), Builtin(), Org())
screen=service.save({{
  "name":"Shared Team Filter",
  "reports":["report-a","report-b"],
  "filter_ids":["filter-team"],
  "display_filter_mappings":[
    {{"filter_id":"filter-team","report_id":"report-a","field":"team_name"}},
    {{"filter_id":"filter-team","report_id":"report-b","field":"division"}},
  ],
  "filter_values":{{"filter-team":"Red"}},
  "tables":[
    {{"report_id":"report-a","columns":["team_name","sales"]}},
    {{"report_id":"report-b","columns":["division","close"]}},
  ],
  "theme_mode":"inherited",
}})
payload=service.render(screen["id"])
assert [row["team_name"] for row in payload["sections"][0]["rows"]] == ["Red"]
assert [row["division"] for row in payload["sections"][1]["rows"]] == ["Red"]
assert payload["display_filters"][0]["name"] == "Team"
assert len(payload["display_filters"][0]["mappings"]) == 2
"""
            subprocess.run([sys.executable, "-c", code], env=env, check=True)


if __name__ == "__main__":
    unittest.main()
