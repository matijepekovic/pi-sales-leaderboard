"""v38 Tableau parsing shim.

The Rep Totals dashboard can export a lower-level worksheet where the split
count measures are sparse across rows. Reconstruct counts per unique LEAD-Id:

- issued credit = the lead's split credit (recoverable from issued/pitched/sold)
- pitched credit = only when pitched is present for that lead
- sold credit = only when sold is present for that lead
- repeated job rows for the same LEAD-Id count once

This matches Tableau's Sales Rep Totals logic without changing the full pull
or the Pi-team-only TV eligibility rule.
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

    wide_by_field = {}
    for header in headers:
        if header in (mn_col, mv_col):
            continue
        field = _base.match_field(_base.norm(header))
        if field:
            wide_by_field.setdefault(field, []).append(header)

    def header_priority(header):
        n = _base.norm(header)
        return (
            0 if "splitprep" in n else 1,
            0 if "split" in n else 1,
            -len(n),
        )

    for field in wide_by_field:
        wide_by_field[field].sort(key=header_priority)

    acc = {}
    meta = {}
    order = []
    lead_counts = {}
    current_rep = ""
    current_lead = ""

    def total_row(row):
        vals = [str(v or "").strip().lower() for v in row.values()]
        if lead_col:
            return "total" in vals and not str(row.get(lead_col) or "").strip()
        return "total" in vals

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
            lead_counts[name] = {}
            order.append(name)

        raw_lead = str(row.get(lead_col) or "").strip() if lead_col else ""
        if raw_lead:
            current_lead = raw_lead
        lead = raw_lead or current_lead
        if lead.lower() in ("all", "total"):
            continue

        info = meta[name]
        for key, col in (
            ("home_branch", branch_col),
            ("title", title_col),
            ("hire_date", hire_col),
            ("team", team_col),
        ):
            if col:
                val = str(row.get(col) or "").strip()
                if val and val.lower() not in ("all", "total") and not info.get(key):
                    info[key] = val

        real_lead = bool(lead)
        lead_key = lead if real_lead else f"__row_{row_index}"

        def feed(field, raw):
            v = _base.clean_number(raw)
            if v is None:
                return False

            if field in _base.COUNT_FIELDS:
                bucket = lead_counts[name].setdefault(
                    lead_key, {"_real_lead": real_lead}
                )
                previous = bucket.get(field)
                if previous is None or abs(v) > abs(previous):
                    bucket[field] = v
            else:
                slot = acc[name].setdefault(field, [0.0, 0])
                slot[0] += v
                slot[1] += 1
            return True

        seen_this_row = set()

        for field, field_headers in wide_by_field.items():
            for header in field_headers:
                if feed(field, row.get(header)):
                    seen_this_row.add(field)
                    break

        if mn_col and mv_col:
            field = _base.match_field(_base.norm(row.get(mn_col) or ""))
            if field and field not in seen_this_row:
                feed(field, row.get(mv_col))

    reps = []
    for name in order:
        rec = {"name": name}

        for field, agg in acc[name].items():
            total, count = agg
            rec[field] = (
                (total / count)
                if field in _base.MEAN_FIELDS and count
                else total
            )

        issued = pitched = sold = 0.0
        for bucket in lead_counts[name].values():
            issued_v = bucket.get("issuedLeads")
            pitched_v = bucket.get("pitchedLeads")
            sold_v = bucket.get("soldLeads")

            if bucket.get("_real_lead"):
                observed = [
                    v for v in (issued_v, pitched_v, sold_v)
                    if v is not None
                ]
                if observed:
                    issued += max(observed, key=lambda x: abs(x))
            elif issued_v is not None:
                issued += issued_v

            if pitched_v is not None:
                pitched += pitched_v
            if sold_v is not None:
                sold += sold_v

        if lead_counts[name]:
            rec["issuedLeads"] = issued
            rec["pitchedLeads"] = pitched
            rec["soldLeads"] = sold

        rec.update(meta[name])
        reps.append(_base.derive(rec))

    return reps


_base.parse_rows = parse_rows
TableauSource = _base.TableauSource
TableauError = _base.TableauError
resolve_dates = _base.resolve_dates
