"""v39 Tableau connector: pull the Sales Rep Totals worksheet directly.

Do not reconstruct rep totals from a dashboard/detail export. Tableau REST
returns only one child worksheet when a dashboard is queried as CSV, so v39
resolves the published worksheet named "Sales Rep Totals" and queries that
view directly. Tableau's own calculated rep totals are then mapped into the
leaderboard schema by the original wide-row parser.

If the worksheet is hidden/not exposed as a REST view, fail clearly instead
of falling back to detail data or guessing calculations.
"""
from .tableau_v36_base import *
from . import tableau_v36_base as _base


TARGET_WORKSHEET_NAME = "Sales Rep Totals"
TARGET_WORKSHEET_NORM = "salesreptotals"

# Keep status/error text aligned with what we actually pull.
_base.TABLEAU_VIEW_PATH = (
    f"{_base.TABLEAU_WORKBOOK_CONTENT_URL}/sheets/SalesRepTotals"
)


class TableauSource(_base.TableauSource):
    VIEW_PATH = _base.TABLEAU_VIEW_PATH

    def _view_id(self, base, token, site_id):
        """Resolve the published Sales Rep Totals worksheet, never the dashboard."""
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

        # Prefer the human-readable worksheet name. Then accept an exact sheet
        # URL-name/contentUrl match, but never silently select the RepTotals
        # dashboard itself.
        for view in views:
            name = str(view.get("name") or "").strip()
            content_url = str(view.get("contentUrl") or "").strip()
            view_url_name = str(view.get("viewUrlName") or "").strip()
            is_sheet_path = "/sheets/" in content_url.lower()

            exact_name = normalized(name) == TARGET_WORKSHEET_NORM
            exact_url = normalized(view_url_name) == TARGET_WORKSHEET_NORM
            sheet_tail = (
                is_sheet_path
                and normalized(content_url.rsplit("/", 1)[-1]) == TARGET_WORKSHEET_NORM
            )

            if exact_name or exact_url or sheet_tail:
                view_id = str(view.get("id") or "").strip()
                if view_id:
                    return view_id

        available = []
        for view in views[:50]:
            label = str(view.get("name") or view.get("viewUrlName") or "?").strip()
            content = str(view.get("contentUrl") or "").strip()
            available.append(f"{label} [{content}]")

        raise _base.TableauError(
            "Tableau did not expose the 'Sales Rep Totals' worksheet as a REST view. "
            "The leaderboard refused to fall back to dashboard detail data. "
            "Available views: " + ("; ".join(available) if available else "none")
        )

    def fetch_csv(self, base, token, site_id, start, end):
        """Query Sales Rep Totals and verify we received its summary columns."""
        csv_text = super().fetch_csv(base, token, site_id, start, end)

        reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
        headers = reader.fieldnames or []
        normalized_headers = [_base.norm(h) for h in headers]

        # We specifically need Tableau's pre-calculated rep-total fields. If
        # those are absent, stop rather than reconstructing them from another
        # worksheet.
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
                "Sales Rep Totals returned unexpected columns; missing Tableau "
                "summary fields: " + ", ".join(missing) + ". Columns received: "
                + (", ".join(headers) if headers else "none")
            )

        return csv_text


# Public names expected by server.py
TableauError = _base.TableauError
resolve_dates = _base.resolve_dates
