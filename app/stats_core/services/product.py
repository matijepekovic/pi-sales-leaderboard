"""Product Close Rates domain service."""
from __future__ import annotations

import json
import threading
import time

from product_source_v115 import ProductCloseSourceV115, selected_market
from stats_core.errors import BusyError, ValidationError

PRODUCT_MODE = "product_close"
PRODUCT_LABEL = "Product Close Rates"
_MARKET_CACHE_SECONDS = 6 * 60 * 60


class ProductService:
    def __init__(self, repos, temporary_date):
        self.repos = repos
        self.temporary_date = temporary_date
        self._refresh_lock = threading.Lock()

    def _store_regular(self, rows, start, end, market):
        self.repos.products.replace(rows)
        now_text = time.strftime("%Y-%m-%d %H:%M:%S")
        self.repos.meta.set("product_close_start", start)
        self.repos.meta.set("product_close_end", end)
        self.repos.meta.set("product_close_market", market)
        self.repos.meta.set(
            "product_close_status",
            f"{market} — {len(rows)} products, {start} to {end} — updated {now_text}",
        )
        self.repos.meta.bump("product_close_version")
        return now_text

    def regular_payload(self, settings=None):
        settings = settings or self.repos.settings.get()
        rows = self.repos.products.list()
        market = str(self.repos.meta.get("product_close_market", "") or "").strip() or "Olympia"
        start = str(self.repos.meta.get("product_close_start", "") or "")
        end = str(self.repos.meta.get("product_close_end", "") or "")
        context = f"regular|{market}|{start}|{end}|{self.repos.meta.get('product_close_version','0')}"
        decorated = [dict(row, _display_context=context) for row in rows]
        return {
            "rows": decorated,
            "market": market,
            "start": start,
            "end": end,
            "temporary": False,
            "seconds_left": 0,
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
                "start": temporary.get("start") or "",
                "end": temporary.get("end") or "",
                "temporary": True,
                "seconds_left": int(temporary.get("seconds_left") or 0),
                "updated_at": "",
                "status": "Temporary date override active",
                "icons": settings.get("product_icons") or {},
            }
        return self.regular_payload(settings)

    def _pull_regular_and_temporary(self, settings):
        market = selected_market(settings)
        source = ProductCloseSourceV115(settings)
        start, end, rows = source.fetch_products(market=market)
        state = self.temporary_date.state()
        temporary_rows = None
        if state.get("active"):
            _ts, _te, temporary_rows = source.fetch_products(
                start=state["start"], end=state["end"], market=market
            )
        return {
            "market": market,
            "start": start,
            "end": end,
            "rows": rows,
            "temporary_state": state,
            "temporary_rows": temporary_rows,
        }

    def _commit_pulled(self, result):
        self._store_regular(result["rows"], result["start"], result["end"], result["market"])
        state = result.get("temporary_state") or {}
        if state.get("active") and result.get("temporary_rows") is not None:
            self.temporary_date.replace_product_rows(
                result["temporary_rows"],
                result["market"],
                expected_start=state.get("start"),
                expected_end=state.get("end"),
            )

    def refresh(self, settings=None, raise_errors=True):
        settings = settings or self.repos.settings.get()
        if not str(settings.get("tableau_pat_secret") or "").strip():
            if raise_errors:
                raise ValidationError("Enter the Tableau PAT secret first.")
            self.repos.meta.set("product_close_status", "Product close rate pull failed: Tableau PAT is not configured")
            return False
        if not self._refresh_lock.acquire(blocking=False):
            if raise_errors:
                raise BusyError("A product refresh is already running.")
            return False
        try:
            try:
                result = self._pull_regular_and_temporary(settings)
                self._commit_pulled(result)
                return True
            except Exception as exc:
                self.repos.meta.set("product_close_status", f"Product close rate pull failed: {exc}")
                if raise_errors:
                    raise
                return False
        finally:
            self._refresh_lock.release()

    def _cached_markets(self):
        try:
            values = json.loads(str(self.repos.meta.get("product_markets_v115", "[]") or "[]"))
        except Exception:
            values = []
        values = [str(value).strip() for value in values if str(value).strip()]
        try:
            cached_at = float(self.repos.meta.get("product_markets_v115_at", "0") or 0)
        except Exception:
            cached_at = 0.0
        return list(dict.fromkeys(values)), cached_at

    def market_choices(self, settings=None, force=False):
        settings = settings or self.repos.settings.get()
        selected = selected_market(settings)
        cached, cached_at = self._cached_markets()
        fresh = cached and time.time() - cached_at < _MARKET_CACHE_SECONDS
        warning = ""
        if force or not fresh:
            try:
                cached = ProductCloseSourceV115(settings).fetch_markets()
                cached_at = time.time()
                self.repos.meta.set("product_markets_v115", json.dumps(cached))
                self.repos.meta.set("product_markets_v115_at", cached_at)
            except Exception as exc:
                warning = str(exc)
        values = list(cached)
        if selected and selected.casefold() not in {value.casefold() for value in values}:
            values.append(selected)
        if not values:
            values = [selected or "Olympia"]
        return sorted(list(dict.fromkeys(values)), key=str.casefold), warning

    def set_market(self, requested):
        requested = str(requested or "").strip()
        if not requested:
            raise ValidationError("Choose a market.")
        settings = self.repos.settings.get()
        choices, warning = self.market_choices(settings)
        canonical = next((value for value in choices if value.casefold() == requested.casefold()), "")
        if not canonical:
            raise ValidationError("Choose a market from the dropdown.")
        if not self._refresh_lock.acquire(blocking=False):
            raise BusyError("A product refresh is already running.")
        try:
            candidate = dict(settings)
            candidate["product_market"] = canonical
            result = self._pull_regular_and_temporary(candidate)
            self.repos.settings.save(candidate)
            self.repos.meta.bump("settings_version")
            self._commit_pulled(result)
            return self.current_payload(candidate), warning
        finally:
            self._refresh_lock.release()

    def mode_payload(self):
        product = self.current_payload()
        return {
            "mode": PRODUCT_MODE,
            "mode_label": PRODUCT_LABEL,
            "metrics": [],
            "rows": product["rows"],
            "teams": [],
            "product_market": product["market"],
            "product_start": product["start"],
            "product_end": product["end"],
            "product_icons": product["icons"],
            "product_temporary": product["temporary"],
            "product_seconds_left": product["seconds_left"],
        }
