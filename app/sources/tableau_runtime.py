"""Tableau runtime settings normalization owned by the Tableau adapter layer."""
from __future__ import annotations

from copy import deepcopy

from sources.tableau_configured import ConfiguredTableauSource, config_of


class TableauRuntime:
    def normalized_settings(self, settings):
        settings = deepcopy(settings or {})
        saved = settings.get("source") if isinstance(settings.get("source"), dict) else {}
        config = dict(config_of(settings))
        for source_key, top_key in (
            ("server", "tableau_server"),
            ("site", "tableau_site"),
            ("pat_name", "tableau_pat_name"),
        ):
            explicit = str(saved.get(source_key) or "").strip()
            top = str(settings.get(top_key) or "").strip()
            config[source_key] = explicit or top
        config["date_start_field"] = str(config.get("date_start_field") or "Start")
        config["date_end_field"] = str(config.get("date_end_field") or "End")
        settings["source"] = config
        return settings

    def source(self, settings):
        runtime = self.normalized_settings(settings)
        return ConfiguredTableauSource(runtime, runtime["source"])
