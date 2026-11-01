"""Source-neutral sales facts shared by Olympia reports.

Only normalized Stats MOD records belong here. Salesforce names, HTTP, storage,
and display layout stay with their respective adapters.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def decimal_amount(value):
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        number = Decimal(text.replace(",", "").replace("$", ""))
    except (ValueError, InvalidOperation):
        return None
    return number if number.is_finite() else None


def sold_entries(draft):
    """Explicitly sold products with positive prices, one entry per product.

    Imported Salesforce product results are authoritative. For a product
    present in both representations the existing selected sale entry wins,
    avoiding double-counting a sale. Missing deposits do not invalidate
    existing Salesforce price data.
    """
    entries = {}
    for product, value in (draft.get("sale_products") or {}).items():
        if isinstance(value, dict):
            price = decimal_amount(value.get("price"))
            if price is not None and price > 0:
                entries[product] = value
    for product, value in (draft.get("product_results") or {}).items():
        if (isinstance(value, dict) and
                str(value.get("result") or "").strip().casefold() == "sale" and
                decimal_amount(value.get("price")) is not None and
                decimal_amount(value.get("price")) > 0):
            if product not in entries:
                entries[product] = value
    return entries


def has_sale(draft):
    """A result is sold if the work-order result or any product is a sale."""
    return (str(draft.get("dispo") or "").strip().casefold() == "sale" or
            bool(sold_entries(draft)))


def result_disposition(draft):
    """Use WorkOrder's actual disposition, or a unanimous product outcome.

    Conflicting product outcomes with no WorkOrder disposition stay unclassified
    for a single-work-order summary. They are never rewritten or transformed.
    """
    main = str(draft.get("dispo") or "").strip().casefold()
    if main:
        return main
    outcomes = {
        str(item.get("result") or "").strip().casefold()
        for item in (draft.get("product_results") or {}).values()
        if isinstance(item, dict) and str(item.get("result") or "").strip()
    }
    return next(iter(outcomes)) if len(outcomes) == 1 else ""


def sold_revenue(draft):
    """Sum sold products once; use the WorkOrder sale price only as fallback."""
    entries = sold_entries(draft)
    if entries:
        return sum(
            (decimal_amount(item.get("price")) for item in entries.values()),
            Decimal("0")
        )
    if has_sale(draft):
        return decimal_amount(draft.get("final_price_override"))
    return None


def is_not_home(draft):
    """NP with an explicit Not Home result detail; CXL At Lead is unrelated."""
    if result_disposition(draft) != "np":
        return False
    if str(draft.get("result_detail") or "").strip().casefold() == "not home":
        return True
    return any(
        isinstance(item, dict)
        and str(item.get("result") or "").strip().casefold() == "np"
        and str(item.get("detail") or "").strip().casefold() == "not home"
        for item in (draft.get("product_results") or {}).values()
    )
