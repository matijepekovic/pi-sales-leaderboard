"""Instance-local named Field periods, composed only through the Fields API.

Reusable Fields retain their identity, names and definitions. The placement ID
is a local column identity; Data still owns every period pull and its cache.
"""
from __future__ import annotations

import json
import uuid

from stats_core.errors import ValidationError
from stats_core.services.data_periods import normalize_interval, normalize_timeframe, timeframe_intervals


def normalize_field_variants(field_ids, variants, fields):
    """Validate local definitions without reading rows or contacting a source."""
    if variants is None:
        return []
    if not isinstance(variants, list) or len(variants) > 12:
        raise ValidationError("Choose at most 12 custom Field versions per Widget instance.")
    if not variants:
        return []
    metadata = {item["id"]: item for item in fields.resolve(field_ids)}
    ids, labels = set(metadata), {str(item.get("label") or "").strip().casefold() for item in metadata.values()}
    result, point_count = [], 0
    for raw in variants:
        if not isinstance(raw, dict) or set(raw) - {"id", "field_id", "label", "timeframe", "interval", "aggregation"}:
            raise ValidationError("Invalid custom Field version settings.")
        source_id = str(raw.get("field_id") or "")
        if source_id not in metadata:
            raise ValidationError("A custom version must use a Field already selected in this Widget.")
        source = metadata[source_id]
        if source.get("type") not in {"number", "percent"} or source.get("kind") == "table":
            raise ValidationError("Choose a numeric value Field for a custom timeframe.")
        label = str(raw.get("label") or "").strip()
        if not 1 <= len(label) <= 120:
            raise ValidationError("Name the custom Field version (1–120 characters).")
        if label.casefold() in labels:
            raise ValidationError("Give each custom Field version a name different from the original and other versions.")
        variant_id = str(raw.get("id") or f"placement-{uuid.uuid4().hex[:12]}").strip()
        if not variant_id.startswith("placement-") or len(variant_id) > 120 or variant_id in ids:
            raise ValidationError("Each custom Field version needs a unique identity of at most 120 characters.")
        timeframe = normalize_timeframe(raw.get("timeframe"))
        interval = normalize_interval(raw.get("interval"))
        aggregation = str(raw.get("aggregation") or "")
        if aggregation and aggregation not in {"none", "sum", "average", "count"}:
            raise ValidationError("Choose individual values, total, average, or row count for each timeline point.")
        if interval and not aggregation:
            raise ValidationError("Choose what each timeline point should show: individual values, total, average, or row count.")
        if interval and source.get("type") == "percent" and aggregation == "sum":
            raise ValidationError("Percentages cannot be added together. Choose average or individual values.")
        # Binning is pure date arithmetic. Validation never evaluates Fields.
        point_count += len(timeframe_intervals(timeframe, interval)) if interval else 1
        if point_count > 120:
            raise ValidationError("These custom versions need more than 120 period queries. Use fewer versions, wider intervals, or shorter ranges.")
        value = {"id": variant_id, "field_id": source_id, "label": label, "timeframe": timeframe}
        if interval:
            value["interval"] = interval
        if aggregation:
            value["aggregation"] = aggregation
        result.append(value)
        ids.add(variant_id)
        labels.add(label.casefold())
    return result


def _row_keys(row):
    values = row.get("__row_keys") or []
    if row.get("__row_key") is not None:
        values = [row["__row_key"], *values]
    return list(dict.fromkeys(str(value) for value in values if value is not None and str(value)))


def _indexed_rows(rows, allow_unmatched=False):
    result, aliases = [], {}
    for source in rows:
        keys = _row_keys(source)
        if not keys and not allow_unmatched:
            raise ValidationError("Choose ‘Match rows using’ so custom periods match the same records, not their row positions.")
        if any(key in aliases for key in keys):
            raise ValidationError("The matching Field repeats within this period. Choose a Field that identifies one row.")
        index = len(result)
        result.append(dict(source))
        for key in keys:
            aliases[key] = index
    return result, aliases


