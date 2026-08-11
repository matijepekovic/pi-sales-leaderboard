"""v41 Tableau connector: pull the exact Rep Totals NEW worksheet.

The Tableau crosstab dialog identifies the totals worksheet as "Rep Totals NEW".
The workbook REST view list exposes that worksheet at:
    8-SalesRepLevelData/sheets/RepTotalsNEW3

Target that exact content URL. Do not query RepTotals, do not reconstruct totals
from Rep Details, and do not fall back to another worksheet.
"""
from .tableau_v36_base import *
from . import tableau_v36_base as _base


TARGET_CONTENT_TAIL = "/sheets/RepTotalsNEW3"

# Keep status/error text aligned with what we actually pull.
_base.TABLEAU_VIEW_PATH = (
    f"{_base.TABLEAU_WORKBOOK_CONTENT_URL}/sheets/RepTotalsNEW3"
)


class TableauSource(_base.TableauSource):
    VIEW_PATH = _base.TABLEAU_VIEW_PATH

    def _view_id(self, base, token, site_id):
        """Resolve only the exact Rep Totals NEW REST view."""
        workbook_id = self._workbook_id(base, token, site_id)
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_id}/views",
            token=token,
        )
        if status != 200:
            raise _base.TableauError(
                f"Could not list views for {_base.TABLEAU_WORKBOOK_CONTENT_URL}."
            )

        try:
            views = self._view_list(_base.json.loads(raw))
        except Exception:
            views = []

        for view in views:
            content_url = str(view.get("contentUrl") or "").strip()
            if content_url.lower().endswith(TARGET_CONTENT_TAIL.lower()):
                view_id = str(view.get("id") or "").strip()
                if view_id:
                    return view_id

        available = []
        for view in views[:50]:
            label = str(view.get("name") or view.get("viewUrlName") or "?").strip()
            content = str(view.get("contentUrl") or "").strip()
            available.append(f"{label} [{content}]")

        raise _base.TableauError(
            "Tableau did not expose the expected Rep Totals NEW REST view at "
            f"{_base.TABLEAU_VIEW_PATH}. Available views: "
            + ("; ".join(available) if available else "none")
        )

    def fetch_csv(self, base, token, site_id, start, end):
        """Query Rep Totals NEW and verify Tableau returned the summary fields."""
        csv_text = super().fetch_csv(base, token, site_id, start, end)

        reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
        headers = reader.fieldnames or []
        normalized_headers = [_base.norm(h) for h in headers]

        required_markers = {
            "issued": "issuedleadssplitprep",
            "pitched": "pitchedleadssplit",
            "sold": "soldleadssplit",
        }
        missing = [
            label for label, marker in required_markers.items()
            if not any(marker in h for h in normalized_headers)
        ]
        if missing:
            raise _base.TableauError(
                "Rep Totals NEW returned unexpected columns; missing Tableau summary "
                "fields: " + ", ".join(missing) + ". Columns received: "
                + (", ".join(headers) if headers else "none")
            )

        return csv_text


# Public names expected by server.py
TableauError = _base.TableauError
resolve_dates = _base.resolve_dates
