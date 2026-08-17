"""A rep pull aimed at a workbook and sheet chosen from the settings page.

This exists so the report can be changed without editing the working
connector. It subclasses the shipped TableauSource and overrides only the
two methods that decide *where* to look; the sign-in, the date and branch
filters, the CSV parsing and the Olympia guard are all inherited unchanged.

That is the same shape tableau_products.py has used since v75, so the
mechanism is proven rather than new.

Nothing constructs this unless a report has actually been picked -- see
source_picker.resolve_source(). With the picker untouched, the board runs
the original class and this file is never imported into the request path.
"""
from . import tableau_v36_base as _base
from .tableau import TableauSource as _RepSource


class CustomTableauSource(_RepSource):
    """Same rep pull, pointed somewhere else.

    workbook: a workbook content URL, e.g. "8-SalesRepLevelData"
    sheet:    a view content URL or its tail, e.g.
              "8-SalesRepLevelData/sheets/RepTotalsNEW3" or "RepTotalsNEW3"
    """

    def __init__(self, config=None, workbook="", sheet=""):
        super().__init__(config)
        self.workbook = str(workbook or "").strip()
        self.sheet = str(sheet or "").strip()
        # Match on the tail so a stored full content URL and a bare sheet
        # name both work. Tableau's own contentUrl is the full form.
        tail = self.sheet.rsplit("/", 1)[-1]
        self.sheet_tail = f"/sheets/{tail}" if tail else ""
        self.VIEW_PATH = f"{self.workbook}/sheets/{tail}" if tail else self.workbook

    def _workbook_id(self, base, token, site_id):
        key = _base.urllib.parse.quote(self.workbook, safe="")
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{key}?key=contentUrl",
            token=token,
        )
        if status != 200:
            raise _base.TableauError(
                f"Could not find Tableau workbook '{self.workbook}' (HTTP {status})."
            )
        try:
            workbook_id = str(
                _base.json.loads(raw).get("workbook", {}).get("id") or ""
            ).strip()
        except Exception:
            workbook_id = ""
        if not workbook_id:
            raise _base.TableauError(
                f"Tableau workbook '{self.workbook}' returned no id."
            )
        return workbook_id

    def _view_id(self, base, token, site_id):
        workbook_id = self._workbook_id(base, token, site_id)
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_id}/views", token=token
        )
        if status != 200:
            raise _base.TableauError(
                f"Could not list views for '{self.workbook}'."
            )
        try:
            views = self._view_list(_base.json.loads(raw))
        except Exception:
            views = []

        for view in views:
            content_url = str(view.get("contentUrl") or "").strip()
            if content_url.lower().endswith(self.sheet_tail.lower()):
                view_id = str(view.get("id") or "").strip()
                if view_id:
                    return view_id

        available = "; ".join(
            f"{str(v.get('name') or '?').strip()} [{str(v.get('contentUrl') or '').strip()}]"
            for v in views[:50]
        )
        raise _base.TableauError(
            f"'{self.workbook}' has no sheet matching '{self.sheet}'. "
            f"Sheets available: {available or 'none'}"
        )
