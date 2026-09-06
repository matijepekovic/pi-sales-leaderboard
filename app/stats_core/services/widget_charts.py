"""Source-independent measurement meaning and evaluated chart contracts.

Values are evaluated once here. Renderers receive units and contributing rows;
changing a visual never chooses a new calculation.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from stats_core.errors import ValidationError


PIE_MODES = {"auto", "percentage", "composition"}
AGGREGATIONS = {"none", "sum", "average", "count", "ratio"}
RATIO_MODES = {"totals", "row_average", "individual"}
CATEGORY_ORDERS = {"source", "number", "date"}
AGGREGATION_LABELS = {
    "none": "Individual row values",
    "sum": "Sum of row values",
    "average": "Average of row values (each row counts equally)",
    "count": "Count of values",
    "ratio": "Ratio of totals",
}


def numeric_value(value, *, percentage=False, percentage_scale="auto", strict=False):
    """Parse Field units. Blank numeric cells count as zero; invalid is not zero."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text:
        return 0.0
    explicit_percentage = text.endswith("%")
    try:
        number = float(text[:-1]) / 100 if explicit_percentage else float(text)
    except (TypeError, ValueError, OverflowError):
        if strict:
            raise ValidationError("A numeric Field contains text that cannot be used in a calculation.") from None
        return None
    if not math.isfinite(number):
        if strict:
            raise ValidationError("Chart values must be finite numbers; a selected Field contains a non-finite value.")
        return None
    if percentage and not explicit_percentage and (percentage_scale == "points" or (percentage_scale == "auto" and abs(number) > 1)):
        number /= 100
    return number


def measurement_settings(definition, field_id):
    """The per-value choice takes priority; legacy definitions keep their meaning."""
    settings = {key: definition[key] for key in ("aggregation", "denominator_field_id", "result_type", "ratio_mode") if key in definition}
    settings.update(definition.get("measure_settings", {}).get(field_id, {}))
    settings.setdefault("aggregation", "none")
    if settings["aggregation"] == "ratio":
        settings.setdefault("ratio_mode", "totals")
        settings.setdefault("result_type", "percent")
    return settings


def measurement_format(settings, field):
    if settings["aggregation"] == "count":
        return {"type": "number", "decimals": 0}
    if settings["aggregation"] == "ratio":
        value_type = settings.get("result_type", "percent")
        return {"type": value_type, "decimals": 1 if value_type == "percent" else field.get("decimals", 2)}
    return {"type": field.get("type", "number"), "decimals": field.get("decimals", 1 if field.get("type") == "percent" else 2)}


def _individual(settings):
    return settings["aggregation"] == "none" or (settings["aggregation"] == "ratio" and settings.get("ratio_mode") == "individual")


def calculation_label(settings):
    if settings["aggregation"] == "ratio":
        return {"totals": "Ratio of totals", "row_average": "Average of individual row ratios", "individual": "Individual row ratios"}[settings.get("ratio_mode", "totals")]
    return AGGREGATION_LABELS[settings["aggregation"]]


