"""Normalized report workflows independent of source vendors."""
from __future__ import annotations

import time
import uuid

from stats_core.config import METRIC_DEFS
from stats_core.errors import ValidationError
from stats_core.repositories.data_catalog import PRODUCT_REPORT_ID, REP_REPORT_ID

_PRODUCT_FIELDS = [
    {"key": "product", "label": "Product", "type": "text"},
    {"key": "close_rate", "label": "Close Rate", "type": "percent"},
]


class ReportService:
    def __init__(self, repos, adapters, rep_refresh, product_refresh):
        self.repos = repos
        self.adapters = dict(adapters or {})
        self.rep_refresh = rep_refresh
        self.product_refresh = product_refresh

    def prepare(self):
        self.repos.data_catalog.ensure(self.repos.settings.get())

    def _catalog(self):
        return self.repos.data_catalog.get(self.repos.settings.get())

    def _source(self, source_id):
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

    def _adapter_settings(self, source):
        adapter = self._adapter(source)
        secret = self.repos.source_credentials.get(source.get("id"))
        return adapter, adapter.with_secret(self.repos.settings.get(), secret)

    def get(self, report_id):
        report = self.repos.data_catalog.report(report_id, self.repos.settings.get())
        if not report:
            raise ValidationError("Report not found.")
        return report

    def list(self, source_id=None):
        rows = []
        for report in self._catalog()["reports"]:
            if source_id and str(report.get("source_id")) != str(source_id):
                continue
            item = dict(report)
            item["fields"] = self.fields(item["id"])
            item.update(self.status(item["id"]))
            rows.append(item)
        return rows

    def fields(self, report_id):
        report = self.get(report_id)
        kind = str(report.get("kind") or "table")
        if kind == "rep_performance":
            return [
                {"key": key, "label": label, "type": typ}
                for key, label, typ in METRIC_DEFS
            ]
        if kind == "product_close":
            return list(_PRODUCT_FIELDS)
        return list(self.repos.report_data.read(report_id).get("fields") or [])

    def rows(self, report_id):
        report = self.get(report_id)
        kind = str(report.get("kind") or "table")
        if kind == "rep_performance":
            return self.repos.reps.list()
        if kind == "product_close":
            return self.repos.products.list()
        return self.repos.report_data.read(report_id).get("rows") or []

    def status(self, report_id):
        report = self.get(report_id)
        kind = str(report.get("kind") or "table")
        if kind == "rep_performance":
            return {
                "status": self.repos.meta.get("source_status", ""),
                "last_refresh": self.repos.meta.get("last_source_refresh", ""),
            }
        if kind == "product_close":
            rows = self.repos.products.list()
            return {
                "status": self.repos.meta.get("product_close_status", ""),
                "last_refresh": rows[0].get("updated_at", "") if rows else "",
            }
        meta = self.repos.report_data.read(report_id).get("meta") or {}
        return {
            "status": str(meta.get("status") or ""),
            "last_refresh": str(meta.get("last_refresh") or ""),
        }

    def runtime_settings(self, report_id):
        report = self.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_settings(source)
        return adapter.report_settings(app_settings, source, report)

    def refresh(self, report_id):
        report = self.get(report_id)
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_settings(source)
        settings = adapter.report_settings(app_settings, source, report)
        kind = str(report.get("kind") or "table")
        if kind == "rep_performance":
            return self.rep_refresh.refresh(settings)
        if kind == "product_close":
            ok = self.product_refresh.refresh(settings)
            return {"ok": bool(ok), "rows": len(self.repos.products.list())}

        table = adapter.table(app_settings, source, report)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        saved = self.repos.report_data.replace(
            report_id,
            table.get("fields") or [],
            table.get("rows") or [],
            {
                "status": f"{len(table.get('rows') or [])} rows",
                "last_refresh": stamp,
                "start": table.get("start", ""),
                "end": table.get("end", ""),
                "export": table.get("export", ""),
                "truncated": bool(table.get("truncated")),
            },
        )
        self.repos.meta.bump("data_version")
        return {"ok": True, "rows": len(saved["rows"]), "fields": saved["fields"]}

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        source_id = str(incoming.get("source_id") or "").strip()
        self._source(source_id)
        report_id = str(incoming.get("id") or "").strip() or f"report-{uuid.uuid4().hex[:12]}"
        existing = self.repos.data_catalog.report(report_id, self.repos.settings.get()) or {}
        kind = str(incoming.get("kind") or existing.get("kind") or "table").strip()
        if report_id in (REP_REPORT_ID, PRODUCT_REPORT_ID):
            kind = "rep_performance" if report_id == REP_REPORT_ID else "product_close"
        elif kind not in {"table"}:
            kind = "table"
        name = str(incoming.get("name") or existing.get("name") or "Untitled Report").strip()[:120]
        if not name:
            raise ValidationError("Report name is required.")
        source_config = incoming.get("source_config") if isinstance(incoming.get("source_config"), dict) else existing.get("source_config", {})
        runtime = incoming.get("runtime") if isinstance(incoming.get("runtime"), dict) else existing.get("runtime", {})
        report = {
            "id": report_id,
            "source_id": source_id,
            "name": name,
            "kind": kind,
            "source_config": dict(source_config or {}),
            "runtime": dict(runtime or {}),
        }
        catalog = self._catalog()
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != report_id] + [report]
        self.repos.data_catalog.save(catalog)
        self.repos.meta.bump("settings_version")
        self._sync_legacy(report)
        return report

    def _sync_legacy(self, report):
        if str(report.get("id")) not in (REP_REPORT_ID, PRODUCT_REPORT_ID):
            return
        source = self._source(report.get("source_id"))
        adapter, app_settings = self._adapter_settings(source)
        settings = self.repos.settings.get()
        settings.update(adapter.legacy_projection(app_settings, source, report))
        self.repos.settings.save(settings)

    def delete(self, report_id):
        report_id = str(report_id or "").strip()
        if report_id in (REP_REPORT_ID, PRODUCT_REPORT_ID):
            raise ValidationError("Built-in reports cannot be deleted.")
        catalog = self._catalog()
        before = len(catalog["reports"])
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != report_id]
        if len(catalog["reports"]) == before:
            raise ValidationError("Report not found.")
        self.repos.data_catalog.save(catalog)
        self.repos.report_data.delete(report_id)
        self.repos.meta.bump("settings_version")
        return True
