"""Source workflows behind replaceable adapter contracts."""
from __future__ import annotations

import threading
import uuid

from stats_core.config import METRIC_DEFS
from stats_core.errors import BusyError, ValidationError
from stats_core.repositories.data_catalog import PRIMARY_SOURCE_ID, REP_REPORT_ID


class SourceService:
    def __init__(self, repos, reports, preview, adapters):
        self.repos = repos
        self.reports = reports
        self.preview_store = preview
        self.adapters = dict(adapters or {})
        self._refresh_lock = threading.Lock()

    def prepare(self):
        self.repos.data_catalog.ensure(self.repos.settings.get())

    def _catalog(self):
        return self.repos.data_catalog.get(self.repos.settings.get())

    def _source(self, source_id=PRIMARY_SOURCE_ID):
        source = self.repos.data_catalog.source(source_id, self.repos.settings.get())
        if not source:
            raise ValidationError("Source not found.")
        return source

    def _adapter(self, source):
        key = str(source.get("adapter") or "")
        adapter = self.adapters.get(key)
        if not adapter:
            raise ValidationError(f"Source adapter '{key}' is not available.")
        return adapter

    def _adapter_context(self, source):
        adapter = self._adapter(source)
        secret = self.repos.source_credentials.get(source.get("id"))
        app_settings = adapter.with_secret(self.repos.settings.get(), secret)
        return adapter, app_settings

    def list(self):
        rows = []
        for source in self._catalog()["sources"]:
            adapter = self._adapter(source)
            secret = self.repos.source_credentials.get(source.get("id"))
            public = adapter.public_source(source, secret_configured=bool(secret))
            public["reports"] = self.reports.list(source_id=source.get("id"))
            rows.append(public)
        return rows

    def get(self, source_id):
        source = self._source(source_id)
        adapter = self._adapter(source)
        secret = self.repos.source_credentials.get(source.get("id"))
        public = adapter.public_source(source, secret_configured=bool(secret))
        public["reports"] = self.reports.list(source_id=source.get("id"))
        return public

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        source_id = str(incoming.get("id") or "").strip() or f"source-{uuid.uuid4().hex[:12]}"
        existing = self.repos.data_catalog.source(source_id, self.repos.settings.get()) or {}
        adapter_key = str(incoming.get("adapter") or existing.get("adapter") or "tableau").strip()
        if adapter_key not in self.adapters:
            raise ValidationError(f"Source adapter '{adapter_key}' is not available.")
        name = str(incoming.get("name") or existing.get("name") or self.adapters[adapter_key].label).strip()[:120]
        if not name:
            raise ValidationError("Source name is required.")
        raw_connection = incoming.get("connection") if isinstance(incoming.get("connection"), dict) else existing.get("connection", {})
        connection = {
            key: str(raw_connection.get(key) or "").strip()[:300]
            for key in ("server", "site", "pat_name")
        }
        connection["secret_ref"] = "source_credentials"
        source = {
            "id": source_id,
            "name": name,
            "adapter": adapter_key,
            "enabled": bool(incoming.get("enabled", existing.get("enabled", True))),
            "connection": connection,
        }
        catalog = self._catalog()
        catalog["sources"] = [row for row in catalog["sources"] if str(row.get("id")) != source_id] + [source]
        self.repos.data_catalog.save(catalog)
        if isinstance(incoming.get("secret"), str):
            secret = incoming["secret"].strip()
            if secret:
                self.repos.source_credentials.set(source_id, secret)
        if incoming.get("clear_secret") is True:
            self.repos.source_credentials.set(source_id, "")
        self.repos.meta.bump("settings_version")
        if source_id == PRIMARY_SOURCE_ID:
            self._sync_primary_legacy(source)
        return self.get(source_id)

    def _sync_primary_legacy(self, source):
        report = self.repos.data_catalog.report(REP_REPORT_ID, self.repos.settings.get()) or {}
        adapter, app_settings = self._adapter_context(source)
        settings = self.repos.settings.get()
        settings.update(adapter.legacy_projection(app_settings, source, report))
        settings["tableau_pat_secret"] = self.repos.source_credentials.get(source.get("id"))
        self.repos.settings.save(settings)

    def delete(self, source_id):
        source_id = str(source_id or "").strip()
        if source_id == PRIMARY_SOURCE_ID:
            raise ValidationError("The built-in Tableau source cannot be deleted.")
        if self.reports.list(source_id=source_id):
            raise ValidationError("Delete this source's reports before deleting the source.")
        catalog = self._catalog()
        before = len(catalog["sources"])
        catalog["sources"] = [row for row in catalog["sources"] if str(row.get("id")) != source_id]
        if len(catalog["sources"]) == before:
            raise ValidationError("Source not found.")
        self.repos.data_catalog.save(catalog)
        self.repos.source_credentials.delete(source_id)
        self.repos.meta.bump("settings_version")
        return True

    def test(self, source_id):
        source = self._source(source_id)
        adapter, app_settings = self._adapter_context(source)
        result = adapter.test_connection(app_settings, source)
        return {**result, "message": f"Connected. {result.get('selected_rows', 0)} matching rows."}

    def workbooks_for(self, source_id):
        source = self._source(source_id)
        adapter, app_settings = self._adapter_context(source)
        return adapter.workbooks(app_settings, source)

    def all_views_for(self, source_id):
        source = self._source(source_id)
        adapter, app_settings = self._adapter_context(source)
        return adapter.all_views(app_settings, source)

    def views_for(self, source_id, workbook):
        source = self._source(source_id)
        adapter, app_settings = self._adapter_context(source)
        return adapter.views(app_settings, source, workbook)

    def columns_for(self, report_id, body):
        report = self.reports.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_context(source)
        overrides = adapter.candidate_overrides(body)
        return adapter.columns(app_settings, source, report, overrides)

    def test_report(self, report_id, body):
        report = self.reports.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_context(source)
        overrides = adapter.candidate_overrides(body)
        return adapter.test_view(app_settings, source, report, overrides)

    def preview_report(self, report_id, body):
        report = self.reports.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_context(source)
        overrides = adapter.candidate_overrides(body)
        kind = str(report.get("kind") or "table")
        if kind == "rep_performance":
            start, end, rows, notes = adapter.preview(app_settings, source, report, overrides)
            if not rows:
                raise ValidationError("That pull came back with no people, so there is nothing to preview.")
            on_tv = bool((body or {}).get("on_tv"))
            if on_tv:
                label = str(report.get("name") or "Report")
                self.preview_store.start(rows, label)
            return {
                "start": start, "end": end, "reps": len(rows), "notes": notes,
                "on_tv": on_tv, "preview": self.preview_store.state(),
                "rows": self.repos.reps.apply_organization([dict(row) for row in rows]),
            }
        table = adapter.table(app_settings, source, report, overrides)
        return {"preview": table, "on_tv": False}

    def refresh_report(self, report_id):
        if not self._refresh_lock.acquire(blocking=False):
            raise BusyError("A refresh is already running.")
        try:
            return self.reports.refresh(report_id)
        finally:
            self._refresh_lock.release()

    # Legacy endpoints remain active while the existing Settings frontend is
    # replaced. They delegate to the normalized built-in source/report rather
    # than owning a second Tableau implementation.
    def options(self):
        reps = self.repos.reps.list()
        status = self.reports.status(REP_REPORT_ID)
        return {
            "offices": sorted({str(r.get("home_branch") or "").strip() for r in reps if str(r.get("home_branch") or "").strip()}),
            "names": sorted({str(r.get("rep_name") or "").strip() for r in reps if str(r.get("rep_name") or "").strip()}, key=str.lower),
            "source_status": status["status"],
            "last_source_refresh": status["last_refresh"],
            "scheduled_tableau_status": self.repos.meta.get("scheduled_tableau_status", ""),
            "scheduled_tableau_last_attempt": self.repos.meta.get("scheduled_tableau_last_attempt", ""),
        }

    def test_connection(self):
        return self.test(PRIMARY_SOURCE_ID)

    def refresh(self):
        return self.refresh_report(REP_REPORT_ID)

    def report(self):
        report = self.reports.get(REP_REPORT_ID)
        config = dict(report.get("source_config") or {})
        source = self._source(report.get("source_id"))
        connection = dict(source.get("connection") or {})
        return {
            "row_filter_columns": [
                {"key": key, "label": label}
                for key, label, typ in METRIC_DEFS if typ == "text"
            ],
            "workbook": str(config.get("workbook") or ""),
            "sheet": str(config.get("sheet") or "").rsplit("/", 1)[-1],
            "is_default": False, "default_workbook": "", "default_sheet": "",
            "server": str(connection.get("server") or ""),
            "site": str(connection.get("site") or ""),
            "pat_name": str(connection.get("pat_name") or ""),
            "filters": config.get("filters") or [],
            "date_start_field": str(config.get("date_start_field") or "Start"),
            "date_end_field": str(config.get("date_end_field") or "End"),
            "row_filter": config.get("row_filter") or {},
            "mapping": config.get("mapping") or {},
            "export": str(config.get("export") or "auto"),
            "defaults": {
                "server": "", "site": "", "pat_name": "", "workbook": "", "sheet": "",
                "export": "auto", "filters": [], "date_start_field": "Start",
                "date_end_field": "End", "mapping": {}, "row_filter": {},
            },
        }

    def workbooks(self): return self.workbooks_for(PRIMARY_SOURCE_ID)
    def all_views(self): return self.all_views_for(PRIMARY_SOURCE_ID)
    def views(self, workbook): return self.views_for(PRIMARY_SOURCE_ID, workbook)
    def columns(self, body): return self.columns_for(REP_REPORT_ID, body)
    def preview(self, body): return self.preview_report(REP_REPORT_ID, body)
    def stop_preview(self): return self.preview_store.stop()
    def preview_state(self): return self.preview_store.state()
    def test_view(self, body): return self.test_report(REP_REPORT_ID, body)
