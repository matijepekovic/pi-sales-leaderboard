"""Tableau report discovery and trial pulls for the settings UI."""
from __future__ import annotations

import time

from sources import tableau_base as _base
from sources.tableau_configured import ConfiguredTableauSource, config_of
from sources.tableau_crosstab import describe_crosstab, mapping_description
from sources.tableau_mapped import describe_report, suggest_mapping, unmapped_columns

DATE_KEYS = ("data_date_mode", "data_date_start", "data_date_end")
_FILTER_VALUE_LIMIT = 1000
_FILTER_ROW_LIMIT = 5000


def source_config(settings):
    return config_of(settings or {})


def _signed_in(settings):
    source = ConfiguredTableauSource(settings, source_config(settings))
    base, token, site_id = source.signin()
    return source, base, token, site_id


def _books(payload):
    if not isinstance(payload, dict):
        return []
    books = payload.get("workbooks", {}).get("workbook", [])
    if isinstance(books, dict):
        return [books]
    return books if isinstance(books, list) else []


def list_workbooks(settings):
    """Return workbooks visible to the configured Tableau token."""
    source, base, token, site_id = _signed_in(settings)
    try:
        status, raw = source._request(
            f"{base}/sites/{site_id}/workbooks?pageSize=1000", token=token
        )
        books = _books(_base.json.loads(raw)) if status == 200 else []

        if not books:
            status, raw = source._request(
                f"{base}/sites/{site_id}/users?pageSize=1000", token=token
            )
            users = []
            if status == 200:
                users = _base.json.loads(raw).get("users", {}).get("user", [])
                if isinstance(users, dict):
                    users = [users]
            for user in users[:1]:
                uid = str(user.get("id") or "").strip()
                if not uid:
                    continue
                status, raw = source._request(
                    f"{base}/sites/{site_id}/users/{uid}/workbooks?pageSize=1000",
                    token=token,
                )
                if status == 200:
                    books = _books(_base.json.loads(raw))

        rows = [
            {
                "name": str(book.get("name") or "").strip(),
                "content_url": str(book.get("contentUrl") or "").strip(),
            }
            for book in books
        ]
        rows = [row for row in rows if row["content_url"]]
        rows.sort(key=lambda row: row["name"].lower())
        return rows
    finally:
        source.signout(base, token)


def list_all_views(settings):
    """Return every published view visible to the configured token."""
    source, base, token, site_id = _signed_in(settings)
    try:
        rows = []
        status, raw = source._request(
            f"{base}/sites/{site_id}/views?pageSize=1000", token=token
        )
        if status == 200:
            for view in source._view_list(_base.json.loads(raw)):
                content_url = str(view.get("contentUrl") or "").strip()
                if not content_url:
                    continue
                parts = content_url.split("/")
                rows.append(
                    {
                        "workbook": parts[0],
                        "sheet": parts[-1],
                        "name": str(view.get("name") or parts[-1]).strip(),
                        "content_url": content_url,
                    }
                )
    finally:
        source.signout(base, token)

    if not rows:
        for book in list_workbooks(settings):
            try:
                for view in list_views(settings, book["content_url"]):
                    rows.append(
                        {
                            "workbook": book["content_url"],
                            "sheet": str(view["content_url"]).split("/")[-1],
                            "name": view["name"],
                            "content_url": view["content_url"],
                        }
                    )
            except _base.TableauError:
                continue

    rows.sort(key=lambda row: (row["workbook"].lower(), row["name"].lower()))
    return rows


def list_views(settings, workbook):
    """Return published views for one workbook."""
    workbook = str(workbook or "").strip()
    if not workbook:
        raise _base.TableauError("Choose a workbook first.")

    source, base, token, site_id = _signed_in(settings)
    try:
        key = _base.urllib.parse.quote(workbook, safe="")
        status, raw = source._request(
            f"{base}/sites/{site_id}/workbooks/{key}?key=contentUrl", token=token
        )
        if status != 200:
            raise _base.TableauError(
                f"Could not open workbook '{workbook}' (HTTP {status})."
            )
        workbook_id = str(
            _base.json.loads(raw).get("workbook", {}).get("id") or ""
        ).strip()

        status, raw = source._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_id}/views", token=token
        )
        if status != 200:
            raise _base.TableauError(f"Could not list sheets for '{workbook}'.")
        views = source._view_list(_base.json.loads(raw))
        return [
            {
                "name": str(view.get("name") or "").strip(),
                "content_url": str(view.get("contentUrl") or "").strip(),
            }
            for view in views
            if str(view.get("contentUrl") or "").strip()
        ]
    finally:
        source.signout(base, token)


