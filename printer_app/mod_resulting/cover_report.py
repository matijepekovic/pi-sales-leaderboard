"""Normalized Olympia MOD cover projection. No Salesforce or storage dependencies."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from statistics import mean

from .contract import prices

DIVISIONS = (
    ("roof", "Roofing Division"),
    ("bath", "Bath"),
    ("siding", "Siding"),
    ("windows", "Windows"),
    ("gutters", "Gutters"),
)
COLUMN_FIELDS = (
    ("lead_source", "Lead Source"),
    ("marketer", "Marketer"),
    ("client_name", "Client Name"),
    ("sales_rep", "Sales Rep"),
    ("manager_sign", "Manager Sign"),
    ("price", "Price"),
    ("deposit", "Deposit"),
    ("cash_finance", "C/F"),
    ("product", "Product"),
    ("phone", "Phone #"),
    ("poi", "POI"),
    ("doc_signing", "Doc Signing"),
    ("sold_at", "% Sold At"),
)
SUMMARY_FIELDS = (
    "leads", "pitched", "pitch_pct", "closing_pct", "day_total", "dpl",
)
TOTAL_FIELDS = ("avg_job_pct", "average_sale", "average_deposit",
                "sales", "reps_paid", "nra", "mod", "date")
EDITABLE_ROW_FIELDS = {key for key, _ in COLUMN_FIELDS}


def has_result(draft):
    """A Salesforce result may be per-product even when main Dispo is blank."""
    return bool(str(draft.get("dispo") or "").strip() or any(
        str(item.get("result") or "").strip()
        for item in (draft.get("product_results") or {}).values()
        if isinstance(item, dict)
    ))


def division_for(work_type):
    """Only the work type determines section membership, never sold product."""
    name = str(work_type or "").strip().casefold()
    if "roof" in name:
        return "roof"
    if "bath" in name:
        return "bath"
    if "sid" in name:
        return "siding"
    if "window" in name:
        return "windows"
    if "gutter" in name:
        return "gutters"
    return None


def _decimal(value):
    value = str(value if value is not None else "").strip()
    if not value:
        return None
    value = value.replace(",", "").replace("$", "")
    try:
        result = Decimal(value)
    except (ValueError, InvalidOperation):
        return None
    return result if result.is_finite() else None


def _currency(value):
    return ("$" + format(value, ",.0f")) if value is not None else ""


def _percent(value):
    return (format(value * 100, ".0f") + "%") if value is not None else ""


def _number(value):
    return str(value)


def _sold(draft):
    """Keep source sale details, including independently sold products."""
    result = {}
    for product, entry in (draft.get("sale_products") or {}).items():
        if isinstance(entry, dict):
            amount = _decimal(entry.get("price"))
            if amount is not None and amount > 0:
                result[product] = entry
    for product, entry in (draft.get("product_results") or {}).items():
        if isinstance(entry, dict) and str(entry.get("result") or "").casefold() in ("sale",):
            amount = _decimal(entry.get("price"))
            if amount is not None and amount > 0 and product not in result:
                result[product] = entry
    return result


def _first_name(name):
    text = str(name or "").strip()
    return text.split()[0] if text else ""


def _sales_rep(names):
    return " / ".join(_first_name(name) for name in names if str(name or "").strip())


def _row(work_order_id, snapshot, draft):
    sales = _sold(draft)
    amounts = [_decimal(item.get("price")) for item in sales.values()]
    sold_price = sum(amounts, Decimal(0)) if amounts else None
    if sold_price is None and str(draft.get("dispo") or "").casefold() == "sale":
        sold_price = _decimal(draft.get("final_price_override"))

    deposits = [_decimal(item.get("deposit")) for item in sales.values()]
    deposit = sum(deposits, Decimal(0)) if deposits and all(v is not None for v in deposits) else None
    if deposit is None:
        deposit = _decimal(str(draft.get("deposit_override") or "").split("/", 1)[0])

    start = _decimal(draft.get("start_price_override"))
    if start is None:
        start = _decimal(prices(draft.get("numbers", ""))["highest"])
    ratio = sold_price / start if sold_price is not None and start and start > 0 else None
    return {
        "id": work_order_id,
        "lead_source": str(snapshot.get("source") or ""),
        "marketer": str(snapshot.get("canvass_set_by") or snapshot.get("set_by") or ""),
        "client_name": str(snapshot.get("lead_name") or ""),
        "sales_rep": _sales_rep(snapshot.get("assigned_service_resources") or ()),
        "manager_sign": "",
        "price": _currency(sold_price),
        "deposit": _currency(deposit),
        "cash_finance": "",
        "product": "/".join(str(name).strip()[0].upper() for name in sales if str(name).strip()),
        "phone": str(snapshot.get("phone") or ""),
        "poi": "",
        "doc_signing": "Yes" if draft.get("docs") else "",
        "sold_at": _percent(ratio),
    }


def _sale(draft):
    return str(draft.get("dispo") or "").casefold() == "sale" or bool(_sold(draft))


def _summary(report, counts):
    """Calculate only supported figures; unmapped fields stay blank."""
    total_price = total_deposit = Decimal(0)
    all_ratios = []
    all_sales = all_reps = 0
    grand = dict.fromkeys(SUMMARY_FIELDS, "")
    grand_leads = grand_pitched = grand_sales = grand_nra = 0
    for section in report["sections"]:
        key = section["key"]
        info = counts.get(key, {})
        leads = info.get("leads", 0)
        pitched = info.get("pitched", 0)
        sales = info.get("sales", 0)
        nra = info.get("nra", 0)
        amount = sum((_decimal(row["price"]) or Decimal(0) for row in section["rows"]), Decimal(0))
        deposits = sum((_decimal(row["deposit"]) or Decimal(0) for row in section["rows"]), Decimal(0))
        total_price += amount
        total_deposit += deposits
        all_sales += sales
        all_reps += sum(len([v for v in str(row["sales_rep"]).split("/") if v.strip()])
                        for row in section["rows"])
        for row in section["rows"]:
            ratio_text = str(row["sold_at"]).strip().rstrip("%")
            ratio = _decimal(ratio_text)
            if ratio is not None:
                all_ratios.append(ratio)
        section["summary"] = {
            "leads": _number(leads),
            "pitched": _number(pitched),
            "pitch_pct": _percent(Decimal(pitched) / leads if leads else None),
            "closing_pct": _percent(Decimal(sales) / leads if leads else None),
            "day_total": _currency(amount),
            "dpl": _currency(amount / leads if leads else Decimal(0)),
        }
        grand_leads += leads
        grand_pitched += pitched
        grand_sales += sales
        grand_nra += nra
    grand.update(
        leads=_number(grand_leads),
        pitched=_number(grand_pitched),
        pitch_pct=_percent(Decimal(grand_pitched) / grand_leads if grand_leads else None),
        closing_pct=_percent(Decimal(grand_sales) / grand_leads if grand_leads else None),
        day_total=_currency(total_price),
        dpl=_currency(total_price / grand_leads if grand_leads else Decimal(0)),
    )
    report["grand"] = grand
    report["totals"] = {
        "avg_job_pct": _percent(mean(all_ratios) / 100) if all_ratios else "",
        "average_sale": _currency(total_price / all_sales if all_sales else None),
        "average_deposit": _currency(total_deposit / all_sales if all_sales else None),
        "sales": _number(all_sales),
        "reps_paid": _number(all_reps),
        "nra": _number(grand_nra),
        "mod": report["mod"],
        "date": report["date"],
    }


def project_cover(day, sheets, mod_name=""):
    """Create approved report from saved normalized MOD cards, not fresh Salesforce."""
    sections = [{"key": key, "title": title, "rows": []} for key, title in DIVISIONS]
    by_key = {section["key"]: section for section in sections}
    counts = {key: {"leads": 0, "pitched": 0, "sales": 0, "nra": 0} for key, _ in DIVISIONS}
    unknown = []
    for item in sheets:
        snapshot = item["snapshot"]
        draft = item["draft"]
        key = division_for(snapshot.get("work_type"))
        if key is None:
            unknown.append(str(snapshot.get("work_type") or "Unspecified"))
            continue
        info = counts[key]
        info["leads"] += 1
        disposition = str(draft.get("dispo") or "").strip().casefold()
        if disposition in ("sale", "pns"):
            info["pitched"] += 1
        if disposition == "nra":
            info["nra"] += 1
        if _sale(draft):
            info["sales"] += 1
            by_key[key]["rows"].append(_row(item["work_order_id"], snapshot, draft))
    if unknown:
        # Never silently classify an unknown Salesforce Work Type as another division.
        raise ValueError("Unmapped Work Type(s) for OLY Cover: " + ", ".join(sorted(set(unknown))))
    from datetime import date
    report = {
        "day": day, "mod": str(mod_name or ""),
        "date": date.fromisoformat(day).strftime("%A, %B %-d, %Y"),
        "sections": sections, "counts": counts, "grand": {}, "totals": {},
    }
    _summary(report, counts)
    return report


def apply_edits(report, edits):
    """Use a sparse user-owned editing overlay; never write to MOD drafts."""
    if not isinstance(edits, dict) or set(edits) - {"rows", "summary", "grand", "totals", "manual_rows", "hidden"}:
        raise ValueError("Invalid cover edits.")
    result = deepcopy(report)
    sections = {section["key"]: section for section in result["sections"]}
    rows = {row["id"]: row for section in result["sections"] for row in section["rows"]}
    changes = edits.get("rows", {})
    if not isinstance(changes, dict):
        raise ValueError("Invalid cover row edits.")
    for key, fields in changes.items():
        if key not in rows or not isinstance(fields, dict) or set(fields) - EDITABLE_ROW_FIELDS:
            raise ValueError("Invalid cover row edit.")
        for field, value in fields.items():
            if not isinstance(value, str) or len(value) > 160:
                raise ValueError("Invalid cover cell value.")
            rows[key][field] = value

    hidden = edits.get("hidden", [])
    if not isinstance(hidden, list) or any(key not in rows for key in hidden):
        raise ValueError("Invalid removed cover row.")
    for section in result["sections"]:
        section["rows"] = [row for row in section["rows"] if row["id"] not in hidden]

    manual = edits.get("manual_rows", [])
    if not isinstance(manual, list) or len(manual) > 200:
        raise ValueError("Invalid manually added rows.")
    seen = set(rows)
    for row in manual:
        if not isinstance(row, dict) or set(row) - (EDITABLE_ROW_FIELDS | {"id", "division"}):
            raise ValueError("Invalid manual cover row.")
        ident = row.get("id")
        division = row.get("division")
        if not isinstance(ident, str) or not ident.startswith("manual:") or len(ident) > 80 or ident in seen or division not in sections:
            raise ValueError("Invalid manual cover row identity.")
        seen.add(ident)
        data = {"id": ident}
        for field, _ in COLUMN_FIELDS:
            value = row.get(field, "")
            if not isinstance(value, str) or len(value) > 160:
                raise ValueError("Invalid manual cover cell.")
            data[field] = value
        sections[division]["rows"].append(data)

    # Changes to prices and deposits affect computed daily totals unless the
    # corresponding summary cell has been explicitly edited.
    counts = deepcopy(report["counts"])
    for section in result["sections"]:
        key = section["key"]
        counts[key]["sales"] = len(section["rows"])
        manual = (edits.get("summary") or {}).get(key, {})
        for field in ("leads", "pitched"):
            numeric = _decimal(manual.get(field)) if field in manual else None
            if numeric is not None and numeric >= 0 and numeric == numeric.to_integral_value():
                counts[key][field] = int(numeric)
    _summary(result, counts)
    for field_name, allowed in (("summary", set(SUMMARY_FIELDS)),
                                ("grand", set(SUMMARY_FIELDS)),
                                ("totals", set(TOTAL_FIELDS))):
        values = edits.get(field_name, {})
        if not isinstance(values, dict):
            raise ValueError("Invalid cover summary edits.")
        if field_name == "summary":
            for key, mapping in values.items():
                if key not in sections or not isinstance(mapping, dict) or set(mapping) - allowed:
                    raise ValueError("Invalid cover division summary.")
                for field, value in mapping.items():
                    if not isinstance(value, str) or len(value) > 160:
                        raise ValueError("Invalid cover summary value.")
                    sections[key]["summary"][field] = value
        else:
            if set(values) - allowed or any(not isinstance(v, str) or len(v) > 160
                                           for v in values.values()):
                raise ValueError("Invalid cover total field.")
            result[field_name].update(values)
    return result
