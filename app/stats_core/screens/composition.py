"""Validated presentation geometry for normalized Widget instances."""
from __future__ import annotations

import math
import uuid

from stats_core.errors import ValidationError
from stats_core.services.data_periods import normalize_timeframe


def _object(raw, keys, name):
    raw = {} if raw is None else raw
    if not isinstance(raw, dict) or set(raw) - set(keys):
        raise ValidationError(f"Invalid {name} settings.")
    return raw


def _number(raw, default, low, high, label, integer=False):
    if raw is None:
        return default
    try:
        number = float(raw)
    except (ValueError, TypeError):
        raise ValidationError(f"{label} must be a number.")
    if isinstance(raw, bool) or not math.isfinite(number) or not low <= number <= high or (integer and not number.is_integer()):
        raise ValidationError(f"{label} must be {'a whole number ' if integer else ''}between {low} and {high}.")
    return int(number) if integer else round(number, 4)


def clean_canvas(raw):
    raw = _object(raw, {"width", "height"}, "canvas")
    return {key: _number(raw.get(key), default, 240, 16384, f"Canvas {key}", True)
            for key, default in (("width", 1920), ("height", 1080))}


def clean_layout(raw):
    raw = _object(raw, {"x", "y", "width", "height"}, "Widget position")
    result = {key: _number(raw.get(key), default, low, 100, f"Widget {key}")
              for key, default, low in (("x", 0, 0), ("y", 0, 0), ("width", 100, .1), ("height", 100, .1))}
    if result["x"] + result["width"] > 100.001 or result["y"] + result["height"] > 100.001:
        raise ValidationError("Keep the Widget within the Screen canvas.")
    return result


def clean_assets(raw, allowed_keys):
    """Validate placed Theme asset slots without resolving their artwork.

    None asks for inherited placement defaults; [] explicitly places no assets.
    Allowed slot keys come from the Theme owner's public contract.
    """
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) > 50:
        raise ValidationError("Choose at most 50 placed assets for this Screen.")
    allowed = set(allowed_keys) - {"background"}
    result, seen = [], set()
    for index, item in enumerate(raw):
        item = _object(item, {"id", "key", "x", "y", "width", "height", "fit"}, "asset placement")
        key = str(item.get("key") or "").strip()
        if key not in allowed:
            raise ValidationError("Choose a placeable Theme asset slot.")
        default_id = uuid.uuid5(uuid.NAMESPACE_URL, f"stats:screen-asset:{index}:{key}").hex
        asset_id = str(item.get("id") or f"asset-{default_id}").strip()
        if not asset_id or len(asset_id) > 120 or asset_id in seen:
            raise ValidationError("Each placed asset needs a unique identity of at most 120 characters.")
        fit = str(item.get("fit") or "contain")
        if fit not in {"contain", "cover"}:
            raise ValidationError("Choose Contain or Cover for asset sizing.")
        try:
            rectangle = clean_layout({name: item[name] for name in ("x", "y", "width", "height") if name in item})
        except ValidationError as exc:
            raise ValidationError(str(exc).replace("Widget", "Asset")) from None
        result.append({"id": asset_id, "key": key, **rectangle, "fit": fit})
        seen.add(asset_id)
    return result


def clean_fit(raw):
    raw = _object(raw, {"rows", "font_size", "padding", "row_height"}, "Widget fit")
    result = {"rows": _number(raw.get("rows"), 10, 1, 1000, "Visible rows", True)}
    for key, low, high in (("font_size", 1, 500), ("padding", 0, 500), ("row_height", 1, 2000)):
        if raw.get(key) is not None and raw.get(key) != "":
            result[key] = _number(raw[key], None, low, high, key.replace("_", " ").title())
    return result


def clean_timeframe(raw):
    if raw is None:
        return None
    return normalize_timeframe(raw)