def trial_settings(settings, overrides=None):
    trial = dict(settings or {})
    for key in DATE_KEYS:
        value = (overrides or {}).get(key)
        if value is not None:
            trial[key] = value
    return trial


def trial_config(settings, overrides=None):
    config = dict(source_config(settings))
    for key, value in (overrides or {}).items():
        if key in config and value is not None:
            config[key] = value
    return config


def preview_pull(settings, overrides=None):
    """Run a candidate source configuration without saving anything."""
    source = ConfiguredTableauSource(
        trial_settings(settings, overrides), trial_config(settings, overrides)
    )
    began = time.monotonic()
    start, end, rows = source._pull_rows()
    notes = dict(
        source.last_notes or {},
        seconds=round(time.monotonic() - began, 1),
        remote_rows=source.last_remote_rows,
    )
    return start, end, rows, notes


def test_source(settings, overrides=None):
    start, end, rows, notes = preview_pull(settings, overrides)
    config = trial_config(settings, overrides)
    branch_column = str(
        (config.get("row_filter") or {}).get("column") or "home_branch"
    )
    return {
        "workbook": config["workbook"],
        "sheet": config["sheet"],
        "start": start,
        "end": end,
        "reps": len(rows),
        "offices": sorted(
            {
                str(row.get(branch_column) or "").strip()
                for row in rows
                if str(row.get(branch_column) or "").strip()
            }
        ),
        "metrics": sorted(
            {
                key
                for row in rows
                for key, value in row.items()
                if isinstance(value, (int, float)) and value
            }
        ),
        "sample": [str(row.get("rep_name") or "") for row in rows[:3]],
        "notes": notes,
    }


def _filter_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def report_filter_catalog(payload, how):
    """Return real fields and values from the selected report export."""
    if how == "crosstab":
        described = describe_crosstab(payload)
        headers = list(described.get("headers") or [])
        rows = list(described.get("rows") or [])[:_FILTER_ROW_LIMIT]
    else:
        reader = _base.csv.DictReader(_base.io.StringIO(str(payload or "")))
        headers = [
            str(header or "").strip()
            for header in (reader.fieldnames or [])
            if str(header or "").strip()
        ]
        rows = []
        for index, row in enumerate(reader):
            if index >= _FILTER_ROW_LIMIT:
                break
            rows.append(row)

    catalog = []
    for header in headers:
        values, seen = [], set()
        truncated = False
        for row in rows:
            text = _filter_text(row.get(header))
            if not text or text.casefold() == "all":
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            if len(values) < _FILTER_VALUE_LIMIT:
                values.append(text)
            else:
                truncated = True
        values.sort(key=str.casefold)
        catalog.append(
            {"field": header, "values": values, "truncated": truncated}
        )
    return catalog


def read_columns(settings, overrides=None):
    """Describe columns and mappings offered by a candidate report."""
    config = trial_config(settings, overrides)
    trial = trial_settings(settings, overrides)
    discovery = dict(config)
    discovery["filters"] = []
    discovery["row_filter"] = {}
    source = ConfiguredTableauSource(trial, discovery)
    start, end = _base.resolve_dates(trial)
    base, token, site_id = source.signin()
    try:
        payload, how, csv_error = source.read_export(
            base, token, site_id, start, end
        )
    finally:
        source.signout(base, token)

    if how == "csv":
        described = describe_report(payload)
        guess = suggest_mapping(described["headers"], described["choices"])
        described = {
            "shape": described["shape"],
            "headers": described["headers"],
            "choices": described["choices"],
            "samples": described.get("samples") or {},
            "suggested": guess,
            "unmapped": unmapped_columns(described["choices"], guess),
            "export": "view data (CSV)",
        }
    else:
        described = mapping_description(payload)
        described["export"] = "Crosstab Excel"
        if csv_error:
            described["csv_error"] = csv_error

    return {
        **described,
        "start": start,
        "end": end,
        "filter_fields": report_filter_catalog(payload, how),
    }
