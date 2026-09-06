"""Normalized Report workflows independent of source vendors."""
from __future__ import annotations

import time
import hashlib
import json
import threading
import uuid
from datetime import date

from stats_core.errors import ValidationError
from stats_core.services.data_periods import resolve_timeframe
from stats_core.services.row_identity import infer_identity_field, infer_label_field


class ReportService:
    """Owns Report definitions and normalized pulled snapshots.

    Source adapters return table-shaped data. Everything downstream reads only
    the normalized Report contract stored by ``report_data``.
    """

    def __init__(self, repos, adapters, dependencies=None, clock=None):
        self.repos = repos
        self.adapters = dict(adapters or {})
        self.dependencies = dependencies
        self.clock = clock or time.time
        self._period_lock = threading.RLock()

    FIELD_TYPES = {"text", "number", "percent"}
    NUMERIC_FIELD_TYPES = {"number", "percent"}

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

    @staticmethod
    def _runtime(value):
        runtime = dict(value or {}) if isinstance(value, dict) else {}
        runtime["keep_last_known_rows"] = runtime.get("keep_last_known_rows") is not False
        raw_interval = runtime.get("update_interval_minutes")
        if raw_interval in (None, ""):
            runtime.pop("update_interval_minutes", None)
            return runtime
        if isinstance(raw_interval, bool):
            raise ValidationError("Report update interval must be a number of minutes.")
        try:
            interval = int(raw_interval)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Report update interval must be a number of minutes.") from exc
        if interval < 0 or interval > 10080:
            raise ValidationError("Report update interval must be between 0 and 10,080 minutes.")
        runtime["update_interval_minutes"] = interval
        return runtime

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
            config = item.get("source_config") if isinstance(item.get("source_config"), dict) else {}
            item["source_value"] = str(adapter.report_value(item) or "")
            item["filters"] = [dict(value) for value in (config.get("filters") or []) if isinstance(value, dict)]
            item["fields"] = self.fields(item["id"])
            item.update(self.status(item["id"]))
            rows.append(item)
        return sorted(rows, key=lambda item: str(item.get("name") or "").casefold())

    def fields(self, report_id):
        report = self.get(report_id)
        overrides = self._stored_field_overrides(report)
        fields = []
        for raw in self.repos.report_data.read(report_id).get("fields") or []:
            if not isinstance(raw, dict):
                continue
            field = dict(raw)
            key = str(field.get("key") or "")
            source_label = str(field.get("label") or key)
            source_data_type = str(field.get("type") or "text").strip().lower()
            source_type = self._normalized_display_type(source_data_type)
            override = overrides.get(key) if isinstance(overrides.get(key), dict) else {}
            display_type = str(override.get("type") or source_type)
            if display_type not in self._allowed_display_types(source_type):
                display_type = source_type
            display_label = str(override.get("label") or source_label)
            decimals = self._decimals(
                override.get("decimals"), self._default_decimals(display_type)
            )
            field.update({
                "label": display_label,
                "type": display_type,
                "decimals": decimals,
                "source_label": source_label,
                "source_type": source_type,
                "source_data_type": source_data_type,
                "customized": (
                    display_label != source_label
                    or display_type != source_type
                    or decimals != self._default_decimals(source_type)
                ),
            })
            if display_type == "percent":
                field["percent_input_scale"] = self.normalize_percent_input_scale(override.get("percent_input_scale"))
                field["customized"] = field["customized"] or field["percent_input_scale"] != "auto"
            else:
                field.pop("percent_input_scale", None)
            fields.append(field)
        return fields

    @classmethod
    def _allowed_display_types(cls, source_type):
        return cls.NUMERIC_FIELD_TYPES if source_type in cls.NUMERIC_FIELD_TYPES else {"text"}

    @classmethod
    def _normalized_display_type(cls, value):
        value = str(value or "text").strip().lower()
        if value == "currency":
            return "number"
        return value if value in cls.FIELD_TYPES else "text"

    @staticmethod
    def _default_decimals(field_type):
        return 1 if field_type == "percent" else 2 if field_type == "number" else 0

    @staticmethod
    def normalize_percent_input_scale(value):
        """Percentage input meaning is global Field metadata, not chart guesswork."""
        scale = str(value or "auto").strip().lower()
        if scale not in {"auto", "fraction", "points"}:
            raise ValidationError("Choose Automatic, 0.143 → 14.3%, or 14.3 → 14.3% for percentage values.")
        return scale

    @staticmethod
    def _decimals(value, default):
        if isinstance(value, bool):
            return default
        try:
            return min(max(int(value), 0), 8)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _validate_field_type(cls, source_type, field_type):
        if field_type not in cls.FIELD_TYPES:
            raise ValidationError("Field type must be Text, Number, or Percentage.")
        if field_type in cls._allowed_display_types(source_type):
            return
        if source_type == "text":
            raise ValidationError("Text fields must stay Text. You can still rename this Field.")
        raise ValidationError("Numeric fields can only be Number or Percentage.")

    @classmethod
    def _clean_field_overrides(cls, value):
        result = {}
        for key, raw in value.items() if isinstance(value, dict) else []:
            key = str(key or "").strip()
            if not key or not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or "").strip()[:120]
            field_type = cls._normalized_display_type(raw.get("type"))
            if not label or field_type not in cls.FIELD_TYPES:
                continue
            result[key] = {
                "label": label,
                "type": field_type,
                "decimals": cls._decimals(
                    raw.get("decimals"), cls._default_decimals(field_type)
                ),
            }
            if field_type == "percent":
                result[key]["percent_input_scale"] = cls.normalize_percent_input_scale(raw.get("percent_input_scale"))
        return result

    @classmethod
    def _stored_field_overrides(cls, report):
        """Read canonical overrides and migrate the former storage key in memory."""
        report = report if isinstance(report, dict) else {}
        value = report.get("field_overrides")
        if not isinstance(value, dict):
            value = report.get("display_values")
        return cls._clean_field_overrides(value)

    @staticmethod
    def _cleanup(value):
        value = value if isinstance(value, dict) else {}
        field = str(value.get("deduplicate_by") or "").strip()
        if not field:
            return {}
        keep = "last" if str(value.get("deduplicate_keep") or "first").lower() == "last" else "first"
        return {"deduplicate_by": field, "deduplicate_keep": keep}

    @staticmethod
    def _duplicate_key(value):
        if value is None:
            return None
        text = str(value).strip()
        return text.casefold() if text else None

    def _deduplicate_rows(self, rows, cleanup):
        cleanup = self._cleanup(cleanup)
        field = cleanup.get("deduplicate_by")
        if not field:
            return [dict(row) for row in rows]
        keep_last = cleanup.get("deduplicate_keep") == "last"
        source = list(reversed(rows)) if keep_last else list(rows)
        result, seen = [], set()
        for raw in source:
            row = dict(raw)
            key = self._duplicate_key(row.get(field))
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            result.append(row)
        return list(reversed(result)) if keep_last else result

    @classmethod
    def _window_keeps_previous_rows(cls, previous_meta, start, end):
        old_start = str((previous_meta or {}).get("start") or "").strip()
        old_end = str((previous_meta or {}).get("end") or "").strip()
        start = str(start or "").strip()
        end = str(end or "").strip()
        if not old_start or not old_end or not start or not end:
            return True
        try:
            old_start_date = date.fromisoformat(old_start)
            old_end_date = date.fromisoformat(old_end)
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except ValueError:
            return old_start == start and old_end == end
        return start_date <= old_start_date and end_date >= old_end_date

    def _merge_refresh_rows(self, previous, fields, rows, start, end):
        previous = previous if isinstance(previous, dict) else {}
        previous_rows = [dict(row) for row in (previous.get("rows") or []) if isinstance(row, dict)]
        previous_meta = dict(previous.get("meta") or {})
        preferred = str(previous_meta.get("identity_field") or "")
        field_keys = {str(field.get("key") or "") for field in fields}
        identity_field = preferred if preferred in field_keys else infer_identity_field(
            fields, rows or previous_rows
        )
        if not identity_field:
            return [dict(row) for row in rows], "", []
        if not self._window_keeps_previous_rows(previous_meta, start, end):
            return [dict(row) for row in rows], identity_field, []

        current_keys = {
            self._duplicate_key(row.get(identity_field))
            for row in rows
            if self._duplicate_key(row.get(identity_field)) is not None
        }
        merged = [dict(row) for row in rows]
        retained = []
        for previous_row in previous_rows:
            key = self._duplicate_key(previous_row.get(identity_field))
            if key is None or key in current_keys:
                continue
            merged.append(dict(previous_row))
            retained.append(str(previous_row.get(identity_field) or "").strip())
            current_keys.add(key)
        return merged, identity_field, retained

    def duplicates(self, report_id, field):
        fields = {str(item.get("key") or "") for item in self.fields(report_id)}
        field = str(field or "").strip()
        if field not in fields:
            raise ValidationError("Choose a valid field for duplicate detection.")
        counts, labels = {}, {}
        for row in self.rows(report_id):
            key = self._duplicate_key(row.get(field))
            if key is None:
                continue
            counts[key] = counts.get(key, 0) + 1
            labels.setdefault(key, str(row.get(field)).strip())
        groups = [
            {"value": labels[key], "count": count}
            for key, count in counts.items() if count > 1
        ]
        groups.sort(key=lambda item: (-item["count"], item["value"].casefold()))
        return {
            "field": field,
            "duplicate_rows": sum(item["count"] - 1 for item in groups),
            "duplicate_values": len(groups),
            "groups": groups[:100],
        }

    def set_deduplication(self, report_id, incoming):
        report = self.get(report_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        field = str(incoming.get("field") or "").strip()
        fields = {str(item.get("key") or "") for item in self.fields(report_id)}
        if field not in fields:
            raise ValidationError("Choose a valid field for duplicate removal.")
        cleanup = {"deduplicate_by": field, "deduplicate_keep": "last" if str(incoming.get("keep") or "first").lower() == "last" else "first"}
        updated = {**report, "cleanup": cleanup}
        catalog = self._catalog()
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != str(report_id)] + [updated]
        self.repos.data_catalog.save(catalog)
        snapshot = self.repos.report_data.read(report_id)
        rows = list(snapshot.get("rows") or [])
        cleaned = self._deduplicate_rows(rows, cleanup)
        meta = dict(snapshot.get("meta") or {})
        meta["status"] = f"{len(cleaned)} rows"
        self.repos.report_data.replace(report_id, snapshot.get("fields") or [], cleaned, meta)
        self.repos.meta.bump("settings_version")
        self.repos.meta.bump("data_version")
        return {"cleanup": cleanup, "removed": len(rows) - len(cleaned), "rows": len(cleaned)}

    def clear_deduplication(self, report_id):
        report = dict(self.get(report_id))
        report.pop("cleanup", None)
        catalog = self._catalog()
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != str(report_id)] + [report]
        self.repos.data_catalog.save(catalog)
        self.repos.meta.bump("settings_version")
        return True

    def update_report_field(self, report_id, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        report = self.get(report_id)
        key = str(incoming.get("field") or "").strip()
        raw_fields = [dict(field) for field in (self.repos.report_data.read(report_id).get("fields") or []) if isinstance(field, dict)]
        source = next((field for field in raw_fields if str(field.get("key") or "") == key), None)
        if not source:
            raise ValidationError("Report Field not found.")

        source_label = str(source.get("label") or key)
        source_type = self._normalized_display_type(source.get("type"))
        label = str(incoming.get("label") or "").strip()[:120]
        field_type = str(incoming.get("type") or "").strip().lower()
        decimals = self._decimals(
            incoming.get("decimals"), self._default_decimals(field_type)
        )
        if not label:
            raise ValidationError("Field name is required.")
        self._validate_field_type(source_type, field_type)

        overrides = self._stored_field_overrides(report)
        percent_input_scale = self.normalize_percent_input_scale(
            incoming.get("percent_input_scale", overrides.get(key, {}).get("percent_input_scale"))
        ) if field_type == "percent" else "auto"
        if (
            label == source_label
            and field_type == source_type
            and decimals == self._default_decimals(source_type)
            and percent_input_scale == "auto"
        ):
            overrides.pop(key, None)
        else:
            overrides[key] = {"label": label, "type": field_type, "decimals": decimals}
            if field_type == "percent":
                overrides[key]["percent_input_scale"] = percent_input_scale
        updated = dict(report)
        updated.pop("display_values", None)
        if overrides:
            updated["field_overrides"] = overrides
        else:
            updated.pop("field_overrides", None)
        catalog = self._catalog()
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != str(report_id)] + [updated]
        self.repos.data_catalog.save(catalog)
        self.repos.meta.bump("settings_version")
        return next(field for field in self.fields(report_id) if str(field.get("key") or "") == key)

    def rows(self, report_id):
        self.get(report_id)
        return [dict(row) for row in (self.repos.report_data.read(report_id).get("rows") or [])]

    @staticmethod
    def _query_fingerprint(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()

    @staticmethod
    def _query_ttl(report):
        try:
            minutes = int((report.get("runtime") or {}).get("update_interval_minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        return max(60, minutes * 60)

    def rows_for_period(self, report_id, timeframe):
        """Query an isolated period snapshot without changing the saved Report."""
        start, end = resolve_timeframe(timeframe)
        report = self.get(report_id)
        source = self._source(report.get("source_id"))
        if not source.get("enabled", True):
            raise ValidationError("Source is disabled.")
        runtime = dict(report.get("runtime") or {})
        configuration = self._query_fingerprint({
            "source": source,
            "source_config": report.get("source_config") or {},
            "cleanup": report.get("cleanup") or {},
            "keep_last_known_rows": runtime.get("keep_last_known_rows") is not False,
        })
        query_key = self._query_fingerprint({"configuration": configuration, "start": start, "end": end})
        with self._period_lock:
            cached = self.repos.report_data.read_query(report_id, query_key)
            fetched_at = (cached.get("meta") or {}).get("fetched_at")
            if isinstance(fetched_at, (int, float)) and 0 <= self.clock() - fetched_at < self._query_ttl(report):
                return [dict(row) for row in cached["rows"]]

            adapter, app_settings = self._adapter_settings(source)
            query = {**report, "runtime": {**runtime, "date_mode": "custom", "date_start": start, "date_end": end}}
            table = adapter.table(app_settings, source, query)
            if not isinstance(table, dict) or not isinstance(table.get("fields"), list) or not isinstance(table.get("rows"), list):
                raise ValidationError("The data source returned an invalid table for the requested timeframe.")
            if any(not isinstance(field, dict) or not field.get("key") for field in table["fields"]) or any(not isinstance(row, dict) for row in table["rows"]):
                raise ValidationError("The data source returned invalid Fields or rows for the requested timeframe.")
            if (table.get("start") and str(table["start"]) != start) or (table.get("end") and str(table["end"]) != end):
                raise ValidationError("The data source returned a different timeframe than requested.")
            fields = [dict(field) for field in table["fields"]]
            returned_keys = {str(field["key"]) for field in fields}
            expected_keys = {str(field["key"]) for field in self.fields(report_id)}
            missing = expected_keys - returned_keys
            if missing:
                raise ValidationError(f"The requested timeframe is missing Field '{sorted(missing)[0]}'.")
            rows = self._deduplicate_rows(table["rows"], report.get("cleanup"))
            previous = cached
            if not previous.get("meta"):
                compatible = [
                    snapshot for snapshot in self.repos.report_data.list_queries(report_id)
                    if (snapshot.get("meta") or {}).get("configuration") == configuration
                    and self._window_keeps_previous_rows(snapshot.get("meta"), start, end)
                ]
                previous = max(compatible, key=lambda item: float((item.get("meta") or {}).get("fetched_at") or 0), default={})
            if runtime.get("keep_last_known_rows") is not False:
                rows, identity_field, retained_row_keys = self._merge_refresh_rows(previous, fields, rows, start, end)
            else:
                identity_field = infer_identity_field(fields, rows)
                retained_row_keys = []
            saved = self.repos.report_data.replace_query(report_id, query_key, fields, rows, {
                "configuration": configuration, "query_key": query_key,
                "start": start, "end": end, "fetched_at": self.clock(),
                "last_refresh": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": f"{len(rows)} rows", "identity_field": identity_field,
                "retained_row_keys": retained_row_keys, "truncated": bool(table.get("truncated")),
            })
            return [dict(row) for row in saved["rows"]]

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
        meta = self.repos.report_data.read(report_id).get("meta") or {}
        identity_field = str(meta.get("identity_field") or "")
        retained_keys = {
            self._duplicate_key(value)
            for value in (meta.get("retained_row_keys") or [])
            if self._duplicate_key(value) is not None
        }
        label_field = infer_label_field(fields) or identity_field
        retained_rows = []
        if identity_field and retained_keys:
            for row in rows:
                identity = str(row.get(identity_field) or "").strip()
                if self._duplicate_key(identity) not in retained_keys:
                    continue
                retained_rows.append({
                    "identity": identity,
                    "label": str(row.get(label_field) or identity).strip(),
                })
        return {
            "report_id": report_id,
            "report_name": str(report.get("name") or report_id),
            "fields": fields,
            "sample_rows": rows[:sample_limit],
            "total_rows": len(rows),
            "retention": {
                "identity_field": identity_field,
                "saved_missing": retained_rows,
            },
            **self.status(report_id),
        }

    def status(self, report_id):
        self.get(report_id)
        meta = self.repos.report_data.read(report_id).get("meta") or {}
        return {
            "status": str(meta.get("status") or "Not pulled yet"),
            "last_refresh": str(meta.get("last_refresh") or ""),
            "retained_rows": len(meta.get("retained_row_keys") or []),
        }

    def remove_retained_row(self, report_id, incoming):
        self.get(report_id)
        incoming = incoming if isinstance(incoming, dict) else {}
        identity = str(incoming.get("identity") or "").strip()
        snapshot = self.repos.report_data.read(report_id)
        meta = dict(snapshot.get("meta") or {})
        identity_field = str(meta.get("identity_field") or "")
        retained = {
            self._duplicate_key(value)
            for value in (meta.get("retained_row_keys") or [])
            if self._duplicate_key(value) is not None
        }
        lookup = self._duplicate_key(identity)
        if not identity_field or lookup is None or lookup not in retained:
            raise ValidationError("Saved missing row not found.")
        rows = [
            dict(row) for row in (snapshot.get("rows") or [])
            if self._duplicate_key(row.get(identity_field)) != lookup
        ]
        meta["retained_row_keys"] = [
            value for value in (meta.get("retained_row_keys") or [])
            if self._duplicate_key(value) != lookup
        ]
        meta["status"] = f"{len(rows)} rows"
        self.repos.report_data.replace(report_id, snapshot.get("fields") or [], rows, meta)
        self.repos.meta.bump("data_version")
        return {"removed": identity, "rows": len(rows)}

    def refresh(self, report_id):
        report = self.get(report_id)
        source = self._source(report.get("source_id"))
        if not source.get("enabled", True):
            raise ValidationError("Source is disabled.")
        adapter, app_settings = self._adapter_settings(source)
        table = adapter.table(app_settings, source, report)
        fields = [dict(item) for item in (table.get("fields") or []) if isinstance(item, dict)]
        rows = [dict(item) for item in (table.get("rows") or []) if isinstance(item, dict)]
        rows = self._deduplicate_rows(rows, report.get("cleanup"))
        previous = self.repos.report_data.read(report_id)
        start = str(table.get("start") or "")
        end = str(table.get("end") or "")
        if report.get("runtime", {}).get("keep_last_known_rows") is not False:
            rows, identity_field, retained_row_keys = self._merge_refresh_rows(
                previous, fields, rows, start, end
            )
        else:
            previous_identity = str((previous.get("meta") or {}).get("identity_field") or "")
            identity_field = infer_identity_field(fields, rows, previous_identity)
            retained_row_keys = []
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        saved = self.repos.report_data.replace(
            report_id,
            fields,
            rows,
            {
                "status": f"{len(rows)} rows",
                "last_refresh": stamp,
                "start": start,
                "end": end,
                "export": str(table.get("export") or ""),
                "truncated": bool(table.get("truncated")),
                "identity_field": identity_field,
                "retained_row_keys": retained_row_keys,
            },
        )
        self.repos.meta.bump("data_version")
        return {
            "ok": True,
            "rows": len(saved["rows"]),
            "retained_rows": len(retained_row_keys),
            "fields": self.fields(report_id),
        }

    def candidate(self, incoming, report_id=""):
        """Build a Report definition without persisting it."""
        incoming = incoming if isinstance(incoming, dict) else {}
        source_id = str(incoming.get("source_id") or "").strip()
        source = self._source(source_id)
        adapter = self._adapter(source)
        report_id = str(report_id or "").strip()
        existing = self.repos.data_catalog.report(report_id) or {} if report_id else {}
        name = str(incoming.get("name") or existing.get("name") or "Untitled Report").strip()[:120]
        if not name:
            raise ValidationError("Report name is required.")

        incoming_config = incoming.get("source_config") if isinstance(incoming.get("source_config"), dict) else existing.get("source_config", {})
        incoming_config = dict(incoming_config or {})
        if isinstance(incoming.get("filters"), list):
            incoming_config["filters"] = [dict(value) for value in incoming["filters"] if isinstance(value, dict)]
        source_value = str(incoming.get("source_value") or "").strip()
        if source_value:
            try:
                source_config = adapter.configure_report_value(source_value, incoming_config)
            except (TypeError, ValueError) as exc:
                raise ValidationError(str(exc) or "Choose a valid Source report value.") from exc
        else:
            source_config = incoming_config

        runtime = incoming.get("runtime") if isinstance(incoming.get("runtime"), dict) else existing.get("runtime", {})
        incoming_overrides = incoming.get("field_overrides")
        if not isinstance(incoming_overrides, dict):
            incoming_overrides = incoming.get("display_values")
        if not isinstance(incoming_overrides, dict):
            incoming_overrides = (
                existing.get("field_overrides")
                if isinstance(existing.get("field_overrides"), dict)
                else existing.get("display_values")
            )
        field_overrides = self._clean_field_overrides(incoming_overrides)
        cleanup = self._cleanup(incoming.get("cleanup") if isinstance(incoming.get("cleanup"), dict) else existing.get("cleanup"))
        if report_id and field_overrides:
            raw_fields = [dict(field) for field in (self.repos.report_data.read(report_id).get("fields") or []) if isinstance(field, dict)]
            for field in raw_fields:
                key = str(field.get("key") or "")
                override = field_overrides.get(key)
                if not override:
                    continue
                source_type = self._normalized_display_type(field.get("type"))
                self._validate_field_type(source_type, override["type"])
        result = {
            "source_id": source_id,
            "name": name,
            "source_config": dict(source_config or {}),
            "runtime": self._runtime(runtime),
        }
        if field_overrides:
            result["field_overrides"] = field_overrides
        if cleanup:
            result["cleanup"] = cleanup
        return result

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        report_id = str(incoming.get("id") or "").strip() or f"report-{uuid.uuid4().hex[:12]}"
        report = {"id": report_id, **self.candidate(incoming, report_id)}
        catalog = self._catalog()
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != report_id] + [report]
        self.repos.data_catalog.save(catalog)
        self.repos.meta.bump("settings_version")
        return report

    def delete(self, report_id):
        report_id = str(report_id or "").strip()
        self.get(report_id)
        used_by = self.dependencies(report_id) if self.dependencies else []
        if used_by:
            raise ValidationError(f"This Report supplies Fields used by {used_by[0]}. Remove or replace those references first.")
        for screen in self.repos.screens.list():
            if report_id in [str(value) for value in (screen.get("reports") or [])]:
                raise ValidationError("This Report is used by a Screen. Remove it from that Screen first.")
        for definition in self.repos.groups.list_types():
            if str(definition.get("report_id") or "") == report_id:
                raise ValidationError("This Report supplies a Group Type. Change or delete that Group Type first.")
        catalog = self._catalog()
        before = len(catalog["reports"])
        catalog["reports"] = [row for row in catalog["reports"] if str(row.get("id")) != report_id]
        if len(catalog["reports"]) == before:
            raise ValidationError("Report not found.")
        self.repos.data_catalog.save(catalog)
        self.repos.report_data.delete(report_id)
        self.repos.fields.delete_report(report_id)
        self.repos.table_presets.delete_report(report_id)
        self.repos.meta.bump("settings_version")
        return True
