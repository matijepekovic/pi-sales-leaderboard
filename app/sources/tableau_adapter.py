"""Tableau adapter for normalized Stats Source and Report contracts.

All Tableau connection, discovery and export details stay inside this adapter.
Downstream Stats code sees only Source definitions and normalized table data.
"""
from __future__ import annotations

import json
from copy import deepcopy

from sources import discovery
from sources.tableau_runtime import TableauRuntime
from sources.tableau_table import read_table

_REPORT_KEYS = (
    "workbook",
    "sheet",
    "filters",
    "date_start_field",
    "date_end_field",
    "export",
)


class TableauAdapter:
    key = "tableau"
    label = "Tableau"

    def __init__(self, runtime=None):
        self.runtime = runtime or TableauRuntime()

    @staticmethod
    def _connection(source):
        value = source.get("connection") if isinstance(source, dict) else {}
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def clean_source(incoming, existing=None):
        incoming = incoming if isinstance(incoming, dict) else {}
        existing = existing if isinstance(existing, dict) else {}
        raw = incoming.get("connection") if isinstance(incoming.get("connection"), dict) else existing.get("connection", {})
        return {
            "server": str(raw.get("server") or "").strip().rstrip("/")[:300],
            "site": str(raw.get("site") or "").strip()[:200],
            "pat_name": str(raw.get("pat_name") or "").strip()[:200],
            "secret_ref": "source_credentials",
        }

    @staticmethod
    def with_secret(app_settings, secret):
        settings = deepcopy(app_settings or {})
        settings["tableau_pat_secret"] = str(secret or "")
        return settings

    @staticmethod
    def candidate_overrides(body):
        body = body if isinstance(body, dict) else {}
        return {key: body[key] for key in _REPORT_KEYS + discovery.DATE_KEYS if key in body}

    def source_settings(self, app_settings, source):
        settings = deepcopy(app_settings or {})
        connection = self._connection(source)
        source_config = {
            "server": str(connection.get("server") or "").strip(),
            "site": str(connection.get("site") or "").strip(),
            "pat_name": str(connection.get("pat_name") or "").strip(),
        }
        settings["tableau_server"] = source_config["server"]
        settings["tableau_site"] = source_config["site"]
        settings["tableau_pat_name"] = source_config["pat_name"]
        settings["source"] = source_config
        return self.runtime.normalized_settings(settings)

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
        return self.runtime.normalized_settings(settings)

    def public_source(self, source, secret_configured=False):
        source = deepcopy(source or {})
        connection = self._connection(source)
        connection.pop("secret", None)
        connection["secret_configured"] = bool(secret_configured)
        source["connection"] = connection
        return source

    def test_connection(self, app_settings, source):
        connector = self.runtime.source(self.source_settings(app_settings, source))
        base = token = None
        try:
            base, token, _site_id = connector.signin()
            return {"message": "Connected to Tableau."}
        finally:
            if base and token:
                connector.signout(base, token)

    def report_values(self, app_settings, source):
        """Expose Tableau views through the generic Stats report-value contract."""
        connector = self.runtime.source(self.source_settings(app_settings, source))
        base = token = None
        try:
            base, token, site_id = connector.signin()
            status, raw = connector._request(
                f"{base}/sites/{site_id}/views?pageSize=1000"
                "&fields=name,contentUrl,project.name",
                token=token,
                timeout=15,
            )
            if status != 200:
                raise ValueError(f"Could not list reports from Tableau (HTTP {status}).")
            views = connector._view_list(json.loads(raw))
            values = []
            for view in views:
                content_url = str(view.get("contentUrl") or "").strip()
                if not content_url:
                    continue
                project = view.get("project") if isinstance(view.get("project"), dict) else {}
                values.append({
                    "id": content_url,
                    "label": str(view.get("name") or content_url).strip(),
                    "group": str(project.get("name") or "Other").strip() or "Other",
                })
            return sorted(values, key=lambda item: (item["group"].casefold(), item["label"].casefold()))
        finally:
            if base and token:
                connector.signout(base, token)

    @staticmethod
    def report_value(report):
        config = report.get("source_config") if isinstance(report, dict) else {}
        config = config if isinstance(config, dict) else {}
        workbook = str(config.get("workbook") or "").strip().strip("/")
        sheet = str(config.get("sheet") or "").strip().strip("/")
        return f"{workbook}/{sheet}" if workbook and sheet else ""

    @staticmethod
    def configure_report_value(value, existing=None):
        """Translate one opaque Stats source value into Tableau-only config."""
        value = str(value or "").strip().strip("/")
        parts = [part for part in value.split("/") if part]
        if len(parts) < 2:
            raise ValueError("Choose a valid Source report value.")
        config = dict(existing or {})
        config["workbook"] = parts[0]
        config["sheet"] = parts[-1]
        config.setdefault("export", "auto")
        config.setdefault("filters", [])
        return config

    def columns(self, app_settings, source, report, overrides=None):
        return discovery.read_columns(self.report_settings(app_settings, source, report), overrides or {})

    def table(self, app_settings, source, report, overrides=None):
        return read_table(self.report_settings(app_settings, source, report), overrides or {})

    def test_view(self, app_settings, source, report, overrides=None):
        return discovery.test_source(self.report_settings(app_settings, source, report), overrides or {})
