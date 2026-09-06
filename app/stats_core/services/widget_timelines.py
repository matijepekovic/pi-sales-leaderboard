"""Chart values over dated Field-placement observations, without data access."""
from __future__ import annotations

from stats_core.errors import ValidationError
from stats_core.services.widget_charts import (
    calculation_label, evaluate_measurement, measurement_format, measurement_settings,
)


def build_timeline(timeline, definition, identity_field_id=""):
    """Keep period summaries and explicitly matched individual histories distinct."""
    field_id = timeline["source_field_id"]
    points = timeline["points"]
    settings = {**measurement_settings(definition, field_id), "aggregation": timeline["aggregation"]}
    # This is an explicit aggregation of the Field itself, not a Widget's
    # separate numerator/denominator computation.
    settings = {"aggregation": settings["aggregation"]}
    field = timeline["field"]
    value_format = measurement_format(settings, field)
    chart = {"aggregation": settings["aggregation"], "aggregation_label": calculation_label(settings),
             "source_row_count": sum(len(point["rows"]) for point in points),
             "categories": [point["label"] for point in points], "series": [],
             "timeline": True, "timeframe": timeline["timeframe"], "interval": timeline["interval"],
             "periods": [{"start_date": point["start_date"], "end_date": point["end_date"]} for point in points],
             "point_details": points}
    if value_format["type"] == "percent":
        chart.update(percentage_scale="fraction", value_type="percent")

    def series(label, batches):
        values, row_indices = [], []
        for point, selected in zip(points, batches):
            metadata = {item["id"]: item for item in point["fields"]}
            values.append(evaluate_measurement(field_id, settings, selected, metadata))
            selected_objects = {id(row) for row in selected}
            row_indices.append([index for index, row in enumerate(point["rows"]) if id(row) in selected_objects])
        return {"field_id": timeline["field_id"], "source_field_id": field_id, "label": label,
                "values": [value["value"] for value in values], "sample_counts": [value["sample_count"] for value in values],
                "reasons": [value.get("reason", "") for value in values], "aggregation": settings["aggregation"],
                "aggregation_label": calculation_label(settings), "value_format": value_format, "row_indices": row_indices}

    if settings["aggregation"] != "none":
        chart["series"] = [series(timeline["label"], [point["rows"] for point in points])]
        return chart
    if not identity_field_id:
        raise ValidationError("Choose ‘Match rows using’ for individual timeline values.")
    records, missing_identity = {}, 0
    for point_index, point in enumerate(points):
        seen = set()
        for row_index, row in enumerate(point["rows"]):
            key = row.get("__row_key")
            if not key:
                # A blank key is an isolated real observation. Never connect it
                # to another period by index or silently discard its value.
                key = ("unmatched", point_index, row_index)
                missing_identity += 1
            elif key in seen:
                raise ValidationError("The timeline matching Field repeats in a period. Choose a unique Field.")
            seen.add(key)
            label = row.get(identity_field_id)
            label = str(label) if label is not None and str(label).strip() else "(Missing match value)"
            if key not in records:
                records[key] = {"label": label, "batches": [[] for _ in points]}
            records[key]["batches"][point_index] = [row]
    chart["series"] = [series(f"{timeline['label']} · {record['label']}", record["batches"]) for record in records.values()]
    if missing_identity:
        chart["notice"] = f"{missing_identity} observations have no matching value and remain separate points."
    return chart
