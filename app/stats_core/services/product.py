from __future__ import annotations

from stats_core.product.source import selected_market

PRODUCT_MODE = "product_close"
PRODUCT_LABEL = "Product Close Rates"


class ProductService:
    """Product payload/orchestration facade.

    Source access and refresh locking live in ProductRefreshService; persistent
    rows live in ProductRepository; screen rendering lives in ProductCloseScreen.
    """

    def __init__(self, repos, temporary_date, refresh_service):
        self.repos = repos
        self.temporary_date = temporary_date
        self.refresh_service = refresh_service

    def regular_payload(self, settings=None):
        settings = settings or self.repos.settings.get()
        rows = self.repos.products.list()
        market = str(self.repos.meta.get("product_close_market", "") or "").strip() or "Olympia"
        start = str(self.repos.meta.get("product_close_start", "") or "")
        end = str(self.repos.meta.get("product_close_end", "") or "")
        context = f"regular|{market}|{start}|{end}|{self.repos.meta.get('product_close_version','0')}"
        return {
            "rows": [dict(row, _display_context=context) for row in rows],
            "market": market, "start": start, "end": end,
            "temporary": False, "seconds_left": 0,
            "updated_at": rows[0]["updated_at"] if rows else "",
            "status": self.repos.meta.get("product_close_status", ""),
            "icons": settings.get("product_icons") or {},
        }

    def current_payload(self, settings=None):
        settings = settings or self.repos.settings.get()
        temporary = self.temporary_date.product_payload()
        if temporary is not None:
            context = (
                f"temporary|{temporary['market']}|{temporary['start']}|"
                f"{temporary['end']}|{temporary['seconds_left']}"
            )
            return {
                "rows": [dict(row, _display_context=context) for row in temporary.get("rows") or []],
                "market": temporary.get("market") or selected_market(settings),
                "start": temporary.get("start") or "", "end": temporary.get("end") or "",
                "temporary": True, "seconds_left": int(temporary.get("seconds_left") or 0),
                "updated_at": "", "status": "Temporary date override active",
                "icons": settings.get("product_icons") or {},
            }
        return self.regular_payload(settings)

    def refresh(self, settings=None, raise_errors=True):
        return self.refresh_service.refresh(settings, raise_errors=raise_errors)

    def market_choices(self, settings=None, force=False):
        return self.refresh_service.market_choices(settings, force=force)

    def set_market(self, requested):
        settings, warning = self.refresh_service.change_market(requested)
        return self.current_payload(settings), warning
