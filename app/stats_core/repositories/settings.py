from __future__ import annotations

import json

from stats_core.storage import sqlite


class SettingsRepository:
    def get(self):
        with sqlite.connect() as con:
            row = con.execute(
                "SELECT value FROM settings WHERE key='config'"
            ).fetchone()

        base = json.loads(json.dumps(sqlite.DEFAULT_SETTINGS))
        if not row:
            return base

        incoming = json.loads(row["value"])
        base.update(incoming)
        base["visible_metrics"] = {
            **sqlite.DEFAULT_METRICS,
            **incoming.get("visible_metrics", {}),
        }
        base["sort_metric"] = {
            **sqlite.DEFAULT_SETTINGS["sort_metric"],
            **incoming.get("sort_metric", {}),
        }
        base["number_font_scale"] = {
            **sqlite.DEFAULT_SETTINGS["number_font_scale"],
            **incoming.get("number_font_scale", {}),
        }
        base["rank_direction"] = {
            "whole_office": "desc",
            "team_vs_team": "desc",
            "all_teams": "desc",
            "per_team": "desc",
        }
        return base

    def save(self, settings):
        with sqlite.connect() as con:
            con.execute(
                "INSERT INTO settings(key,value) VALUES('config',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(settings),),
            )
