"""The board's data source: one configuration, one code path.

  resolve_source(settings) - the factory. Always the same class, always
  described by the saved `source` object. With nothing saved that object is
  the seeded default, which is the Olympia Rep Totals pull the board has
  always made -- same request, same parser, same numbers.

  list_workbooks / list_views / read_columns - discovery for the settings
  page, reusing the source's own sign-in and request helpers rather than
  adding any HTTP code.
"""
from sources import tableau_base as _base
from sources.tableau import TableauSource
from sources.tableau_configured import (ConfiguredTableauSource, DEFAULTS,
                                        config_of, has_columns)
from sources.tableau_crosstab import describe_crosstab, mapping_description
from sources.tableau_mapped import describe_report, suggest_mapping, unmapped_columns


def source_config(settings):
    """The configuration the board pulls with.

    Pre-v90 installs stored a picked report in tableau_workbook /
    tableau_sheet. Those are deliberately ignored now: the reports they point
    at were picked while the picker was still guessing at exports, and the
    shipped default is a report that has been measured against the live site.
    Anything saved through the Data Source card lands in `source` and still
    wins.
    """
    return config_of(settings or {})


def resolve_source(settings):
    """The rep source to pull with. One class, described by settings."""
    return ConfiguredTableauSource(settings, source_config(settings))


def describe(settings):
    config = source_config(settings)
    return {
        "workbook": config["workbook"],
        "sheet": config["sheet"].rsplit("/", 1)[-1],
        "is_default": config == config_of({}),
        "default_workbook": DEFAULTS["workbook"],
        "default_sheet": DEFAULTS["sheet"],
        "server": config["server"],
        "site": config["site"],
        "pat_name": config["pat_name"],
        "filters": config["filters"],
        "date_start_field": config["date_start_field"],
        "date_end_field": config["date_end_field"],
        "row_filter": config["row_filter"],
        "mapping": config["mapping"],
        "export": config["export"],
        "defaults": DEFAULTS,
    }


# ------------------------------------------------------------------ discovery

def _signed_in(settings, source=None):
    """Signed in with the configured connection, not a compiled-in one."""
    source = source or ConfiguredTableauSource(settings, source_config(settings))
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
    """Workbooks this PAT can see, newest listing endpoint that works.

    The site-wide endpoint is admin-only on most sites; the per-user one is
    what a normal token can read. Try the first, fall back to the second.
    """
    source, base, token, site_id = _signed_in(settings)
    try:
        status, raw = source._request(
            f"{base}/sites/{site_id}/workbooks?pageSize=1000", token=token)
        books = _books(_base.json.loads(raw)) if status == 200 else []

        if not books:
            status, raw = source._request(
                f"{base}/sites/{site_id}/users?pageSize=1000", token=token)
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
                    token=token)
                if status == 200:
                    books = _books(_base.json.loads(raw))

        rows = [
            {"name": str(b.get("name") or "").strip(),
             "content_url": str(b.get("contentUrl") or "").strip()}
            for b in books
        ]
        rows = [r for r in rows if r["content_url"]]
        rows.sort(key=lambda r: r["name"].lower())
        return rows
    finally:
        source.signout(base, token)


def list_all_views(settings):
    """Every report the token can see, across every workbook, in one list.

    Picking through workbook-then-sheet only works when you already know which
    workbook a report lives in. This is the flat version: one search, one
    click. It is a single sign-in, so it costs one request rather than one per
    workbook per keystroke.

    Everything here is a *published view*. A worksheet that exists only inside
    a dashboard is not published on its own and cannot appear -- which is
    worth being able to see, because a dashboard's data export hands back
    every worksheet on it at once, stitched together.
    """
    source, base, token, site_id = _signed_in(settings)
    try:
        rows = []
        status, raw = source._request(
            f"{base}/sites/{site_id}/views?pageSize=1000", token=token)
        if status == 200:
            for view in source._view_list(_base.json.loads(raw)):
                content_url = str(view.get("contentUrl") or "").strip()
                if not content_url:
                    continue
                parts = content_url.split("/")
                rows.append({
                    "workbook": parts[0],
                    "sheet": parts[-1],
                    "name": str(view.get("name") or parts[-1]).strip(),
                    "content_url": content_url,
                })
    finally:
        source.signout(base, token)

    if not rows:
        # A site that will not serve the flat listing still answers per
        # workbook, so walk them instead.
        for book in list_workbooks(settings):
            try:
                for view in list_views(settings, book["content_url"]):
                    rows.append({
                        "workbook": book["content_url"],
                        "sheet": str(view["content_url"]).split("/")[-1],
                        "name": view["name"],
                        "content_url": view["content_url"],
                    })
            except _base.TableauError:
                continue

    rows.sort(key=lambda r: (r["workbook"].lower(), r["name"].lower()))
    return rows


