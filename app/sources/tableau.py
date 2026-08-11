"""v40 Tableau connector: pull the exposed Rep Totals worksheet directly.

Tableau's REST view list identifies the worksheet as:
    Rep Totals [8-SalesRepLevelData/sheets/RepTotals]

The dashboard's visible heading says "Sales Rep Totals", but that is not the
REST view name. Query the exposed Rep Totals worksheet directly and use
Tableau's own calculated summary fields. Do not reconstruct totals from detail
rows and do not fall back to another worksheet.
"""
from .tableau_v36_base import *
from . import tableau_v36_base as _base


TARGET_WORKSHEET_NAME = "Rep Totals"
TARGET_WORKSHEET_NORM = "reptotals"
TARGET_CONTENT_TAIL = "/sheets/RepTotals"

# Keep status/error text aligned with what we actually pull.
_base.TABLEAU_VIEW_PATH = (
    f"{_base.TABLEAU_WORKBOOK_CONTENT_URL}/sheets/RepTotals"
)


class TableauSource(_base.TableauSource):
    VIEW_PATH = _base.TABLEAU_VIEW_PATH

    def _view_id(self, base, token, site_id):
        """Resolve only the exposed Rep Totals worksheet."""
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

        def normalized(value):
            return _base.norm(str(value or ""))

        for view in views:
            name = str(view.get("name") or "").strip()
            content_url = str(view.get("contentUrl") or "").strip()
            view_url_name = str(view.get("viewUrlName") or "").strip()

            exact_name = normalized(name) == TARGET_WORKSHEET_NORM
            exact_url = normalized(view_url_name) == TARGET_WORKSHEET_NORM
            exact_content = content_url.lower().endswith(TARGET_CONTENT_TAIL.lower())

            if exact_name or exact_url or exact_content:
                view_id = str(view.get("id") or "").strip()
                if view_id:
                    return view_id

        available = []
        for view in views[:50]:
            label = str(view.get("name") or view.get("viewUrlName") or "?").strip()
            content = str(view.get("contentUrl") or "").strip()
            available.append(f"{label} [{content}]")

        raise _base.TableauError(
            "Tableau did not expose the Rep Totals worksheet expected at "
            f"{_base.TABLEAU_VIEW_PATH}. Available views: "
            + ("; ".join(available) if available else "none")
        )

    def fetch_csv(self, base, token, site_id, start, end):
        """Query Rep Totals and verify Tableau returned summary columns."""
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
                "Rep Totals returned unexpected columns; missing Tableau summary "
                "fields: " + ", ".join(missing) + ". Columns received: "
                + (", ".join(headers) if headers else "none")
            )

        return csv_text


# Public names expected by server.py
TableauError = _base.TableauError
resolve_dates = _base.resolve_dates
