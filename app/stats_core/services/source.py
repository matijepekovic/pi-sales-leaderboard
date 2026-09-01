"""Source workflows behind replaceable adapter contracts."""
from __future__ import annotations

import threading
import uuid

from stats_core.errors import BusyError, ValidationError


class SourceService:
    """Owns Source definitions and delegates vendor behavior to adapters."""

    def __init__(self, repos, reports, adapters):
        self.repos = repos
        self.reports = reports
        self.adapters = dict(adapters or {})
        self._refresh_lock = threading.Lock()

    def prepare(self):
        return self.repos.data_catalog.ensure()

    def _catalog(self):
        return self.repos.data_catalog.get()

    def _source(self, source_id):
        source = self.repos.data_catalog.source(source_id)
        if not source:
            raise ValidationError("Source not found.")
        return source

    def _adapter(self, source):
        key = str(source.get("adapter") or "").strip()
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
        return sorted(rows, key=lambda item: str(item.get("name") or "").casefold())

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
        existing = self.repos.data_catalog.source(source_id) or {}
        default_adapter = next(iter(self.adapters), "")
        adapter_key = str(incoming.get("adapter") or existing.get("adapter") or default_adapter).strip()
        adapter = self.adapters.get(adapter_key)
        if not adapter:
            raise ValidationError(f"Source adapter '{adapter_key}' is not available.")
        catalog = self._catalog()
        if not existing and any(str(row.get("adapter") or "").strip() == adapter_key for row in catalog["sources"]):
            raise ValidationError(f"{adapter.label} is already configured. Additional Sources are coming soon.")
        name = str(incoming.get("name") or existing.get("name") or adapter.label).strip()[:120]
        if not name:
            raise ValidationError("Source name is required.")
        source = {
            "id": source_id,
            "name": name,
            "adapter": adapter_key,
            "enabled": bool(incoming.get("enabled", existing.get("enabled", True))),
            "connection": adapter.clean_source(incoming, existing),
        }
        catalog["sources"] = [row for row in catalog["sources"] if str(row.get("id")) != source_id] + [source]
        self.repos.data_catalog.save(catalog)
        if isinstance(incoming.get("secret"), str) and incoming.get("secret"):
            self.repos.source_credentials.set(source_id, incoming["secret"].strip())
        if incoming.get("clear_secret") is True:
            self.repos.source_credentials.delete(source_id)
        self.repos.meta.bump("settings_version")
        return self.get(source_id)

    def delete(self, source_id):
        source_id = str(source_id or "").strip()
        if self.reports.list(source_id=source_id):
            raise ValidationError("Delete this Source's Reports first.")
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
        return adapter.test_connection(app_settings, source)

    def report_values_for(self, source_id):
        """Return vendor-neutral report choices exposed by one Source."""
        source = self._source(source_id)
        adapter, app_settings = self._adapter_context(source)
        values = adapter.report_values(app_settings, source)
        return [
            {"id": str(item.get("id") or ""), "label": str(item.get("label") or "")}
            for item in (values or [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        ]

    def columns_for(self, report_id, body):
        report = self.reports.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_context(source)
        return adapter.columns(app_settings, source, report, adapter.candidate_overrides(body))

    def test_report(self, report_id, body):
        report = self.reports.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_context(source)
        return adapter.test_view(app_settings, source, report, adapter.candidate_overrides(body))

    def preview_report(self, report_id, body):
        report = self.reports.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_context(source)
        table = adapter.table(app_settings, source, report, adapter.candidate_overrides(body))
        return {
            "preview": {
                "fields": [dict(item) for item in (table.get("fields") or []) if isinstance(item, dict)],
                "rows": [dict(item) for item in (table.get("rows") or [])[:50] if isinstance(item, dict)],
                "total_rows": len(table.get("rows") or []),
                "start": str(table.get("start") or ""),
                "end": str(table.get("end") or ""),
                "export": str(table.get("export") or ""),
                "truncated": bool(table.get("truncated")),
            }
        }

    def refresh_report(self, report_id):
        if not self._refresh_lock.acquire(blocking=False):
            raise BusyError("A refresh is already running.")
        try:
            return self.reports.refresh(report_id)
        finally:
            self._refresh_lock.release()
