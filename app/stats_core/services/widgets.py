"""Reusable visualization structure over the public Fields contract."""
from __future__ import annotations

import math
import json
import uuid

from stats_core.errors import ValidationError
from stats_core.services.widget_charts import (
    AGGREGATIONS, RATIO_MODES, build_chart, numeric_value, validate_chart_meaning,
    measurement_settings,
)
from stats_core.services.field_placements import normalize_field_variants, evaluate_field_placements
from stats_core.services.data_periods import normalize_timeframe
from stats_core.services.widget_timelines import build_timeline


KINDS = {"table", "bar", "line", "pie"}
OPERATORS = {"equals", "not_equals", "contains", "not_contains", "greater_than", "greater_or_equal", "less_than", "less_or_equal"}


class WidgetService:
    """Own structure and filtering, with no source, Theme or Screen storage access."""

    def __init__(self, repository, fields, meta, dependencies=None, change_validation=None):
        self.repository = repository
        self.fields = fields
        self.meta = meta
        self.dependencies = dependencies
        self.change_validation = change_validation

    def list(self):
        return sorted(self.repository.list(), key=lambda item: str(item.get("name") or "").casefold())

    def get(self, widget_id):
        widget = self.repository.get(str(widget_id or ""))
        if not widget:
            raise ValidationError("Widget not found.")
        return widget

    def field_dependencies(self, widget_id):
        """All selected and filtering Fields, without exposing Field storage."""
        widget = self.get(widget_id)
        return list(dict.fromkeys([*widget.get("field_ids", []),
                                  *[rule["field_id"] for rule in widget.get("filters", [])]]))

    def field_consumers(self):
        """Each reusable Widget is one Field query for relationship guards."""
        return [{"name": widget["name"], "field_ids": self.field_dependencies(widget["id"])}
                for widget in self.list()]

    @staticmethod
    def _keys(value, allowed, label):
        if not isinstance(value, dict):
            raise ValidationError(f"{label} must be an object.")
        unexpected = set(value) - set(allowed)
        if unexpected:
            raise ValidationError(f"{label} does not own '{sorted(unexpected)[0]}'.")

    @staticmethod
    def _ids(value, label, allow_empty=False):
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValidationError(f"Choose valid {label}.")
        result = list(dict.fromkeys(item.strip() for item in value))
        if (not result and not allow_empty) or len(result) > 100:
            raise ValidationError(f"Choose between 1 and 100 {label}.")
        return result

    def normalize(self, incoming, widget_id=None):
        self._keys(incoming, {"id", "name", "kind", "field_ids", "filters", "chart"}, "Widget")
        name = str(incoming.get("name") or "").strip()
        if not name or len(name) > 120:
            raise ValidationError("Widget name must contain between 1 and 120 characters.")
        kind = str(incoming.get("kind") or "table")
        if kind not in KINDS:
            raise ValidationError("Choose Table, Bar, Line, or Pie.")
        field_ids = self._ids(incoming.get("field_ids"), "Fields")
        rules = incoming.get("filters", [])
        if not isinstance(rules, list) or len(rules) > 100:
            raise ValidationError("Widget filters must be a list of at most 100 rules.")
        filters = []
        for rule in rules:
            self._keys(rule, {"field_id", "operator", "value"}, "Widget filter")
            field_id = str(rule.get("field_id") or "").strip()
            operator = str(rule.get("operator") or "equals")
            value = rule.get("value")
            if not field_id or operator not in OPERATORS:
                raise ValidationError("Choose a valid Field and filter comparison.")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValidationError("Filter values must be text, numbers, or empty.")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValidationError("Filter values must be finite numbers.")
            if isinstance(value, str) and len(value) > 500:
                raise ValidationError("Filter values must be 500 characters or fewer.")
            filters.append({"field_id": field_id, "operator": operator, "value": value})
        all_ids = list(dict.fromkeys(field_ids + [rule["field_id"] for rule in filters]))
        metadata = {field["id"]: field for field in self.fields.resolve(all_ids)}
        for rule in filters:
            if metadata[rule["field_id"]].get("kind") == "table":
                raise ValidationError("Generated table Fields are evaluated after filtering.")
            if (
                metadata[rule["field_id"]].get("type") in {"number", "percent"}
                and rule["operator"] in {"equals", "not_equals"}
                and rule["value"] not in (None, "")
                and self._number(rule["value"]) is None
            ):
                raise ValidationError("Numeric Field comparisons require a numeric value.")
            if rule["operator"] in {"greater_than", "greater_or_equal", "less_than", "less_or_equal"}:
                if metadata[rule["field_id"]].get("type") not in {"number", "percent"} or self._number(rule["value"]) is None:
                    raise ValidationError("Numeric comparisons require a numeric Field and value.")
        result = {"id": str(widget_id or incoming.get("id") or f"widget-{uuid.uuid4().hex[:12]}"),
                  "name": name, "kind": kind, "field_ids": field_ids, "filters": filters}
        chart = incoming.get("chart") or {}
        if chart or kind != "table":
            result["chart"] = self._chart(chart, kind, field_ids, metadata)
        return result

    def _chart(self, chart, kind, field_ids, metadata):
        self._keys(chart, {"dimension_field_id", "measure_field_ids", "aggregation",
                           "denominator_field_id", "pie_mode", "measure_settings", "layout",
                           "result_type", "ratio_mode", "category_order"}, "Chart")
        dimension = str(chart.get("dimension_field_id") or "").strip()
        measures = self._ids(chart.get("measure_field_ids", []), "chart measures", allow_empty=kind == "table")
        aggregation = str(chart.get("aggregation", "none"))
        if aggregation not in AGGREGATIONS:
            raise ValidationError("Choose individual values, a total, an average, a count, or a ratio.")
        if dimension and (dimension not in field_ids or metadata[dimension].get("type") == "asset" or metadata[dimension].get("kind") == "table"):
            raise ValidationError("Choose a selected value or label Field for chart categories.")
        clean = {"dimension_field_id": dimension, "measure_field_ids": measures, "aggregation": aggregation}
        for key in ("denominator_field_id", "pie_mode", "layout", "result_type", "ratio_mode", "category_order"):
            if key in chart:
                clean[key] = chart[key]
        custom = chart.get("measure_settings", {})
        if not isinstance(custom, dict) or set(custom) - set(measures):
            raise ValidationError("Calculation settings must belong to a selected measured Field.")
        if "measure_settings" in chart:
            clean["measure_settings"] = {}
        for field_id, value in custom.items():
            self._keys(value, {"aggregation", "denominator_field_id", "result_type", "ratio_mode"}, "Value calculation")
            clean["measure_settings"][field_id] = dict(value)
        for measure in measures:
            if measure not in field_ids or metadata[measure].get("kind") == "table" or metadata[measure].get("type") == "asset":
                raise ValidationError("Choose selected value Fields for chart measures, not assets or generated rank.")
            settings = measurement_settings(clean, measure)
            if settings["aggregation"] not in AGGREGATIONS:
                raise ValidationError("Choose a valid calculation for each value.")
            if settings.get("result_type", "number") not in {"number", "percent"}:
                raise ValidationError("Display ratios as Number or Percentage.")
            if settings.get("ratio_mode", "totals") not in RATIO_MODES:
                raise ValidationError("Choose a valid ratio calculation.")
            if settings["aggregation"] == "ratio":
                denominator = settings.get("denominator_field_id")
                if denominator not in field_ids or metadata[denominator].get("kind") == "table":
                    raise ValidationError("Ratio of totals needs a selected numeric denominator Field.")
        # A table can retain dormant visual configuration, without applying it
        # to its raw rows or losing it when the Widget is saved and reopened.
        if measures:
            validation = {**clean, "layout": "separate"} if kind == "table" else clean
            validate_chart_meaning("bar" if kind == "table" else kind, validation, metadata)
        return clean

    def save(self, incoming, widget_id=None):
        if widget_id:
            self.get(widget_id)
        definition = self.normalize(incoming, widget_id)
        if any(item["id"] != definition["id"] and str(item["name"]).casefold() == definition["name"].casefold() for item in self.repository.list()):
            raise ValidationError("A Widget with that name already exists.")
        if self.change_validation:
            self.change_validation(definition)
        self.repository.save(definition)
        self.meta.bump("settings_version")
        return definition

    def delete(self, widget_id):
        definition = self.get(widget_id)
        used_by = self.dependencies(widget_id) if self.dependencies else []
        if used_by:
            raise ValidationError(f"This Widget is used by {used_by[0]}. Remove or replace it there first.")
        self.repository.delete(widget_id)
        self.meta.bump("settings_version")
        return definition

    @staticmethod
    def _number(value):
        return numeric_value(value)

    @classmethod
    def _matches(cls, row, rule, metadata):
        actual, expected = row.get(rule["field_id"]), rule["value"]
        operator = rule["operator"]
        if metadata[rule["field_id"]].get("type") in {"number", "percent"} and (
            rule["field_id"] in (row.get("__invalid_fields") or [])
            or (actual is None and metadata[rule["field_id"]].get("kind") == "calculated")
        ):
            return False
        if metadata[rule["field_id"]].get("type") in {"number", "percent"} and operator not in {"contains", "not_contains"}:
            field = metadata[rule["field_id"]]
            percentage = field.get("type") == "percent"
            actual = numeric_value(actual, percentage=percentage, percentage_scale=field.get("percent_input_scale", "auto"))
            # Preserve persisted auto-encoded rules. New UI rules use an explicit
            # '%' suffix for displayed percentages, independent of source scale.
            expected = numeric_value(expected, percentage=percentage)
        else:
            actual = str(actual if actual is not None else "").strip().casefold()
            expected = str(expected if expected is not None else "").strip().casefold()
        if operator == "equals":
            return actual == expected
        if operator == "not_equals":
            return actual != expected
        if operator == "contains":
            return expected in actual
        if operator == "not_contains":
            return expected not in actual
        if actual is None or expected is None:
            return False
        return {"greater_than": lambda: actual > expected,
                "greater_or_equal": lambda: actual >= expected,
                "less_than": lambda: actual < expected,
                "less_or_equal": lambda: actual <= expected}[operator]()

    def _context(self, context):
        context = {} if context is None else context
        self._keys(context, {"group_ids", "ranking", "timeframe", "field_variants", "identity_field_id"}, "Widget context")
        ranking = context.get("ranking") or []
        if not isinstance(ranking, list) or len(ranking) > 3:
            raise ValidationError("Ranking accepts up to three priority Fields.")
        clean = []
        for rule in ranking:
            self._keys(rule, {"field_id", "direction"}, "Ranking")
            field_id, direction = str(rule.get("field_id") or ""), str(rule.get("direction") or "desc")
            if not field_id or direction not in {"asc", "desc"}:
                raise ValidationError("Choose a valid ranking Field and direction.")
            clean.append({"field_id": field_id, "direction": direction})
        result = {**context, "ranking": clean}
        if context.get("timeframe") is not None:
            result["timeframe"] = normalize_timeframe(context["timeframe"])
        identity = str(context.get("identity_field_id") or "").strip()
        if len(identity) > 120:
            raise ValidationError("Choose a valid Field to match rows across periods.")
        if "identity_field_id" in context:
            result["identity_field_id"] = identity
        return result

    @staticmethod
    def _placement_chart(definition, variants):
        """Ephemeral measures: neither aliases nor period dependencies are saved."""
        original = definition.get("chart") or {}
        chart = {**original, "measure_field_ids": list(original.get("measure_field_ids") or []),
                 "measure_settings": {key: dict(value) for key, value in (original.get("measure_settings") or {}).items()}}
        dependencies = {}
        for variant in variants:
            if variant.get("interval"):
                continue
            source_id = variant["field_id"]
            settings = measurement_settings(original, source_id)
            if variant.get("aggregation"):
                settings = {"aggregation": variant["aggregation"]}
            if settings["aggregation"] == "ratio":
                local_id = f"{variant['id']}:denominator"
                dependencies[variant["id"]] = {local_id: settings["denominator_field_id"]}
                settings = {**settings, "denominator_field_id": local_id}
            chart["measure_field_ids"].append(variant["id"])
            chart["measure_settings"][variant["id"]] = settings
        return chart, dependencies

    def _render(self, definition, context):
        context = self.validate_definition_context(definition, context)
        field_ids = definition["field_ids"]
        query_ids = list(dict.fromkeys(field_ids + [rule["field_id"] for rule in definition["filters"]] + [rule["field_id"] for rule in context["ranking"]]))
        if context.get("identity_field_id"):
            query_ids = list(dict.fromkeys([*query_ids, context["identity_field_id"]]))
        variants = context.get("field_variants") or []
        chart_definition, dependencies = self._placement_chart(definition, variants) if definition["kind"] != "table" else ({}, {})
        data = evaluate_field_placements(self.fields, query_ids, context, dependencies=dependencies) if variants else self.fields.evaluate(query_ids, context)
        metadata = {field["id"]: field for field in data["fields"]}
        rows = [row for row in data["rows"] if all(self._matches(row, rule, metadata) for rule in definition["filters"])]
        if context["ranking"]:
            # A source changing its row order must not change an otherwise tied winner.
            rows.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
        for rule in reversed(context["ranking"]):
            field_id = rule["field_id"]
            field = metadata[field_id]
            if field.get("kind") == "table" or field.get("type") == "asset":
                raise ValidationError("Rank by a value Field, not a generated rank or asset.")
            def value(row):
                raw = row.get(field_id)
                if field_id in (row.get("__invalid_fields") or []) or (raw is None and field.get("kind") == "calculated"):
                    return None
                return numeric_value(raw, percentage=field.get("type") == "percent", percentage_scale=field.get("percent_input_scale", "auto")) if field.get("type") in {"number", "percent"} else str(raw or "").casefold()
            present = [row for row in rows if value(row) is not None and (field.get("type") in {"number", "percent"} or row.get(field_id) not in (None, ""))]
            missing = [row for row in rows if value(row) is None or (field.get("type") not in {"number", "percent"} and row.get(field_id) in (None, ""))]
            present.sort(key=value, reverse=rule["direction"] == "desc")
            rows = present + missing
        rows = self.fields.rank(field_ids, rows)
        visible_ids = [*field_ids, *[variant["id"] for variant in variants if not variant.get("interval")]]
        hidden_ids = {field_id for field_id, field in metadata.items() if field.get("hidden")}
        row_metadata = {"__group_ids", "__field_assets", "__row_key", "__row_keys", "__invalid_fields"}
        payload = {"widget_id": definition["id"], "name": definition["name"], "kind": definition["kind"],
                   "fields": [metadata[field_id] for field_id in visible_ids],
                   "rows": [{key: value for key, value in row.items() if key in visible_ids or key in hidden_ids or key in row_metadata} for row in rows],
                   "total_rows": len(rows)}
        if data.get("matching"):
            payload["matching"] = data["matching"]
        if context.get("timeframe"):
            payload["timeframe"] = context["timeframe"]
        if variants:
            payload["field_variants"] = variants
        if hidden_ids:
            payload["calculation_fields"] = [metadata[field_id] for field_id in hidden_ids]
        if definition["kind"] != "table":
            base_chart = build_chart(definition["kind"], chart_definition, rows, metadata)
            timeline_panels = []
            for timeline in data.get("timelines") or []:
                points = []
                for point in timeline["points"]:
                    point_metadata = {field["id"]: field for field in point["fields"]}
                    point_rows = [row for row in point["rows"] if all(self._matches(row, rule, point_metadata) for rule in definition["filters"])]
                    points.append({**point, "rows": point_rows})
                chart = build_timeline({**timeline, "points": points}, definition["chart"], context.get("identity_field_id") or "")
                timeline_panels.append({"label": timeline["label"], "chart": chart})
            payload["chart"] = {"layout": "separate", "source_row_count": len(rows), "panels": [
                {"label": "Original values and period comparisons", "chart": base_chart}, *timeline_panels,
            ]} if timeline_panels else base_chart
        return payload

    def preview(self, definition, context=None):
        normalized = self.normalize(definition, definition.get("id") if isinstance(definition, dict) else None)
        return self._render(normalized, context)

    def validate_context(self, widget_id, context=None):
        """Validate a placement without fetching data or changing the reusable Widget."""
        return self.validate_definition_context(self.get(widget_id), context)

    def validate_definition_context(self, definition, context=None):
        """Check a proposed definition against an existing consumer's context."""
        definition = self.normalize(definition)
        context = self._context(context)
        query_ids = list(dict.fromkeys(definition["field_ids"] + [rule["field_id"] for rule in definition["filters"]] + [rule["field_id"] for rule in context["ranking"]]))
        metadata = {field["id"]: field for field in self.fields.resolve(query_ids)}
        self.fields.validate_scope(query_ids, context.get("group_ids") or [])
        if context.get("identity_field_id"):
            eligible = {field["id"] for field in self.fields.identity_fields(query_ids)}
            if context["identity_field_id"] not in eligible:
                raise ValidationError("Choose a Report text or number Field from this selection to match rows across periods.")
        variants = normalize_field_variants(definition["field_ids"], context.get("field_variants"), self.fields)
        if any(not variant.get("interval") for variant in variants) and not context.get("identity_field_id"):
            compatibility = self.fields.compatibility(query_ids)
            if not compatibility.get("matching_rules"):
                raise ValidationError("Choose ‘Match rows using’ before comparing Field periods.")
            if not compatibility.get("compatible"):
                raise ValidationError(compatibility.get("message") or "Update the matching rule in Fields before comparing periods.")
        for variant in variants:
            if variant.get("interval") and definition["kind"] not in {"bar", "line"}:
                raise ValidationError("A timeline needs a Bar or Line Widget. Keep one-period comparisons in Tables and Pies.")
            if definition["kind"] != "table" and variant["field_id"] not in definition["chart"]["measure_field_ids"]:
                raise ValidationError("Choose a Field already measured by this chart for a custom period version.")
            if variant.get("interval") and variant.get("aggregation") == "none" and not context.get("identity_field_id"):
                raise ValidationError("Choose ‘Match rows using’ for individual timeline values.")
        if variants and definition["kind"] != "table":
            expanded, dependencies = self._placement_chart(definition, variants)
            expanded_metadata = dict(metadata)
            for variant in variants:
                expanded_metadata[variant["id"]] = {**metadata[variant["field_id"]], "id": variant["id"], "label": variant["label"]}
            for group in dependencies.values():
                for local_id, source_id in group.items():
                    expanded_metadata[local_id] = {**metadata[source_id], "id": local_id}
            validate_chart_meaning(definition["kind"], expanded, expanded_metadata)
        if "field_variants" in context or variants:
            context["field_variants"] = variants
        for rule in context["ranking"]:
            field = metadata[rule["field_id"]]
            if field.get("kind") == "table" or field.get("type") == "asset":
                raise ValidationError("Rank by a value Field, not a generated rank or asset.")
        return context

    def render(self, widget_id, context=None):
        return self._render(self.normalize(self.get(widget_id)), context)
