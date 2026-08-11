"""v37 Tableau parsing shim.

Keeps the v36 connector intact but fixes rep-total reconstruction from a
Tableau dashboard detail-sheet export:
- process wide KPI columns even when Measure Names/Measure Values are present
- count split-prep lead metrics once per LEAD-Id, including repeated job rows
- forward-fill suppressed crosstab dimension labels within a rep/lead group

The full Tableau pull is still retained; TV eligibility remains a separate
Pi-team-assignment rule in the display layer.
"""
from .tableau_v36_base import *
from . import tableau_v36_base as _base


def parse_rows(csv_text):
    reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
    headers = reader.fieldnames or []

    def col_for(aliases):
        return _base.find_column(headers, aliases)

    rep_col = col_for(_base.REP_ALIASES)
    if not rep_col:
        raise ValueError(
            "Could not find a rep-name column in the Tableau data. "
            f"Columns seen: {', '.join(headers) or '(none)'}"
        )

    branch_col = col_for(_base.BRANCH_ALIASES)
    title_col = col_for(_base.TITLE_ALIASES)
    hire_col = col_for(_base.HIRE_ALIASES)
    team_col = col_for(_base.TEAM_ALIASES)
    lead_col = col_for(_base.LEAD_ID_ALIASES)
    mn_col = col_for(_base.MEASURE_NAME_COLS)
    mv_col = col_for(_base.MEASURE_VALUE_COLS)

    # Tableau dashboard CSVs can contain ordinary KPI columns and also a
    # Measure Names/Measure Values pair. v36 treated those shapes as mutually
    # exclusive; v37 consumes both without double-counting the same field/row.
    wide_by_field = {}
    for header in headers:
        if header in (mn_col, mv_col):
            continue
        field = _base.match_field(_base.norm(header))
        if field:
            wide_by_field.setdefault(field, []).append(header)

    # Prefer the exact split-prep field when multiple captions map to one KPI.
    def header_priority(header):
        n = _base.norm(header)
        return (0 if "splitprep" in n else 1, -len(n))

    for field in wide_by_field:
        wide_by_field[field].sort(key=header_priority)

    acc = {}
    meta = {}
    order = []
    current_rep = ""
    current_lead = ""

    def total_row(row):
        vals = [str(v or "").strip().lower() for v in row.values()]
        return "total" in vals and not str(row.get(lead_col) or "").strip() if lead_col else "total" in vals

    for row_index, row in enumerate(reader):
        raw_name = str(row.get(rep_col) or "").strip()
        if raw_name:
            if raw_name != current_rep:
                current_lead = ""
            current_rep = raw_name
        name = current_rep
        if not name or name.lower() in ("all", "total"):
            continue
        if total_row(row):
            continue

        if name not in acc:
            acc[name] = {}
            meta[name] = {}
            order.append(name)

        raw_lead = str(row.get(lead_col) or "").strip() if lead_col else ""
        if raw_lead:
            current_lead = raw_lead
        lead = raw_lead or current_lead
        if lead.lower() in ("all", "total"):
            continue

        info = meta[name]
        for key, col in (("home_branch", branch_col), ("title", title_col),
                         ("hire_date", hire_col), ("team", team_col)):
            if col:
                val = str(row.get(col) or "").strip()
                if val and val.lower() not in ("all", "total") and not info.get(key):
                    info[key] = val

        def feed(field, raw):
            v = _base.clean_number(raw)
            if v is None:
                return False

            if field in _base.COUNT_FIELDS:
                # Split-prep lead metrics are lead credits, not job-row counts.
                # A sold lead can have multiple jobs/rows, each repeating the
                # same 0.5/1.0 credit. Count the credit once per LEAD-Id.
                key = lead or f"__row_{row_index}"
                bucket = acc[name].setdefault(field, {})
                previous = bucket.get(key)
                if previous is None or abs(v) > abs(previous):
                    bucket[key] = v
            else:
                slot = acc[name].setdefault(field, [0.0, 0])
                slot[0] += v
                slot[1] += 1
            return True

        seen_this_row = set()

        # First use direct KPI columns. This is the important v37 correction
        # for Issued Leads Split Prep / Pitched Leads Split / Sold Leads Split.
        for field, field_headers in wide_by_field.items():
            for header in field_headers:
                if feed(field, row.get(header)):
                    seen_this_row.add(field)
                    break

        # Then consume a long-format measure only when that KPI was not already
        # present as a direct column on this same row.
        if mn_col and mv_col:
            field = _base.match_field(_base.norm(row.get(mn_col) or ""))
            if field and field not in seen_this_row:
                feed(field, row.get(mv_col))

    reps = []
    for name in order:
        rec = {"name": name}
        for field, agg in acc[name].items():
            if isinstance(agg, dict):
                rec[field] = sum(agg.values())
            else:
                total, count = agg
                rec[field] = (total / count) if field in _base.MEAN_FIELDS and count else total
        rec.update(meta[name])
        reps.append(_base.derive(rec))
    return reps


# TableauSource._pull_rows resolves parse_rows from its defining module at
# runtime, so replacing that module-global parser upgrades the existing class
# without duplicating authentication, filtering, or branch guards.
_base.parse_rows = parse_rows
TableauSource = _base.TableauSource
TableauError = _base.TableauError
resolve_dates = _base.resolve_dates
