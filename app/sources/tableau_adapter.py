"""Tableau adapter for the normalized Stats Source/Report contracts.

Nothing outside this adapter needs to know how Tableau connection fields,
workbooks, views, mappings, filters or export settings are represented.
"""
from __future__ import annotations

from copy import deepcopy

from sources import discovery
from stats_core.services.tableau import TableauService


class TableauAdapter:
    key = "tableau"
    label = "Tableau"

    def __init__(self, tableau=None):
        self.tableau = tableau or TableauService()

    @staticmethod
    def _connection(source):
        value = source.get("connection") if isinstance(source, dict) else {}
        return dict(value) if isinstance(value, dict) else {}

    def source_settings(self, app_settings, source):
        settings = deepcopy(app_settings or {})
        connection = self._connection(source)
        server = str(connection.get("server") or "").strip()
        site = str(connection.get("site") or "").strip()
        pat_name = str(connection.get("pat_name") or "").strip()
        if server:
            settings["tableau_server"] = server
        if site:
            settings["tableau_site"] = site
        if pat_name:
            settings["tableau_pat_name"] = pat_name
        source_config = dict(settings.get("source") or {})
        source_config.update({
            "server": server or str(source_config.get("server") or ""),
            "site": site or str(source_config.get("site") or ""),
            "pat_name": pat_name or str(source_config.get("pat_name") or ""),
        })
        settings["source"] = source_config
        return self.tableau.normalized_settings(settings)

    def report_settings(self, app_settings, source, report):
        settings = self.source_settings(app_settings, source)
        report = report if isinstance(report, dict) else {}
        source_config = dict(settings.get("source") or {})
        configured = report.get("source_config") if isinstance(report.get("source_config"), dict) else {}
        source_config.update(configured)
        settings["source"] = source_config
        runtime = report.get("runtime") if isinstance(report.get("runtime"), dict) else {}
        if "date_mode" in runtime:
            settings["data_date_mode"] = str(runtime.get("date_mode") or "current_month")
        if "date_start" in runtime:
            settings["data_date_start"] = str(runtime.get("date_start") or "")
        if "date_end" in runtime:
            settings["data_date_end"] = str(runtime.get("date_end") or "")
        if "market" in runtime:
            settings["product_market"] = str(runtime.get("market") or "")
        return self.tableau.normalized_settings(settings)

    def public_source(self, source, app_settings=None):
        source = deepcopy(source or {})
        connection = self._connection(source)
        connection.pop("secret", None)
        connection["secret_configured"] = bool(
            str((app_settings or {}).get("tableau_pat_secret") or "").strip()
        )
        source["connection"] = connection
        return source

    def test_connection(self, app_settings, source):
        preview = self.tableau.source(self.source_settings(app_settings, source)).preview()
        return {
            "start": preview["start"],
            "end": preview["end"],
            "total_rows": preview["total_rows"],
            "selected_rows": preview["selected_rows"],
            "offices": preview["offices"],
            "names": preview["names"],
        }

    def workbooks(self, app_settings, source):
        return discovery.list_workbooks(self.source_settings(app_settings, source))

    def all_views(self, app_settings, source):
        return discovery.list_all_views(self.source_settings(app_settings, source))

    def views(self, app_settings, source, workbook):
        return discovery.list_views(self.source_settings(app_settings, source), workbook)

    def columns(self, app_settings, source, report, overrides=None):
        settings = self.report_settings(app_settings, source, report)
        return discovery.read_columns(settings, overrides or {})

    def preview(self, app_settings, source, report, overrides=None):
        settings = self.report_settings(app_settings, source, report)
        return discovery.preview_pull(settings, overrides or {})

    def test_view(self, app_settings, source, report, overrides=None):
        settings = self.report_settings(app_settings, source, report)
        return discovery.test_source(settings, overrides or {})

    def legacy_projection(self, app_settings, source, report=None):
        """Return the old settings shape while old pull code is still active."""
        settings = self.report_settings(app_settings, source, report or {})
        connection = self._connection(source)
        projected = {
            "tableau_server": str(connection.get("server") or ""),
            "tableau_site": str(connection.get("site") or ""),
            "tableau_pat_name": str(connection.get("pat_name") or ""),
            "source": dict(settings.get("source") or {}),
        }
        runtime = (report or {}).get("runtime") if isinstance((report or {}).get("runtime"), dict) else {}
        if "date_mode" in runtime:
            projected["data_date_mode"] = runtime.get("date_mode")
        if "date_start" in runtime:
            projected["data_date_start"] = runtime.get("date_start")
        if "date_end" in runtime:
            projected["data_date_end"] = runtime.get("date_end")
        if "market" in runtime:
            projected["product_market"] = runtime.get("market")
        return projected
