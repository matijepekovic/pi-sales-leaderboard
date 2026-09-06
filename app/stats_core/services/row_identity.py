"""Stable identity helpers for normalized table rows."""
from __future__ import annotations


def _name(field):
    return (
        str(field.get("label") or field.get("key") or "")
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )


def _value(value):
    return "" if value is None else str(value).strip().casefold()


def is_unique(fields, rows, field_key):
    if field_key not in {str(field.get("key") or "") for field in fields}:
        return False
    values = [_value(row.get(field_key)) for row in rows]
    return bool(values) and all(values) and len(set(values)) == len(values)


def infer_label_field(fields):
    fields = [dict(field) for field in fields if isinstance(field, dict)]
    if not fields:
        return ""
    ranked = sorted(fields, key=lambda field: (
        0 if _name(field) == "name" else
        1 if _name(field) in {"sr name", "sales rep", "rep name"} else
        2 if "name" in _name(field) else
        3 if str(field.get("type") or "").lower() == "text" else 10
    ))
    return str(ranked[0].get("key") or "")


def infer_identity_field(fields, rows, preferred=""):
    fields = [dict(field) for field in fields if isinstance(field, dict)]
    preferred = str(preferred or "")
    if preferred and is_unique(fields, rows, preferred):
        return preferred
    label_key = infer_label_field(fields)
    id_fields = sorted(fields, key=lambda field: (
        0 if _name(field) in {"id", "rep id", "user id", "employee id"} else
        1 if _name(field).endswith(" id") else
        2 if "id" in _name(field).split() else 10
    ))
    identity = next(
        (
            str(field.get("key") or "")
            for field in id_fields
            if "id" in _name(field).split()
            and is_unique(fields, rows, str(field.get("key") or ""))
        ),
        "",
    )
    if identity:
        return identity
    if label_key and is_unique(fields, rows, label_key):
        return label_key
    return next(
        (
            str(field.get("key") or "")
            for field in fields
            if str(field.get("type") or "").lower() == "text"
            and is_unique(fields, rows, str(field.get("key") or ""))
        ),
        "",
    )
