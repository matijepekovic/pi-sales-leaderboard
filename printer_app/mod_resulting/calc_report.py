"""Editable, source-neutral Olympia daily calculator report.

Takes the same saved normalized MOD work orders as the cover. Work orders,
not product-result rows, are the countable unit. No Salesforce API fields here.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from .report_facts import (
    decimal_amount, has_sale, is_not_home, result_disposition, sold_revenue,
)

INPUT_FIELDS = (
    ("sold", "# Sold"),
    ("pns", "PNS"),
    ("nh", "NH"),
    ("np", "NP"),
    ("nra", "NRA"),
    ("cxl", "CXL"),
    ("revenue", "Total Sale Rev"),
)
OUTPUT_FIELDS = (
    ("leads", "Leads"),
    ("pitch", "Pitch"),
    ("pitch_nra", "Pitch -NRA"),
    ("close", "Close"),
    ("close_nra", "Close -NRA"),
    ("total", "Total"),
    ("dpl", "DPL"),
    ("nra_total", "NRA"),
)


def _money(value):
    if value is None:
        return ""
    return "$" + f"{value:,.2f}"


def _ratio(numerator, denominator):
    if denominator is None or denominator <= 0 or numerator is None:
        return ""
    return f"{numerator / denominator:.1%}"


def _recalculate(inputs, work_orders, oos):
    """Exact OLY Calc spreadsheet formulas, with CXL and OOS off the lead count."""
    sold = decimal_amount(inputs["sold"])
    pns = decimal_amount(inputs["pns"])
    nh = decimal_amount(inputs["nh"])
    np = decimal_amount(inputs["np"])
    nra = decimal_amount(inputs["nra"])
    cxl = decimal_amount(inputs["cxl"])
    revenue = decimal_amount(inputs["revenue"])
    if all(v is not None for v in (sold, pns, nh, np, nra, cxl)):
        pitched = sold + pns
        denominator = sold + pns + nh + np + nra
        denominator_no_nra = sold + pns + nh + np
    else:
        pitched = denominator = denominator_no_nra = None
    leads = Decimal(work_orders - oos) - cxl if cxl is not None else None
    return {
        "leads": str(int(leads)) if leads is not None and leads == int(leads) else (
            str(leads) if leads is not None else ""),
        "pitch": _ratio(pitched, denominator),
        "pitch_nra": _ratio(pitched, denominator_no_nra),
        "close": _ratio(sold, leads),
        "close_nra": _ratio(sold, leads - nra) if leads is not None and nra is not None else "",
        "total": _money(revenue),
        "dpl": _money(revenue / leads) if revenue is not None and leads is not None and leads > 0 else "",
        "nra_total": inputs["nra"],
    }


def project_calc(day, sheets):
    """Count each Work Order once; CXL at Lead never changes its actual result."""
    totals = dict(sold=0, pns=0, nh=0, np=0, nra=0, cxl=0, oos=0)
    revenue = Decimal("0")
    for sheet in sheets:
        draft = sheet["draft"]
        # WorkOrder's actual disposition takes precedence when present.
        outcome = result_disposition(draft)
        if outcome in ("cxl", "oos"):
            # An actual canceled/out-of-scope WorkOrder is not an issued lead.
            bucket = outcome
        elif outcome == "sale" or has_sale(draft):
            # Include a positive-priced sale on a secondary product, but
            # count its WorkOrder only once.
            bucket = "sold"
        elif outcome == "np" and is_not_home(draft):
            bucket = "nh"
        else:
            bucket = outcome
        if bucket in totals:
            totals[bucket] += 1
        if bucket == "sold":
            sale = sold_revenue(draft)
            if sale is not None:
                revenue += sale
    inputs = {key: str(totals[key]) for key, _ in INPUT_FIELDS if key != "revenue"}
    inputs["revenue"] = _money(revenue)
    return {
        "day": day,
        "work_orders": len(sheets),
        "oos": totals["oos"],
        "inputs": inputs,
        "outputs": _recalculate(inputs, len(sheets), totals["oos"]),
    }


def apply_calc_edits(original, edits):
    """Sparse edits override the report; numeric input edits recalculate metrics."""
    if not isinstance(edits, dict) or set(edits) - {"inputs", "outputs"}:
        raise ValueError("Invalid OLY Calc report edits.")
    report = deepcopy(original)
    for section, allowed in (("inputs", {key for key, _ in INPUT_FIELDS}),
                             ("outputs", {key for key, _ in OUTPUT_FIELDS})):
        changes = edits.get(section, {})
        if (not isinstance(changes, dict) or set(changes) - allowed
                or any(not isinstance(value, str) or len(value) > 90
                       for value in changes.values())):
            raise ValueError("Invalid OLY Calc cell edit.")
    report["inputs"].update(edits.get("inputs", {}))
    report["outputs"] = _recalculate(
        report["inputs"], report["work_orders"], report["oos"])
    report["outputs"].update(edits.get("outputs", {}))
    return report
