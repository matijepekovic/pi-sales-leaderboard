"""Source-neutral effective date windows requested by Screens and Widgets."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from stats_core.errors import ValidationError


_UNITS = {"day", "week", "month", "year"}


def _count(value, label, maximum):
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a whole number between 1 and {maximum}.")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 0
    if str(parsed) != str(value) or not 1 <= parsed <= maximum:
        raise ValidationError(f"{label} must be a whole number between 1 and {maximum}.")
    return parsed


def _shift(value, unit, count):
    if unit in {"day", "week"}:
        return value + timedelta(days=count * (7 if unit == "week" else 1))
    month = value.year * 12 + value.month - 1 + count * (12 if unit == "year" else 1)
    year, month = divmod(month, 12)
    if not 1 <= year <= 9999:
        raise ValidationError("The requested timeframe is outside the supported calendar.")
    return value.replace(year=year, month=month + 1, day=min(value.day, calendar.monthrange(year, month + 1)[1]))


def normalize_interval(raw):
    """A timeline's real query cadence, independent of display freshness."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"unit", "count"}:
        raise ValidationError("Choose a valid timeline interval.")
    unit = str(raw.get("unit") or "")
    if unit not in _UNITS:
        raise ValidationError("Timeline intervals use days, weeks, months, or years.")
    return {"unit": unit, "count": _count(raw.get("count", 1), "Interval", 366)}


def normalize_timeframe(timeframe):
    start, end = resolve_timeframe(timeframe)
    result = {"preset": timeframe["preset"]}
    if timeframe["preset"] == "custom":
        result.update(start_date=start, end_date=end)
    if timeframe["preset"] == "rolling":
        result.update(unit=timeframe["unit"], count=int(timeframe["count"]))
        if timeframe.get("offset"):
            result["offset"] = int(timeframe["offset"])
    return result


def resolve_timeframe(timeframe, today=None):
    """Validate a request before any adapter runs, returning inclusive dates."""
    if not isinstance(timeframe, dict):
        raise ValidationError("Choose a valid timeframe.")
    unexpected = set(timeframe) - {"preset", "start_date", "end_date", "unit", "count", "offset"}
    if unexpected:
        raise ValidationError(f"Unknown timeframe setting '{sorted(unexpected)[0]}'.")
    preset = str(timeframe.get("preset") or "").strip()
    today = today or date.today()
    if preset != "rolling" and set(timeframe).intersection({"unit", "count", "offset"}):
        raise ValidationError("Rolling-window settings only apply to a rolling timeframe.")
    if preset != "custom" and set(timeframe).intersection({"start_date", "end_date"}):
        raise ValidationError("Start and end dates only apply to a custom timeframe.")
    if preset in {"today", "yesterday"}:
        day = today - timedelta(days=1 if preset == "yesterday" else 0)
        return day.isoformat(), day.isoformat()
    if preset in {"current_week", "previous_week", "week_to_date"}:
        start = today - timedelta(days=today.weekday() + (7 if preset == "previous_week" else 0))
        end = today if preset == "week_to_date" else start + timedelta(days=6)
        return start.isoformat(), end.isoformat()
    if preset == "current_month":
        return today.replace(day=1).isoformat(), today.replace(day=calendar.monthrange(today.year, today.month)[1]).isoformat()
    if preset == "month_to_date":
        return today.replace(day=1).isoformat(), today.isoformat()
    if preset == "previous_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1).isoformat(), end.isoformat()
    if preset in {"current_quarter", "previous_quarter"}:
        start = today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1)
        if preset == "previous_quarter":
            start = _shift(start, "month", -3)
        return start.isoformat(), (_shift(start, "month", 3) - timedelta(days=1)).isoformat()
    if preset == "year_to_date":
        return today.replace(month=1, day=1).isoformat(), today.isoformat()
    if preset == "previous_year":
        return date(today.year - 1, 1, 1).isoformat(), date(today.year - 1, 12, 31).isoformat()
    if preset == "rolling":
        unit = str(timeframe.get("unit") or "")
        if unit not in _UNITS:
            raise ValidationError("Rolling windows use days, weeks, months, or years.")
        count = _count(timeframe.get("count"), "Rolling window", 3660 if unit == "day" else 520 if unit == "week" else 120 if unit == "month" else 10)
        raw_offset = timeframe.get("offset", 0)
        offset = 0 if raw_offset == 0 and not isinstance(raw_offset, bool) else _count(raw_offset, "Window offset", 3660 if unit == "day" else 520 if unit == "week" else 120 if unit == "month" else 10)
        end = _shift(today, unit, -offset)
        return (_shift(end, unit, -count) + timedelta(days=1)).isoformat(), end.isoformat()
    if preset != "custom":
        raise ValidationError("Choose a standard, rolling, or custom timeframe.")
    try:
        start = date.fromisoformat(str(timeframe.get("start_date") or ""))
        end = date.fromisoformat(str(timeframe.get("end_date") or ""))
    except ValueError as exc:
        raise ValidationError("Custom timeframe needs valid start and end dates.") from exc
    if start > end:
        raise ValidationError("The timeframe start date must be on or before its end date.")
    return start.isoformat(), end.isoformat()


def timeframe_intervals(timeframe, interval, today=None, maximum=120):
    """Partition an inclusive request into ordered, non-overlapping real pulls.

    Calendar weeks start Monday. Partial first/last bins retain exact requested
    dates. Future dates are excluded from timelines rather than invented as 0.
    """
    today = today or date.today()
    start, end = (date.fromisoformat(value) for value in resolve_timeframe(timeframe, today))
    end = min(end, today)
    interval = normalize_interval(interval)
    if interval is None:
        raise ValidationError("Choose the interval between timeline points.")
    unit, count = interval["unit"], interval["count"]
    if start > end:
        raise ValidationError("A timeline needs dates on or before today.")
    anchor = start
    if unit == "week":
        anchor -= timedelta(days=anchor.weekday())
    elif unit == "month":
        anchor = anchor.replace(day=1)
    elif unit == "year":
        anchor = anchor.replace(month=1, day=1)
    bins = []
    while start <= end:
        next_start = _shift(anchor, unit, count)
        stop = min(end, next_start - timedelta(days=1))
        label = start.isoformat() if start == stop else f"{start.isoformat()} – {stop.isoformat()}"
        bins.append({"start_date": start.isoformat(), "end_date": stop.isoformat(), "label": label})
        if len(bins) > maximum:
            raise ValidationError(f"This timeline needs more than {maximum} points. Choose a wider interval or shorter range.")
        start = next_start
        anchor = next_start
    return bins
