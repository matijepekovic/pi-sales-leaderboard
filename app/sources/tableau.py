"""v42 Tableau connector: pivot Rep Totals NEW summary measures.

The exact published worksheet is:
    8-SalesRepLevelData/sheets/RepTotalsNEW3

Tableau REST returns this worksheet in long form:
    Measure Names | Month | Year ... | SR-Name | USER-Home_Branch__c | Measure Values

Those are already Tableau's rep-level summary values. Pivot the additive summary
measures into one record per rep (and sum them across months for date overrides),
then derive rates/averages from those finished Tableau totals.

No LEAD-Id parsing, no Rep Details reconstruction, and no fallback worksheet.
"""
from .tableau_v36_base import *
from . import tableau_v36_base as _base


TARGET_CONTENT_TAIL = "/sheets/RepTotalsNEW3"

# Keep status/error text aligned with what we actually pull.
_base.TABLEAU_VIEW_PATH = (
    f"{_base.TABLEAU_WORKBOOK_CONTENT_URL}/sheets/RepTotalsNEW3"
)

ADDITIVE_FIELDS = {
    "issuedLeads",
    "pitchedLeads",
    "soldLeads",
    "grossSplit",
    "pendingSplit",
    "netSplit",
}


def parse_summary_rows(csv_text):
    """Pivot Tableau's long Rep Totals NEW export into one summary row per rep."""
    reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
    headers = reader.fieldnames or []

    rep_col = _base.find_column(headers, _base.REP_ALIASES)
    branch_col = _base.find_column(headers, _base.BRANCH_ALIASES)
    measure_name_col = _base.find_column(headers, _base.MEASURE_NAME_COLS)
    measure_value_col = _base.find_column(headers, _base.MEASURE_VALUE_COLS)
    month_col = _base.find_column(headers, ["month"])
    year_col = _base.find_column(headers, ["year"])

    missing_cols = []
    if not rep_col:
        missing_cols.append("SR-Name")
    if not measure_name_col:
        missing_cols.append("Measure Names")
    if not measure_value_col:
        missing_cols.append("Measure Values")
    if missing_cols:
        raise ValueError(
            "Rep Totals NEW is missing required long-format columns: "
            + ", ".join(missing_cols)
            + ". Columns seen: "
            + (", ".join(headers) if headers else "none")
        )

    # name -> {"meta": {...}, "values": {field: {period: number}}}
    #
    # Store one value per rep/metric/month. If Tableau repeats an identical mark,
    # retaining the largest absolute value avoids double-counting the same summary
    # cell. Distinct months are summed later, which makes custom multi-month date
    # overrides aggregate correctly.
    reps = {}
    order = []

    for row_index, row in enumerate(reader):
        name = str(row.get(rep_col) or "").strip()
        if not name or name.lower() in {"grand total", "total", "all"}:
            continue

        measure_name = str(row.get(measure_name_col) or "").strip()
        field = _base.match_field(_base.norm(measure_name))
        if field not in ADDITIVE_FIELDS:
            # Rates, DPL, retention and average-sale measures are deliberately
            # derived from the additive Tableau totals below. That is correct
            # both for one month and for a custom range spanning several months.
            continue

        value = _base.clean_number(row.get(measure_value_col))
        if value is None:
            continue

        if name not in reps:
            reps[name] = {
                "meta": {
                    "home_branch": str(row.get(branch_col) or "").strip()
                    if branch_col else ""
                },
                "values": {},
            }
            order.append(name)
        elif branch_col and not reps[name]["meta"].get("home_branch"):
            reps[name]["meta"]["home_branch"] = str(
                row.get(branch_col) or ""
            ).strip()

        month = str(row.get(month_col) or "").strip() if month_col else ""
        year = str(row.get(year_col) or "").strip() if year_col else ""
        period = (year, month) if (year or month) else ("all", str(row_index))

        bucket = reps[name]["values"].setdefault(field, {})
        previous = bucket.get(period)
        if previous is None or abs(value) > abs(previous):
            bucket[period] = value

    result = []
    for name in order:
        source = reps[name]
        rec = {"name": name}
        rec.update(source["meta"])

        for field in ADDITIVE_FIELDS:
            rec[field] = sum(source["values"].get(field, {}).values())

        # derive() produces the app's expected percentage scale (0..100) and
        # exact DPL/retention/average-sale values from the Tableau summary totals.
        result.append(_base.derive(rec))

    return result


# TableauSource._pull_rows is defined in tableau_v36_base and resolves
# parse_rows from that module at runtime. Replace only that parser.
_base.parse_rows = parse_summary_rows


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
            label = str(
                view.get("name") or view.get("viewUrlName") or "?"
            ).strip()
            content = str(view.get("contentUrl") or "").strip()
            available.append(f"{label} [{content}]")

        raise _base.TableauError(
            "Tableau did not expose the expected Rep Totals NEW REST view at "
            f"{_base.TABLEAU_VIEW_PATH}. Available views: "
            + ("; ".join(available) if available else "none")
        )

    def fetch_csv(self, base, token, site_id, start, end):
        """Query Rep Totals NEW and verify its long-format summary measures."""
        csv_text = super().fetch_csv(base, token, site_id, start, end)

        reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
        headers = reader.fieldnames or []
        rep_col = _base.find_column(headers, _base.REP_ALIASES)
        measure_name_col = _base.find_column(headers, _base.MEASURE_NAME_COLS)
        measure_value_col = _base.find_column(headers, _base.MEASURE_VALUE_COLS)

        missing_cols = []
        if not rep_col:
            missing_cols.append("SR-Name")
        if not measure_name_col:
            missing_cols.append("Measure Names")
        if not measure_value_col:
            missing_cols.append("Measure Values")
        if missing_cols:
            raise _base.TableauError(
                "Rep Totals NEW returned unexpected columns; missing "
                + ", ".join(missing_cols)
                + ". Columns received: "
                + (", ".join(headers) if headers else "none")
            )

        fields_seen = set()
        reps_seen = set()
        measures_seen = set()
        for row in reader:
            name = str(row.get(rep_col) or "").strip()
            if name and name.lower() not in {"grand total", "total", "all"}:
                reps_seen.add(name)

            measure_name = str(row.get(measure_name_col) or "").strip()
            if measure_name:
                measures_seen.add(measure_name)
                field = _base.match_field(_base.norm(measure_name))
                if field:
                    fields_seen.add(field)

        required = {"issuedLeads", "pitchedLeads", "soldLeads", "grossSplit"}
        missing = sorted(required - fields_seen)
        if missing:
            raise _base.TableauError(
                "Rep Totals NEW is missing expected Tableau summary measures: "
                + ", ".join(missing)
                + ". Measure Names received: "
                + (", ".join(sorted(measures_seen)) if measures_seen else "none")
            )
        if not reps_seen:
            raise _base.TableauError(
                f"Rep Totals NEW returned no rep rows for {start} to {end}."
            )

        return csv_text


# Public names expected by server.py
TableauError = _base.TableauError
resolve_dates = _base.resolve_dates
