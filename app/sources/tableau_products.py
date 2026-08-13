"""v75 Close Rate by Product connector.

A second, independent Tableau pull that has nothing to do with the rep
leaderboard. The published worksheet is:

    RegionalSaleswFLOW/sheets/CloseRatebyProduct_1

which is a *different workbook* from the rep board's 8-SalesRepLevelData.
Tableau REST returns it in a compact two-column form:

    Product Calc (group) | Close Rate + NRAs

One row per product, with the rate as a fraction (0.1744, not 17.44).

Two things this module is careful about:

  * It never reassigns the module-level constants in tableau_v36_base. Those
    are read directly by the rep connector's own methods, and tableau.py
    already mutates one of them, so writing to them here would corrupt the
    rep pull. Every workbook-specific value is overridden per method instead.

  * It pins the market filter explicitly. Tableau REST applies a view's
    *saved* filter state, not whatever a browser happens to have selected,
    so the Olympia scope is sent on every request rather than assumed.
"""
from . import tableau_v36_base as _base


TABLEAU_WORKBOOK_CONTENT_URL = "RegionalSaleswFLOW"
TARGET_CONTENT_TAIL = "/sheets/CloseRatebyProduct_1"
TABLEAU_VIEW_PATH = f"{TABLEAU_WORKBOOK_CONTENT_URL}{TARGET_CONTENT_TAIL}"

# The filter card is titled "LEAD-Market__c" and that is also the underlying
# field key. Confirmed against the live view: this key narrows the result,
# while "LEAD-Market" is silently ignored and returns every market.
TABLEAU_MARKET_FIELD = "LEAD-Market__c"
TABLEAU_MARKET = "Olympia"

PRODUCT_COLUMN_ALIASES = ["productcalcgroup", "productcalc", "product"]
CLOSE_RATE_COLUMN_ALIASES = ["closeratenras", "closerate"]

# Only these five lines belong on the board. Anything else Tableau returns --
# Doors, Solar, Walk-In Tubs, and the "All" roll-up row -- is dropped by not
# appearing here. Aliases are matched on the normalized label so a caption
# change from "Roof" to "Roofs" does not break the pull.
PRODUCTS = {
    "bath": "Bath",
    "baths": "Bath",
    "gutter": "Gutters",
    "gutters": "Gutters",
    "roof": "Roof",
    "roofs": "Roof",
    "roofing": "Roof",
    "siding": "Siding",
    "window": "Windows",
    "windows": "Windows",
}

# Tableau hands back fractions; the rest of the app works in 0..100.
RATE_SCALE = 100.0


def parse_product_rows(csv_text):
    """Turn the two-column export into [{'product', 'close_rate'}], ranked."""
    reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
    headers = reader.fieldnames or []

    product_col = _base.find_column(headers, PRODUCT_COLUMN_ALIASES)
    rate_col = _base.find_column(headers, CLOSE_RATE_COLUMN_ALIASES)

    missing = []
    if not product_col:
        missing.append("Product Calc (group)")
    if not rate_col:
        missing.append("Close Rate + NRAs")
    if missing:
        raise _base.TableauError(
            "Close Rate by Product is missing required columns: "
            + ", ".join(missing)
            + ". Columns seen: "
            + (", ".join(headers) if headers else "none")
        )

    # Keep the largest value per product. Tableau can repeat an identical mark,
    # and these are already-finished rates, so summing them would be wrong.
    best = {}
    for row in reader:
        label = PRODUCTS.get(_base.norm(row.get(product_col)))
        if not label:
            continue
        value = _base.clean_number(row.get(rate_col))
        if value is None:
            continue
        rate = value * RATE_SCALE
        if label not in best or rate > best[label]:
            best[label] = rate

    return [
        {"product": name, "close_rate": rate}
        for name, rate in sorted(best.items(), key=lambda kv: -kv[1])
    ]


class ProductCloseSource(_base.TableauSource):
    """Reuses the base sign-in and HTTP plumbing; overrides only the target."""

    VIEW_PATH = TABLEAU_VIEW_PATH

    def _workbook_id(self, base, token, site_id):
        workbook_key = _base.urllib.parse.quote(
            TABLEAU_WORKBOOK_CONTENT_URL, safe=""
        )
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_key}?key=contentUrl",
            token=token,
        )
        if status != 200:
            raise _base.TableauError(
                f"Could not find Tableau workbook '{TABLEAU_WORKBOOK_CONTENT_URL}' "
                f"(HTTP {status}). The 'leaderboard' token may not have access to it."
            )
        try:
            workbook_id = str(
                _base.json.loads(raw).get("workbook", {}).get("id") or ""
            ).strip()
        except Exception:
            workbook_id = ""
        if not workbook_id:
            raise _base.TableauError(
                f"Tableau workbook '{TABLEAU_WORKBOOK_CONTENT_URL}' returned no id."
            )
        return workbook_id

    def _view_id(self, base, token, site_id):
        workbook_id = self._workbook_id(base, token, site_id)
        status, raw = self._request(
            f"{base}/sites/{site_id}/workbooks/{workbook_id}/views",
            token=token,
        )
        if status != 200:
            raise _base.TableauError(
                f"Could not list views for {TABLEAU_WORKBOOK_CONTENT_URL}."
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

        available = "; ".join(
            f"{str(v.get('name') or '?').strip()} [{str(v.get('contentUrl') or '').strip()}]"
            for v in views[:50]
        )
        raise _base.TableauError(
            f"Tableau did not expose {TABLEAU_VIEW_PATH}. Available views: "
            + (available or "none")
        )

    def _query_product_csv(self, base, token, site_id, view_id, start, end):
        params = {
            "maxAge": "1",
            f"vf_{_base.TABLEAU_START_FIELD}": start,
            f"vf_{_base.TABLEAU_END_FIELD}": end,
            f"vf_{TABLEAU_MARKET_FIELD}": TABLEAU_MARKET,
        }
        # %20 rather than '+' in field names, as Tableau documents view filters.
        query = _base.urllib.parse.urlencode(
            params, quote_via=_base.urllib.parse.quote
        )
        status, raw = self._request(
            f"{base}/sites/{site_id}/views/{view_id}/data?{query}",
            token=token,
        )
        if status != 200:
            raise _base.TableauError(
                f"Tableau data request failed (HTTP {status}) for "
                f"{TABLEAU_VIEW_PATH}, {TABLEAU_MARKET}, {start} to {end}."
            )
        return raw.decode("utf-8-sig", errors="replace")

    def fetch_products(self):
        """Sign in, pull, parse. Returns (start, end, rows)."""
        start, end = _base.resolve_dates(self.config)
        base, token, site_id = self.signin()
        try:
            view_id = self._view_id(base, token, site_id)
            csv_text = self._query_product_csv(
                base, token, site_id, view_id, start, end
            )
        finally:
            self.signout(base, token)

        rows = parse_product_rows(csv_text)
        if not rows:
            raise _base.TableauError(
                f"Close Rate by Product returned no tracked products for "
                f"{TABLEAU_MARKET}, {start} to {end}."
            )
        return start, end, rows


TableauError = _base.TableauError