def validate_chart_meaning(kind, definition, metadata):
    order = definition.get("category_order", "source")
    if order not in CATEGORY_ORDERS:
        raise ValidationError("Choose table order, numeric order, or date order.")
    if order != "source" and not definition.get("dimension_field_id"):
        raise ValidationError("Choose a label Field to order chart values.")
    measures = definition["measure_field_ids"]
    settings = [measurement_settings(definition, field_id) for field_id in measures]
    formats = []
    for field_id, item in zip(measures, settings):
        field = metadata[field_id]
        aggregation = item["aggregation"]
        if aggregation not in AGGREGATIONS:
            raise ValidationError("Choose a valid calculation for each value.")
        if aggregation == "ratio":
            if field.get("type") != "number" or metadata.get(item.get("denominator_field_id"), {}).get("type") != "number":
                raise ValidationError("Ratio of totals needs one numeric numerator and one numeric denominator Field. Use underlying numbers, not percentage Fields.")
            if item.get("ratio_mode", "totals") not in RATIO_MODES or item.get("result_type", "percent") not in {"number", "percent"}:
                raise ValidationError("Choose how to calculate and display the ratio.")
        elif aggregation != "count" and field.get("type") not in {"number", "percent"}:
            raise ValidationError("Choose numeric Fields for values, or Count for text.")
        if aggregation == "sum" and field.get("type") == "percent":
            raise ValidationError("Percentages cannot be summed. Choose Average, or calculate a ratio from the underlying numbers.")
        formats.append(measurement_format(item, field))
    if not measures:
        raise ValidationError("Choose a value to visualize.")
    separate = definition.get("layout", "shared") == "separate"
    if definition.get("layout", "shared") not in {"shared", "separate"}:
        raise ValidationError("Choose a shared scale or separate panels.")
    if not separate and len({item["type"] for item in formats}) > 1:
        raise ValidationError("Numbers and percentages cannot share one chart scale. Choose separate panels.")
    if not separate and len({_individual(item) for item in settings}) > 1:
        raise ValidationError("Individual rows and combined results need separate panels.")
    if kind != "pie":
        return None
    mode = definition.get("pie_mode", "auto")
    if mode not in PIE_MODES:
        raise ValidationError("Choose Percentage or Composition for the Pie chart.")
    if mode == "auto":
        mode = "percentage" if all(item["type"] == "percent" for item in formats) else "composition"
    if mode == "percentage" and any(item["type"] != "percent" for item in formats):
        raise ValidationError("A Percentage pie needs a percentage value. A numeric ratio can remain a number in a Bar, Line, or Table.")
    if mode == "composition" and any(item["type"] == "percent" for item in formats):
        raise ValidationError("A Composition pie compares parts of one total, not independent percentage rates. Use Percentage circles or Bars.")
    if mode == "composition" and not separate and len(measures) > 1 and (definition.get("dimension_field_id") or any(_individual(item) for item in settings)):
        raise ValidationError("These values need separate pie panels or a Bar chart; they cannot be flattened into one total.")
    return mode


def _total(values):
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError):
        raise ValidationError("Chart aggregation exceeds the supported numeric range.") from None
    if not math.isfinite(result):
        raise ValidationError("Chart aggregation exceeds the supported numeric range.")
    return result


def _cell(row, field_id, metadata):
    if field_id in (row.get("__invalid_fields") or []):
        return None
    field = metadata[field_id]
    # Calculated None is an unavailable expression, not a numeric source blank.
    if row.get(field_id) is None and field.get("kind") == "calculated":
        return None
    return numeric_value(row.get(field_id), percentage=field.get("type") == "percent", percentage_scale=field.get("percent_input_scale", "auto"), strict=True)


def evaluate_measurement(field_id, settings, selected, metadata):
    """Compute one value over selected rows, with inspection evidence."""
    aggregation = settings["aggregation"]
    unavailable = {"value": None, "sample_count": 0}
    if not selected:
        return {**unavailable, "numerator": None, "denominator": None} if aggregation == "ratio" else unavailable
    if aggregation == "count":
        numeric = metadata[field_id].get("type") in {"number", "percent"}
        count = sum((_cell(row, field_id, metadata) is not None) if numeric else bool(str(row.get(field_id) if row.get(field_id) is not None else "").strip()) for row in selected)
        return {"value": count, "sample_count": count}
    values = [_cell(row, field_id, metadata) for row in selected]
    if aggregation == "ratio":
        bases = [_cell(row, settings["denominator_field_id"], metadata) for row in selected]
        if any(value is None for value in values + bases):
            return {**unavailable, "numerator": None, "denominator": None, "reason": "A selected calculation is unavailable."}
        a, b = _total(values), _total(bases)
        mode = settings.get("ratio_mode", "totals")
        if mode == "totals":
            result = a / b if b else None
        elif mode == "individual":
            if len(selected) != 1:
                raise ValidationError("Individual ratios must preserve individual rows.")
            result = values[0] / bases[0] if bases[0] else None
        else:
            result = _total(value / base / len(values) for value, base in zip(values, bases)) if all(bases) else None
        if result is not None and not math.isfinite(result):
            raise ValidationError("Chart aggregation exceeds the supported numeric range.")
        return {"value": result, "sample_count": len(selected), "numerator": a, "denominator": b,
                **({"reason": "Cannot divide by zero."} if result is None else {})}
    if any(value is None for value in values):
        return {**unavailable, "reason": "A selected calculation is unavailable."}
    if aggregation == "none":
        if len(values) != 1:
            raise ValidationError("Individual values must preserve individual rows.")
        result = values[0]
    else:
        result = _total(value / len(values) for value in values) if aggregation == "average" else _total(values)
    return {"value": result, "sample_count": len(values)}


