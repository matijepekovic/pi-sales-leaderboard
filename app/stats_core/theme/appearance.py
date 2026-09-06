"""Style contracts shared by Theme resources and Group appearance choices."""
from __future__ import annotations

from copy import deepcopy

STYLE_KEYS = {"colors", "corner_settings", "hero_scale", "row_stripe"}
WIDGET_STYLE_KEYS = {"colors", "font_family", "font_size", "header_font_size", "padding", "spacing", "row_height"}


def merge_style(base, overrides):
    result = deepcopy(base or {})
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_style(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def clean_widget_styles(raw, clean_colors):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("Widget styles must be keyed by Widget ID.")
    result = {}
    for widget_id, value in raw.items():
        if not isinstance(value, dict) or set(value) - WIDGET_STYLE_KEYS:
            raise ValueError("Group Widget refinements can contain visual settings only.")
        style = {}
        for key, item in value.items():
            if key == "colors":
                style[key] = clean_colors(item)
            elif key == "font_family":
                style[key] = str(item or "").strip()[:120]
            else:
                try:
                    number = float(item)
                except (TypeError, ValueError):
                    raise ValueError(f"{key.replace('_', ' ').title()} must be a number.") from None
                if not 0 <= number <= 300:
                    raise ValueError(f"{key.replace('_', ' ').title()} must be between 0 and 300.")
                style[key] = round(number, 2)
        if str(widget_id).strip():
            result[str(widget_id).strip()] = style
    return result