def list_views(settings, workbook):
    """Sheets in one workbook. Names differ from content URLs, so both."""
    workbook = str(workbook or "").strip()
    if not workbook:
        raise _base.TableauError("Choose a workbook first.")
    source, base, token, site_id = _signed_in(settings)
    try:
        key = _base.urllib.parse.quote(workbook, safe="")
        status, raw = source._request(
            f"{base}/sites/{site_id}/workbooks/{key}?key=contentUrl", token=token)
        if status != 200:
            raise _base.TableauError(
                f"Could not open workbook '{workbook}' (HTTP {status}).")
        workbook_id = str(
            _base.json.loads(raw).get("workbook", {}).get("id") or "").strip()

        status, raw = source._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_id}/views", token=token)
        if status != 200:
            raise _base.TableauError(f"Could not list sheets for '{workbook}'.")
        views = source._view_list(_base.json.loads(raw))
        return [
            {"name": str(v.get("name") or "").strip(),
             "content_url": str(v.get("contentUrl") or "").strip()}
            for v in views if str(v.get("contentUrl") or "").strip()
        ]
    finally:
        source.signout(base, token)


# -------------------------------------------------------------- live preview
# Mapped rows shown on the TV while you are still adjusting the mapping.
#
# Deliberately in memory with an expiry, never in the reps table. A preview
# cannot survive a restart, cannot outlive its window, and cannot overwrite the
# real numbers -- the worst case is the board showing preview data for a few
# minutes and then returning to normal on its own.

import threading
import time as _time

_PREVIEW_LOCK = threading.Lock()
_PREVIEW = {"rows": None, "until": 0.0, "seq": 0, "label": ""}
PREVIEW_MINUTES = 15


def start_preview(rows, label="", minutes=PREVIEW_MINUTES):
    with _PREVIEW_LOCK:
        _PREVIEW["rows"] = list(rows or [])
        _PREVIEW["until"] = _time.time() + max(1, int(minutes)) * 60
        _PREVIEW["seq"] += 1
        _PREVIEW["label"] = str(label or "")
        return dict(_PREVIEW, rows=len(_PREVIEW["rows"]))


def stop_preview():
    with _PREVIEW_LOCK:
        _PREVIEW["rows"] = None
        _PREVIEW["until"] = 0.0
        _PREVIEW["label"] = ""


def preview_rows():
    """Rows to show instead of the stored ones, or None when not previewing."""
    with _PREVIEW_LOCK:
        if _PREVIEW["rows"] is None:
            return None
        if _time.time() >= _PREVIEW["until"]:
            _PREVIEW["rows"] = None
            _PREVIEW["label"] = ""
            return None
        return list(_PREVIEW["rows"])


def preview_state():
    with _PREVIEW_LOCK:
        active = _PREVIEW["rows"] is not None and _time.time() < _PREVIEW["until"]
        return {
            "active": active,
            "label": _PREVIEW["label"] if active else "",
            "rows": len(_PREVIEW["rows"]) if active else 0,
            "seconds_left": max(0, int(_PREVIEW["until"] - _time.time())) if active else 0,
            "seq": _PREVIEW["seq"],
        }


