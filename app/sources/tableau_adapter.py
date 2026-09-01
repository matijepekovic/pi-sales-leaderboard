"""Tableau adapter for normalized Stats Source and Report contracts.

All Tableau connection, discovery, export, mapping and migration details live
inside this adapter. Downstream Stats code sees only normalized source/report
records and normalized rows.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from sources import discovery
from sources import tableau_base as _base
from sources.tableau_product_market import ProductCloseSource, selected_market
from sources.tableau_runtime import TableauRuntime
from sources.tableau_table import read_table

_REPORT_KEYS = (
    "server", "site", "pat_name", "workbook", "sheet", "filters",
    "date_start_field", "date_end_field", "mapping", "row_filter", "export",
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

    def initial_catalog(self, app_settings, source_id, rep_report_id, product_report_id):
        """One-time migration from the installed pre-catalog configuration."""
        settings = app_settings if isinstance(app_settings, dict) else {}
        legacy = settings.get("source") if isinstance(settings.get("source"), dict) else {}
        source = {
            "id": source_id,
            "name": self.label,
            "adapter": self.key,
            "enabled": True,
            "connection": self.clean_source({
                "connection": {
                    "server": legacy.get("server") or settings.get("tableau_server"),
                    "site": legacy.get("site") or settings.get("tableau_site"),
                    "pat_name": legacy.get("pat_name") or settings.get("tableau_pat_name"),
                }
            }),
        }
        rep_config = {
            key: legacy.get(key)
            for key in (
                "workbook", "sheet", "filters", "date_start_field", "date_end_field",
                "mapping", "row_filter", "export",
            )
            if key in legacy
        }
        return {
            "sources": [source],
            "reports": [
                {
                    "id": rep_report_id,
                    "source_id": source_id,
                    "name": "Sales Rep Performance",
                    "kind": "rep_performance",
                    "source_config": rep_config,
                    "runtime": {
                        "date_mode": str(settings.get("data_date_mode") or "current_month"),
                        "date_start": str(settings.get("data_date_start") or ""),
                        "date_end": str(settings.get("data_date_end") or ""),
                    },
                },
                {
                    "id": product_report_id,
                    "source_id": source_id,
                    "name": "Close Rate by Product",
                    "kind": "product_close",
                    "source_config": {},
                    "runtime": {"market": str(settings.get("product_market") or "Olympia")},
                },
            ],
        }

    @staticmethod
    def legacy_secret(app_settings):
        """One-time secret migration only; no runtime compatibility projection."""
        return str((app_settings or {}).get("tableau_pat_secret") or "")

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
        server = str(connection.get("server") or "").strip()
        site = str(connection.get("site") or "").strip()
        pat_name = str(connection.get("pat_name") or "").strip()
        if server: settings["tableau_server"] = server
        if site: settings["tableau_site"] = site
        if pat_name: settings["tableau_pat_name"] = pat_name
        source_config = dict(settings.get("source") or {})
        source_config.update({
            "server": server or str(source_config.get("server") or ""),
            "site": site or str(source_config.get("site") or ""),
            "pat_name": pat_name or str(source_config.get("pat_name") or ""),
        })
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
        if "date_mode" in runtime: settings["data_date_mode"] = str(runtime.get("date_mode") or "current_month")
        if "date_start" in runtime: settings["data_date_start"] = str(runtime.get("date_start") or "")
        if "date_end" in runtime: settings["data_date_end"] = str(runtime.get("date_end") or "")
        if "market" in runtime: settings["product_market"] = str(runtime.get("market") or "")
        return self.runtime.normalized_settings(settings)

    def public_source(self, source, secret_configured=False):
        source = deepcopy(source or {})
        connection = self._connection(source)
        connection.pop("secret", None)
        connection["secret_configured"] = bool(secret_configured)
        source["connection"] = connection
        return source

    def _rep_scope(self, settings, source, report):
        runtime = self.runtime.normalized_settings(settings)
        start, end = _base.resolve_dates(runtime)
        config = dict(runtime.get("source") or {})
        fingerprint = hashlib.sha256(
            json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()[:24]
        return {
            "id": f"{source.get('id')}:{report.get('id')}:{start}:{end}:{fingerprint}",
            "start": start,
            "end": end,
        }

    def rep_scope(self, app_settings, source, report):
        return self._rep_scope(self.report_settings(app_settings, source, report), source, report)

    def pull_reps(self, app_settings, source, report):
        settings = self.report_settings(app_settings, source, report)
        connector = self.runtime.source(settings)
        rows = connector.fetch()
        scope = self._rep_scope(settings, source, report)
        runtime = self.runtime.normalized_settings(settings)
        return {
            "rows": rows,
            "scope": scope,
            "start": scope["start"],
            "end": scope["end"],
            "total_rows": int(getattr(connector, "last_total_rows", 0) or 0),
            "offices": list(getattr(connector, "last_offices", []) or []),
            "collapsed": list((getattr(connector, "last_notes", {}) or {}).get("collapsed") or []),
            "office": str(runtime.get("data_office") or ""),
        }

    def pull_products(self, app_settings, source, report, start=None, end=None, market=None, fallback_markets=None):
        settings = self.report_settings(app_settings, source, report)
        market = str(market or selected_market(settings)).strip()
        connector = ProductCloseSource(settings, fallback_markets=fallback_markets)
        resolved_start, resolved_end, rows = connector.fetch_products(start=start, end=end, market=market)
        return {"rows": rows, "start": resolved_start, "end": resolved_end, "market": market}

    def product_markets(self, app_settings, source, report, fallback_markets=None):
        settings = self.report_settings(app_settings, source, report)
        return ProductCloseSource(settings, fallback_markets=fallback_markets).fetch_markets()

    def test_connection(self, app_settings, source):
        preview = self.runtime.source(self.source_settings(app_settings, source)).preview()
        return {
            "start": preview["start"], "end": preview["end"],
            "total_rows": preview["total_rows"], "selected_rows": preview["selected_rows"],
            "offices": preview["offices"], "names": preview["names"],
        }

    def workbooks(self, app_settings, source):
        return discovery.list_workbooks(self.source_settings(app_settings, source))

    def all_views(self, app_settings, source):
        return discovery.list_all_views(self.source_settings(app_settings, source))

    def views(self, app_settings, source, workbook):
        return discovery.list_views(self.source_settings(app_settings, source), workbook)

    def columns(self, app_settings, source, report, overrides=None):
        return discovery.read_columns(self.report_settings(app_settings, source, report), overrides or {})

    def preview(self, app_settings, source, report, overrides=None):
        return discovery.preview_pull(self.report_settings(app_settings, source, report), overrides or {})

    def table(self, app_settings, source, report, overrides=None):
        return read_table(self.report_settings(app_settings, source, report), overrides or {})

    def test_view(self, app_settings, source, report, overrides=None):
        return discovery.test_source(self.report_settings(app_settings, source, report), overrides or {})
