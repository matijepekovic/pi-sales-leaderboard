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


def resolve_source(settings):
    """The rep source to pull with. Today's class unless a report was picked."""
    workbook, sheet = chosen(settings)
    if not workbook:
        return TableauSource(settings)
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