# The date window lives in the settings rather than in the source object --
# the whole app resolves it through resolve_dates() -- but the card offers it
# beside the report, so a trial pull has to carry a candidate range too.
DATE_KEYS = ("data_date_mode", "data_date_start", "data_date_end")


def trial_settings(settings, overrides=None):
    """Settings carrying the date window being tried out, if any."""
    trial = dict(settings or {})
    for key in DATE_KEYS:
        value = (overrides or {}).get(key)
        if value is not None:
            trial[key] = value
    return trial


def trial_config(settings, overrides=None):
    """The saved config with whatever the settings page is trying out on top."""
    config = dict(source_config(settings))
    for key, value in (overrides or {}).items():
        if key in config and value is not None:
            config[key] = value
    return config


def preview_pull(settings, overrides=None):
    """Run a candidate configuration end to end. Saves nothing."""
    import time as _clock
    source = ConfiguredTableauSource(trial_settings(settings, overrides),
                                     trial_config(settings, overrides))
    began = _clock.monotonic()
    start, end, rows = source._pull_rows()
    notes = dict(source.last_notes or {},
                 seconds=round(_clock.monotonic() - began, 1),
                 remote_rows=source.last_remote_rows)
    return start, end, rows, notes


def test_source(settings, overrides=None):
    """Trial pull, reported the way the settings page needs it.

    Never writes anything and never touches the saved configuration, so a
    report can be judged before it is committed to rather than at 6am with a
    stale board.
    """
    start, end, rows, notes = preview_pull(settings, overrides)
    config = trial_config(settings, overrides)
    branch_column = str((config.get("row_filter") or {}).get("column") or "home_branch")
    return {
        "workbook": config["workbook"],
        "sheet": config["sheet"],
        "start": start,
        "end": end,
        "reps": len(rows),
        "offices": sorted({str(r.get(branch_column) or "").strip()
                           for r in rows if str(r.get(branch_column) or "").strip()}),
        "metrics": sorted({key for row in rows for key, value in row.items()
                           if isinstance(value, (int, float)) and value}),
        "sample": [str(r.get("rep_name") or "") for r in rows[:3]],
        "notes": notes,
    }



_FILTER_VALUE_LIMIT = 1000
_FILTER_ROW_LIMIT = 5000


def _filter_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def report_filter_catalog(payload, how):
    """Fields and actual values from the selected report export.

    Tableau REST accepts vf_<field>=<value> using workbook field captions.
    Instead of asking the user to type those captions, expose the exact fields
    and values that this report really returned. No KPI is calculated here.
    """
    if how == "crosstab":
        described = describe_crosstab(payload)
        headers = list(described.get("headers") or [])
        rows = list(described.get("rows") or [])[:_FILTER_ROW_LIMIT]
    else:
        reader = _base.csv.DictReader(_base.io.StringIO(str(payload or "")))
        headers = [str(h or "").strip() for h in (reader.fieldnames or [])
                   if str(h or "").strip()]
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
        values.sort(key=lambda value: value.casefold())
        catalog.append({
            "field": header,
            "values": values,
            "truncated": truncated,
        })
    return catalog

def read_columns(settings, overrides=None):
    """What the candidate report offers to map against, and a first guess.

    Same route as the pull: the view's CSV first, Crosstab Excel only when
    that returns nothing -- so what you map against is what you will get.
    """
    config = trial_config(settings, overrides)
    trial = trial_settings(settings, overrides)
    # Discovery must not be narrowed by filters saved for an older report.
    # Read the selected report itself, then let the user choose filters from
    # the fields and values it actually returned. Preview/scheduled pulls still
    # use the saved filters normally.
    discovery = dict(config)
    discovery["filters"] = []
    discovery["row_filter"] = {}
    source = ConfiguredTableauSource(trial, discovery)
    start, end = _base.resolve_dates(trial)
    base, token, site_id = source.signin()
    try:
        payload, how, csv_error = source.read_export(base, token, site_id, start, end)
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
        }
        described["export"] = "view data (CSV)"
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