def _series(field_id, label, settings, values, field):
    result = {"field_id": field_id, "label": label, "values": [item["value"] for item in values],
              "sample_counts": [item["sample_count"] for item in values],
              "aggregation": settings["aggregation"], "aggregation_label": calculation_label(settings),
              "value_format": measurement_format(settings, field),
              "reasons": [item.get("reason", "") for item in values]}
    if settings["aggregation"] == "ratio":
        result.update({"numerators": [item.get("numerator") for item in values],
                       "denominators": [item.get("denominator") for item in values],
                       "ratio_mode": settings.get("ratio_mode", "totals"), "denominator_field_id": settings["denominator_field_id"]})
    return result


def _category_label(value):
    return str(value) if value not in (None, "") else "(Empty)"


def _ordered_buckets(buckets, dimension, order, metadata):
    """Sort the evaluated categories, retaining their original row evidence.

    Dates must be unambiguous ISO values. Never guess locale or infer a timeline
    from labels such as month names, nor change the order of the source table.
    """
    if order == "source":
        return buckets

    def key(bucket):
        row = bucket[1][0]
        value = row.get(dimension)
        if dimension in (row.get("__invalid_fields") or []) or value is None or not str(value).strip():
            raise ValidationError("The order Field has missing values. Choose a complete order Field or table order.")
        if order == "number":
            result = _cell(row, dimension, metadata)
            if result is None:
                raise ValidationError("Numeric order needs a number in every row of the order Field.")
            return result
        text = str(value).strip()
        try:
            # fromisoformat accepts compact dates too; require an explicit date.
            if len(text) < 10 or text[4] != "-" or text[7] != "-":
                raise ValueError
            date = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return (date if date.tzinfo else date.replace(tzinfo=timezone.utc)).timestamp()
        except (ValueError, OverflowError, OSError):
            raise ValidationError("Date order needs YYYY-MM-DD dates (optionally with an ISO time). Ambiguous dates are not guessed.") from None

    return sorted(buckets, key=key)


