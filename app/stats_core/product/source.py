from __future__ import annotations

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


class ProductCloseSource(_BaseProductCloseSource):
    """Product Close Rates Tableau source with explicit market ownership."""

    def __init__(self, config=None, fallback_markets=None):
        super().__init__(config)
        self.fallback_markets = [
            str(value).strip() for value in (fallback_markets or []) if str(value).strip()
        ]

    def _query_market_csv(
        self, base, token, site_id, view_id, start, end,
        market=None, include_all_columns=False,
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
            params["includeAllColumns"] = "true"
        query = _base.urllib.parse.urlencode(params, quote_via=_base.urllib.parse.quote)
        status, raw = self._request(
            f"{base}/sites/{site_id}/views/{view_id}/data?{query}", token=token
        )
        if status != 200:
            label = market or "all markets"
            raise _base.TableauError(
                f"Tableau data request failed (HTTP {status}) for "
                f"{TABLEAU_VIEW_PATH}, {label}, {start} to {end}."
            )
        return raw.decode("utf-8-sig", errors="replace")

    def fetch_products(self, start=None, end=None, market=None):
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
            csv_text = self._query_market_csv(base, token, site_id, view_id, start, end, market=market)
        finally:
            self.signout(base, token)
        rows = parse_product_rows(csv_text)
        if not rows:
            raise _base.TableauError(
                f"Close Rate by Product returned no tracked products for {market}, {start} to {end}."
            )
        return start, end, rows

    def fetch_markets(self):
        today = date.today()
        start = date(today.year, 1, 1).isoformat()
        end = today.isoformat()
        base, token, site_id = self.signin()
        try:
            view_id = self._view_id(base, token, site_id)
            csv_text = self._query_market_csv(
                base, token, site_id, view_id, start, end,
                market=None, include_all_columns=True,
            )
        finally:
            self.signout(base, token)
        reader = _base.csv.DictReader(_base.io.StringIO(csv_text))
        headers = reader.fieldnames or []
        market_col = _base.find_column(headers, MARKET_COLUMN_ALIASES)
        if market_col:
            values = {
                str(row.get(market_col) or "").strip()
                for row in reader
                if str(row.get(market_col) or "").strip()
                and str(row.get(market_col) or "").strip().lower() != "all"
            }
            if values:
                return sorted(values, key=str.casefold)
        if self.fallback_markets:
            return sorted(list(dict.fromkeys(self.fallback_markets)), key=str.casefold)
        raise _base.TableauError(
            "The Product Close Rates report did not expose market choices. Columns received: "
            + (", ".join(headers) if headers else "none")
        )


TableauError = _base.TableauError
