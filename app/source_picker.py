"""Choosing which Tableau report the rep board reads from.

Two jobs:

  resolve_source(settings) - the factory. Returns the shipped TableauSource
  unless a report has actually been picked, so an install that never touches
  the picker runs exactly the code it ran before this file existed.

  list_workbooks / list_views / test_view - discovery for the settings page,
  reusing the base connector's sign-in and request helpers rather than
  adding any HTTP code.
"""
from sources import tableau_v36_base as _base
from sources.tableau import TableauSource
from sources.tableau_custom import CustomTableauSource
from sources.tableau_crosstab import (CrosstabMappedTableauSource,
                                      mapping_description)

# What the board reads when nothing has been picked. Kept here as strings so
# "Reset to Default" has something to restore, and so the shipped connector
# itself never has to be edited.
DEFAULT_WORKBOOK = "8-SalesRepLevelData"
DEFAULT_SHEET = "RepTotalsNEW3"


def chosen(settings):
    """The picked report, or ("", "") when running on the default."""
    workbook = str((settings or {}).get("tableau_workbook") or "").strip()
    sheet = str((settings or {}).get("tableau_sheet") or "").strip()
    if not workbook or not sheet:
        return "", ""
    # A pick that matches the shipped target is not a pick -- fall through to
    # the original class so the default path stays byte-identical.
    if (workbook.lower() == DEFAULT_WORKBOOK.lower()
            and sheet.rsplit("/", 1)[-1].lower() == DEFAULT_SHEET.lower()):
        return "", ""
    return workbook, sheet


def mapping_of(settings):
    """The saved column mapping, or {} when the report needs no mapping."""
    mapping = (settings or {}).get("source_mapping") or {}
    return mapping if mapping.get("rep_name") else {}


def resolve_source(settings):
    """The rep source to pull with. Today's class unless a report was picked."""
    workbook, sheet = chosen(settings)
    if not workbook:
        return TableauSource(settings)
    mapping = mapping_of(settings)
    if mapping:
        return CrosstabMappedTableauSource(settings, workbook, sheet, mapping)
    return CustomTableauSource(settings, workbook, sheet)


def describe(settings):
    workbook, sheet = chosen(settings)
    return {
        "workbook": workbook or DEFAULT_WORKBOOK,
        "sheet": (sheet or DEFAULT_SHEET).rsplit("/", 1)[-1],
        "is_default": not workbook,
        "default_workbook": DEFAULT_WORKBOOK,
        "default_sheet": DEFAULT_SHEET,
    }


# ------------------------------------------------------------------ discovery

def _signed_in(settings):
    source = TableauSource(settings)
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


def preview_pull(settings, workbook, sheet, mapping):
    """Run the chosen report through the mapping. Saves nothing."""
    source = CrosstabMappedTableauSource(settings, workbook, sheet, mapping)
    start, end, rows = source._pull_rows()
    return start, end, rows, source.last_notes


def test_view(settings, workbook, sheet):
    """Trial pull. Never writes anything, and never touches the saved source.

    Returns what a real pull would have found, so a report can be judged
    before it is committed to rather than at 6am with a stale board.
    """
    source = CustomTableauSource(settings, workbook, sheet)
    start, end, rows = source._pull_rows()
    offices = sorted({
        str(r.get("home_branch") or "").strip()
        for r in rows if str(r.get("home_branch") or "").strip()
    })
    metrics = sorted({
        key for row in rows for key, value in row.items()
        if isinstance(value, (int, float)) and value
    })
    return {
        "workbook": workbook,
        "sheet": sheet,
        "start": start,
        "end": end,
        "reps": len(rows),
        "offices": offices,
        "metrics": metrics,
        "sample": [str(r.get("rep_name") or "") for r in rows[:3]],
    }


def report_columns(settings, workbook, sheet):
    """Download Tableau's Crosstab Excel and expose those finished columns."""
    source = CrosstabMappedTableauSource(settings, workbook, sheet, {})
    start, end = _base.resolve_dates(settings)
    base, token, site_id = source.signin()
    try:
        xlsx_bytes = source.fetch_crosstab(base, token, site_id, start, end)
    finally:
        source.signout(base, token)

    described = mapping_description(xlsx_bytes)
    return {**described, "start": start, "end": end}

