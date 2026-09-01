"""Read a Tableau report as a vendor-neutral table contract."""
from __future__ import annotations

from sources import tableau_base as _base
from sources import discovery
from sources.tableau_configured import ConfiguredTableauSource
from sources.tableau_crosstab import describe_crosstab

_MAX_ROWS = 5000


def _number(value):
    text = str(value or "").strip().replace(",", "").replace("$", "").replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _field_type(values):
    present = [value for value in values if str(value or "").strip()]
    if not present:
        return "text"
    numeric = [_number(value) for value in present[:100]]
    if all(value is not None for value in numeric):
        texts = [str(value) for value in present[:100]]
        if any("%" in value for value in texts):
            return "percent"
        if any("$" in value for value in texts):
            return "currency"
        return "number"
    return "text"


def _normalize_rows(headers, rows):
    normalized = []
    for row in rows[:_MAX_ROWS]:
        clean = {}
        for header in headers:
            value = row.get(header)
            typ = None
            clean[header] = "" if value is None else value
        normalized.append(clean)
    return normalized


def read_table(settings, overrides=None):
    """Return fields/rows without imposing Stats leaderboard mappings."""
    trial = discovery.trial_settings(settings, overrides)
    config = discovery.trial_config(settings, overrides)
    source = ConfiguredTableauSource(trial, config)
    start, end = _base.resolve_dates(trial)
    base, token, site_id = source.signin()
    try:
        payload, how, csv_error = source.read_export(base, token, site_id, start, end)
    finally:
        source.signout(base, token)

    if how == "csv":
        reader = _base.csv.DictReader(_base.io.StringIO(str(payload or "")))
        headers = [str(value or "").strip() for value in (reader.fieldnames or []) if str(value or "").strip()]
        rows = []
        for index, row in enumerate(reader):
            if index >= _MAX_ROWS:
                break
            rows.append({header: row.get(header) for header in headers})
        export = "csv"
    else:
        described = describe_crosstab(payload)
        headers = [str(value or "").strip() for value in (described.get("headers") or []) if str(value or "").strip()]
        rows = [dict(row) for row in (described.get("rows") or [])[:_MAX_ROWS] if isinstance(row, dict)]
        export = "crosstab"

    rows = _normalize_rows(headers, rows)
    fields = [
        {
            "key": header,
            "label": header,
            "type": _field_type([row.get(header) for row in rows]),
        }
        for header in headers
    ]
    return {
        "fields": fields,
        "rows": rows,
        "start": start,
        "end": end,
        "export": export,
        "csv_error": str(csv_error or ""),
        "truncated": len(rows) >= _MAX_ROWS,
    }
