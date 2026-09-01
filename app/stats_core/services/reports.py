"""Normalized Report workflows independent of source vendors."""
from __future__ import annotations

import time
import uuid

from stats_core.errors import ValidationError


class ReportService:
    """Owns Report definitions and normalized pulled snapshots.

    Source adapters return table-shaped data. Everything downstream reads only
    the normalized Report contract stored by ``report_data``.
    """

    def __init__(self, repos, adapters):
        self.repos = repos
        self.adapters = dict(adapters or {})

    def prepare(self):
        return None

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

    def _adapter_settings(self, source):
        adapter = self._adapter(source)
        secret = self.repos.source_credentials.get(source.get("id"))
        return adapter, adapter.with_secret(self.repos.settings.get(), secret)

    def get(self, report_id):
        report = self.repos.data_catalog.report(report_id)
        if not report:
            raise ValidationError("Report not found.")
        return report

    def list(self, source_id=None):
        rows = []
        for report in self._catalog()["reports"]:
            if source_id and str(report.get("source_id")) != str(source_id):
                continue
            item = dict(report)
            source = self._source(item.get("source_id"))
            adapter = self._adapter(source)
            item["source_value"] = str(adapter.report_value(item) or "")
            item["fields"] = self.fields(item["id"])
            item.update(self.status(item["id"]))
            rows.append(item)
        return sorted(rows, key=lambda item: str(item.get("name") or "").casefold())

    def fields(self, report_id):
        self.get(report_id)
        return [dict(field) for field in (self.repos.report_data.read(report_id).get("fields") or [])]

    def rows(self, report_id):
        self.get(report_id)
        return [dict(row) for row in (self.repos.report_data.read(report_id).get("rows") or [])]

    def inspect(self, report_id, sample_limit=20, value_limit=500):
        fields = self.fields(report_id)
        rows = self.rows(report_id)
        try:
            sample_limit = min(max(int(sample_limit), 1), 50)
        except Exception:
            sample_limit = 20
        try:
            value_limit = min(max(int(value_limit), 1), 2000)
        except Exception:
            value_limit = 500

        for field in fields:
            key = str(field.get("key") or "")
            values, seen = [], set()
            for row in rows:
                raw = row.get(key)
                if raw is None:
                    continue
                text = str(raw).strip()
                if not text:
                    continue
                folded = text.casefold()
                if folded in seen:
                    continue
                seen.add(folded)
                values.append(text)
                if len(values) >= value_limit:
                    break
            values.sort(key=str.casefold)
            field["sample_values"] = values

        report = self.get(report_id)
        return {
            "report_id": report_id,
            "report_name": str(report.get("name") or report_id),
            "fields": fields,
            "sample_rows": rows[:sample_limit],
            "total_rows": len(rows),
            **self.status(report_id),
        }

    def status(self, report_id):
        self.get(report_id)
        meta = self.repos.report_data.read(report_id).get("meta") or {}
        return {
            "status": str(meta.get("status") or "Not pulled yet"),
            "last_refresh": str(meta.get("last_refresh") or ""),
        }

    def refresh(self, report_id):
        report = self.get(report_id)
        source = self._source(report.get("source_id"))
        if not source.get("enabled", True):
            raise ValidationError("Source is disabled.")
        adapter, app_settings = self._adapter_settings(source)
        table = adapter.table(app_settings, source, report)
        fields = [dict(item) for item in (table.get("fields") or []) if isinstance(item, dict)]
        rows = [dict(item) for item in (table.get("rows") or []) if isinstance(item, dict)]
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        saved = self.repos.report_data.replace(
            report_id,
            fields,
            rows,
            {
                "status": f"{len(rows)} rows",
                "last_refresh": stamp,
                "start": str(table.get("start") or ""),
                "end": str(table.get("end") or ""),
                "export": str(table.get("export") or ""),
                "truncated": bool(table.get("truncated")),
            },
        )
        self.repos.meta.bump("data_version")
        return {"ok": True, "rows": len(saved["rows"]), "fields": saved["fields"]}

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        source_id = str(incoming.get("source_id") or "").strip()
        source = self._source(source_id)
        adapter = self._adapter(source)
        report_id = str(incoming.get("id") or "").strip() or f"report-{uuid.uuid4().hex[:12]}"
        existing = self.repos.data_catalog.report(report_id) or {}
        name = str(incoming.get("name") or existing.get("name") or "Untitled Report").strip()[:120]
        if not name:
            raise ValidationError("Report name is required.")

        incoming_config = incoming.get("source_config") if isinstance(incoming.get("source_config"), dict) else existing.get("source_config", {})
        source_value = str(incoming.get("source_value") or "").strip()
        if source_value:
            try:
                source_config = adapter.configure_report_value(source_value, incoming_config)
            except (TypeError, ValueError) as exc:
                raise ValidationError(str(exc) or "Choose a valid Source report value.") from exc
        else:
            source_config = dict(incoming_config or {})

        runtime = incoming.get("runtime") if isinstance(incoming.get("runtime"), dict) else existing.get("runtime", {})
        report = {
            "id": report_id,
            "source_id": source_id,
            "name": name,
            "source_config": dict(source_config or {}),
            "runtime": dict(runtime or {}),
        }
        catalog = self._catalog()
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != report_id] + [report]
        self.repos.data_catalog.save(catalog)
        self.repos.meta.bump("settings_version")
        return report

    def delete(self, report_id):
        report_id = str(report_id or "").strip()
        for screen in self.repos.screens.list():
            if report_id in [str(value) for value in (screen.get("reports") or [])]:
                raise ValidationError("This Report is used by a Screen. Remove it from that Screen first.")
        catalog = self._catalog()
        before = len(catalog["reports"])
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != report_id]
        if len(catalog["reports"]) == before:
            raise ValidationError("Report not found.")
        self.repos.data_catalog.save(catalog)
        self.repos.report_data.delete(report_id)
        self.repos.meta.bump("settings_version")
        return True