def _merge_period(rows, aliases, period_rows, variant, metadata, identity_field_id, dependencies):
    """Full outer match. Historical-only rows keep labels, never current totals."""
    incoming, unused = _indexed_rows(period_rows, allow_unmatched=True)
    del unused
    for source in incoming:
        keys = _row_keys(source)
        matches = {aliases[key] for key in keys if key in aliases}
        if len(matches) > 1:
            raise ValidationError("The saved matching rules connect this period to multiple rows. Update the match in Fields.")
        if matches:
            index = matches.pop()
            target = rows[index]
        else:
            target = {key: source.get(key) for key in ("__group_ids", "__row_key", "__row_keys") if key in source}
            for field_id, field in metadata.items():
                if field.get("type") in {"text", "asset"} or field_id == identity_field_id:
                    target[field_id] = source.get(field_id)
                elif field.get("type") in {"number", "percent"}:
                    target[field_id] = 0
            index = len(rows)
            rows.append(target)
        target[variant["id"]] = source.get(variant["field_id"])
        if variant["field_id"] in (source.get("__invalid_fields") or []):
            target.setdefault("__invalid_fields", []).append(variant["id"])
        for local_id, source_id in dependencies.items():
            target[local_id] = source.get(source_id)
            if source_id in (source.get("__invalid_fields") or []):
                target.setdefault("__invalid_fields", []).append(local_id)
        joined_keys = list(dict.fromkeys([*_row_keys(target), *keys]))
        target["__row_keys"] = joined_keys
        for key in joined_keys:
            aliases[key] = index


def evaluate_field_placements(fields, field_ids, context, *, dependencies=None):
    """Return original columns, local period columns and real dated snapshots.

    `timelines[].points[].rows` use original Field IDs and unaggregated values;
    Widgets owns the eventual calculation for each point. No timeline values
    are fabricated from the current snapshot or derived from refresh dates.
    """
    context = context if isinstance(context, dict) else {}
    dependencies = dependencies or {}
    variants = normalize_field_variants(field_ids, context.get("field_variants"), fields)
    evaluation_context = {key: value for key, value in context.items() if key != "field_variants"}
    base = fields.evaluate(field_ids, evaluation_context)
    metadata = {field["id"]: dict(field) for field in base["fields"]}
    local_metadata = []
    for variant in variants:
        local_metadata.append({**metadata[variant["field_id"]], "id": variant["id"], "key": variant["id"],
                               "label": variant["label"], "source_field_id": variant["field_id"],
                               "timeframe": variant["timeframe"], "placement": True, "instance_only": True})
    hidden_metadata = []
    for variant in variants:
        for local_id, source_id in dependencies.get(variant["id"], {}).items():
            if source_id not in metadata or local_id in metadata or any(item["id"] == local_id for item in local_metadata + hidden_metadata):
                raise ValidationError("A custom Field calculation has an invalid period dependency.")
            hidden_metadata.append({**metadata[source_id], "id": local_id, "key": local_id,
                                    "label": f"{metadata[source_id]['label']} · {variant['label']}",
                                    "source_field_id": source_id, "timeframe": variant["timeframe"],
                                    "instance_only": True, "hidden": True})
    rows = [dict(row) for row in base["rows"]]
    flat = [variant for variant in variants if not variant.get("interval")]
    if flat:
        known_identity = bool(context.get("identity_field_id") or base.get("matching") or any(_row_keys(row) for row in rows))
        if not known_identity:
            raise ValidationError("Choose ‘Match rows using’ before comparing Field periods.")
        rows, aliases = _indexed_rows(rows, allow_unmatched=True)
    cache, timelines = {}, []

    def evaluate_period(timeframe):
        key = json.dumps(timeframe, sort_keys=True)
        if key not in cache:
            cache[key] = fields.evaluate(field_ids, {**evaluation_context, "timeframe": timeframe})
        return cache[key]

    for variant, field in zip(variants, local_metadata):
        if variant.get("interval"):
            points = []
            for period in timeframe_intervals(variant["timeframe"], variant["interval"]):
                snapshot = evaluate_period({"preset": "custom", "start_date": period["start_date"], "end_date": period["end_date"]})
                points.append({**period, "fields": snapshot["fields"], "rows": snapshot["rows"]})
            timelines.append({"field_id": variant["id"], "source_field_id": variant["field_id"], "label": variant["label"],
                              "field": field, "timeframe": variant["timeframe"], "interval": variant["interval"],
                              "aggregation": variant["aggregation"], "points": points})
        else:
            snapshot = evaluate_period(variant["timeframe"])
            _merge_period(rows, aliases, snapshot["rows"], variant, metadata, context.get("identity_field_id"), dependencies.get(variant["id"], {}))
    for row in rows:
        for variant in flat:
            # Missing joined numeric cells are blank cells, not invalid math.
            row.setdefault(variant["id"], 0)
            for local_id in dependencies.get(variant["id"], {}):
                row.setdefault(local_id, 0)
    return {**base, "fields": [*metadata.values(), *local_metadata, *hidden_metadata], "rows": rows,
            "field_variants": variants, "timelines": timelines}
