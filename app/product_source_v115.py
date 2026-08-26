"""v115 Product Close Rates source helpers.

The existing v75 connector is pinned to Olympia. This wrapper keeps the same
workbook, worksheet and parser, but lets the appliance choose any market that
Tableau exposes and lets temporary date overrides request an explicit range.
"""
from datetime import date

from sources import tableau_v36_base as _base
from sources.tableau_products import (
    ProductCloseSource as _BaseProductCloseSource,
    TABLEAU_MARKET_FIELD,
    TABLEAU_VIEW_PATH,
    parse_product_rows,
)

DEFAULT_MARKET = "Olympia"
MARKET_COLUMN_ALIASES = ["leadmarketc", "leadmarket", "market"]


def selected_market(settings=None):
    settings = settings or {}
    return str(settings.get("product_market") or DEFAULT_MARKET).strip() or DEFAULT_MARKET


class ProductCloseSourceV115(_BaseProductCloseSource):
    """Same fixed Tableau product report, with a configurable market filter."""

    def _query_market_csv(
        self,
        base,
        token,
        site_id,
        view_id,
        start,
        end,
        market=None,
        include_all_columns=False,
    ):
        params = {
            "maxAge": "1",
            f"vf_{_base.TABLEAU_START_FIELD}": start,
            f"vf_{_base.TABLEAU_END_FIELD}": end,
        }
        market = str(market or "").strip()
        if market:
            params[f"vf_{TABLEAU_MARKET_FIELD}"] = market
        if include_all_columns:
            # Tableau's view-data endpoint can expose dimensions that are used
            # as filters but are not visible in the compact two-column sheet.
            params["includeAllColumns"] = "true"

        query = _base.urllib.parse.urlencode(
            params, quote_via=_base.urllib.parse.quote
        )
        status, raw = self._request(
            f"{base}/sites/{site_id}/views/{view_id}/data?{query}",
            token=token,
        )
        if status != 200:
            label = market or "all markets"
            raise _base.TableauError(
                f"Tableau data request failed (HTTP {status}) for "
                f"{TABLEAU_VIEW_PATH}, {label}, {start} to {end}."
            )
        return raw.decode("utf-8-sig", errors="replace")

    def fetch_products(self, start=None, end=None, market=None):
        """Return (start, end, rows) for one explicit or saved market."""
        if not start or not end:
            resolved_start, resolved_end = _base.resolve_dates(self.config)
            start = start or resolved_start
            end = end or resolved_end
        market = str(market or selected_market(self.config)).strip()
        if not market:
            raise _base.TableauError("Choose a product market first.")

        base, token, site_id = self.signin()
        try:
            view_id = self._view_id(base, token, site_id)
            csv_text = self._query_market_csv(
                base, token, site_id, view_id, start, end, market=market
            )
        finally:
            self.signout(base, token)

        rows = parse_product_rows(csv_text)
        if not rows:
            raise _base.TableauError(
                f"Close Rate by Product returned no tracked products for "
                f"{market}, {start} to {end}."
            )
        return start, end, rows

    def fetch_markets(self):
        """Return current Tableau market choices for the dropdown.

        Use year-to-date for discovery so a market with no activity this month
        does not disappear from the selector. No market filter is sent.
        """
        today = date.today()
        start = date(today.year, 1, 1).isoformat()
        end = today.isoformat()

        base, token, site_id = self.signin()
        try:
            view_id = self._view_id(base, token, site_id)
            csv_text = self._query_market_csv(
                base,
                token,
                site_id,
                view_id,
                start,
                end,
                market=None,
                include_all_columns=True,
            )
        finally:
            self.signout(base, token)

        reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
        headers = reader.fieldnames or []
        market_col = _base.find_column(headers, MARKET_COLUMN_ALIASES)
        if not market_col:
            raise _base.TableauError(
                "The Product Close Rates report did not expose its market field "
                "for the dropdown. Columns received: "
                + (", ".join(headers) if headers else "none")
            )

        values = {
            str(row.get(market_col) or "").strip()
            for row in reader
            if str(row.get(market_col) or "").strip()
            and str(row.get(market_col) or "").strip().lower() != "all"
        }
        if not values:
            raise _base.TableauError(
                "The Product Close Rates report returned no market choices."
            )
        return sorted(values, key=str.casefold)


TableauError = _base.TableauError