def build_chart(kind, definition, rows, metadata):
    """Render-independent values, optional panels, and measurement units."""
    mode = validate_chart_meaning(kind, definition, metadata)
    measures = definition["measure_field_ids"]
    settings = {field_id: measurement_settings(definition, field_id) for field_id in measures}
    if len(measures) > 1 and (definition.get("layout") == "separate" or mode == "percentage"):
        return {"layout": "separate", "source_row_count": len(rows), "panels": [
            {"label": metadata[field_id]["label"], "chart": build_chart(kind, {**definition, "measure_field_ids": [field_id], "layout": "shared"}, rows, metadata)}
            for field_id in measures]}
    dimension = definition.get("dimension_field_id", "")
    individual = _individual(settings[measures[0]])
    labels = {field_id: (f"{metadata[field_id]['label']} / {metadata[settings[field_id]['denominator_field_id']]['label']}" if settings[field_id]["aggregation"] == "ratio" else metadata[field_id]["label"]) for field_id in measures}
    calculation_names = list(dict.fromkeys(calculation_label(settings[field_id]) for field_id in measures))
    aggregation_names = {settings[field_id]["aggregation"] for field_id in measures}
    chart = {"aggregation": next(iter(aggregation_names)) if len(aggregation_names) == 1 else "mixed",
             "aggregation_label": calculation_names[0] if len(calculation_names) == 1 else "Each value uses its selected calculation",
             "source_row_count": len(rows), "measure_settings": settings}
    formats = [measurement_format(settings[field_id], metadata[field_id]) for field_id in measures]
    if all(item["type"] == "percent" for item in formats):
        chart["percentage_scale"] = "fraction"
        chart["value_type"] = "percent"
    if len(measures) == 1 and settings[measures[0]]["aggregation"] == "ratio":
        chart.update({"value_type": formats[0]["type"], "numerator_field_id": measures[0],
                      "denominator_field_id": settings[measures[0]]["denominator_field_id"],
                      "ratio_mode": settings[measures[0]].get("ratio_mode", "totals")})
    if not dimension and not individual:
        results = [evaluate_measurement(field_id, settings[field_id], rows, metadata) for field_id in measures]
        first = _series("", chart["aggregation_label"], settings[measures[0]], results, metadata[measures[0]])
        first["value_formats"] = formats
        first["value_settings"] = [settings[field_id] for field_id in measures]
        first["row_indices"] = [list(range(len(rows))) for _ in measures]
        if any(item["aggregation"] == "ratio" for item in settings.values()):
            first.update({"numerators": [item.get("numerator") for item in results], "denominators": [item.get("denominator") for item in results]})
        chart.update({"categories": [labels[field_id] for field_id in measures], "value_field_ids": list(measures), "series": [first]})
    else:
        buckets = []
        if individual:
            buckets = [(_category_label(row.get(dimension)) if dimension else f"Row {index + 1}", [row], [index])
                       for index, row in enumerate(rows)]
        else:
            grouped = {}
            for index, row in enumerate(rows):
                key = _category_label(row.get(dimension))
                if key not in grouped:
                    grouped[key] = ([], [])
                grouped[key][0].append(row)
                grouped[key][1].append(index)
            buckets = [(key, data, indices) for key, (data, indices) in grouped.items()]
        buckets = _ordered_buckets(buckets, dimension, definition.get("category_order", "source"), metadata)
        chart["category_order"] = definition.get("category_order", "source")
        chart["categories"] = [key for key, _, _ in buckets]
        chart["series"] = []
        for field_id in measures:
            item = _series(field_id, labels[field_id], settings[field_id], [evaluate_measurement(field_id, settings[field_id], data, metadata) for _, data, _ in buckets], metadata[field_id])
            item["row_indices"] = [indices for _, _, indices in buckets]
            chart["series"].append(item)
    if mode == "composition":
        if any(value is not None and value < 0 for item in chart["series"] for value in item["values"]):
            raise ValidationError("Pie charts require non-negative values. Use a Bar or Line chart for negative values.")
        if any(_cell(row, field_id, metadata) is not None and _cell(row, field_id, metadata) < 0 for row in rows for field_id in measures if settings[field_id]["aggregation"] != "count"):
            raise ValidationError("Pie charts require non-negative values. Use a Bar or Line chart for negative values.")
    if mode == "percentage":
        for field_id in measures:
            if settings[field_id]["aggregation"] != "ratio" and any(value is not None and not 0 <= value <= 1 for value in [_cell(row, field_id, metadata) for row in rows]):
                raise ValidationError("A Percentage pie must be between 0% and 100%. Use Bar or Line for values outside that range.")
        series = chart["series"][0]
        if any(value is not None and not 0 <= value <= 1 for value in series["values"]):
            raise ValidationError("A Percentage pie must be between 0% and 100%. Use Bar or Line for values outside that range.")
        if len(series["values"]) > 1:
            panels = []
            for index, value in enumerate(series["values"]):
                single = {**series, **{key: [series[key][index]] for key in ("values", "sample_counts", "reasons", "numerators", "denominators", "row_indices", "value_formats", "value_settings") if key in series}}
                panels.append({"label": chart["categories"][index], "chart": {**chart, "categories": [chart["categories"][index]], "series": [single], "pie_mode": mode, "fraction": value}})
            return {"layout": "separate", "source_row_count": len(rows), "panels": panels}
        chart["fraction"] = series["values"][0] if series["values"] else None
    if mode:
        chart["pie_mode"] = mode
    return chart
