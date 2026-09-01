"""Source workflows behind replaceable adapter contracts."""
from __future__ import annotations

import threading
import uuid

from stats_core.errors import BusyError, ValidationError
from stats_core.repositories.data_catalog import (
    PRIMARY_SOURCE_ID,
    PRODUCT_REPORT_ID,
    REP_REPORT_ID,
)


class SourceService:
    def __init__(self, repos, reports, preview, adapters):
        self.repos = repos
        self.reports = reports
        self.preview_store = preview
        self.adapters = dict(adapters or {})
        self._refresh_lock = threading.Lock()

    def prepare(self):
        """Create normalized source/report records and migrate the old secret once."""
        current = self.repos.data_catalog.get()
        if not current["sources"] and not current["reports"]:
            adapter = self.adapters.get("tableau") or next(iter(self.adapters.values()), None)
            if adapter:
                settings = self.repos.settings.get()
                current = self.repos.data_catalog.ensure(
                    adapter.initial_catalog(
                        settings,
                        PRIMARY_SOURCE_ID,
                        REP_REPORT_ID,
                        PRODUCT_REPORT_ID,
                    )
                )
                if not self.repos.source_credentials.get(PRIMARY_SOURCE_ID):
                    secret = adapter.legacy_secret(settings)
                    if secret:
                        self.repos.source_credentials.set(PRIMARY_SOURCE_ID, secret)
            else:
                current = self.repos.data_catalog.ensure()
        return current

    def _catalog(self):
        return self.repos.data_catalog.get()

    def _source(self, source_id):
        source = self.repos.data_catalog.source(source_id)
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
        existing = self.repos.data_catalog.source(source_id) or {}
        default_adapter = next(iter(self.adapters), "")
        adapter_key = str(incoming.get("adapter") or existing.get("adapter") or default_adapter).strip()
        adapter = self.adapters.get(adapter_key)
        if not adapter:
            raise ValidationError(f"Source adapter '{adapter_key}' is not available.")
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
        catalog = self._catalog()
        catalog["sources"] = [
            row for row in catalog["sources"] if str(row.get("id")) != source_id
        ] + [source]
        self.repos.data_catalog.save(catalog)
        if isinstance(incoming.get("secret"), str):
            self.repos.source_credentials.set(source_id, incoming["secret"].strip())
        if incoming.get("clear_secret") is True:
            self.repos.source_credentials.set(source_id, "")
        self.repos.meta.bump("settings_version")
        return self.get(source_id)

    def delete(self, source_id):
        source_id = str(source_id or "").strip()
        if source_id == PRIMARY_SOURCE_ID:
            raise ValidationError("The built-in source cannot be deleted.")
        if self.reports.list(source_id=source_id):
            raise ValidationError("Delete this source's reports before deleting the source.")
        catalog = self._catalog()
        before = len(catalog["sources"])
        catalog["sources"] = [
            row for row in catalog["sources"] if str(row.get("id")) != source_id
        ]
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
        return {
            **result,
            "message": f"Connected. {result.get('selected_rows', 0)} matching rows.",
        }

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
        return adapter.columns(
            app_settings,
            source,
            report,
            adapter.candidate_overrides(body),
        )

    def test_report(self, report_id, body):
        report = self.reports.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_context(source)
        return adapter.test_view(
            app_settings,
            source,
            report,
            adapter.candidate_overrides(body),
        )

    def preview_report(self, report_id, body):
        report = self.reports.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_context(source)
        overrides = adapter.candidate_overrides(body)
        kind = str(report.get("kind") or "table")
        if kind == "rep_performance":
            start, end, rows, notes = adapter.preview(
                app_settings, source, report, overrides
            )
            if not rows:
                raise ValidationError(
                    "That pull came back with no people, so there is nothing to preview."
                )
            on_tv = bool((body or {}).get("on_tv"))
            if on_tv:
                self.preview_store.start(rows, str(report.get("name") or "Report"))
            return {
                "start": start,
                "end": end,
                "reps": len(rows),
                "notes": notes,
                "on_tv": on_tv,
                "preview": self.preview_store.state(),
                "rows": self.repos.reps.apply_organization(
                    [dict(row) for row in rows]
                ),
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
