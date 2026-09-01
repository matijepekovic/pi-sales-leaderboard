from __future__ import annotations

import json
import threading
import time

from stats_core.errors import BusyError, ValidationError
from stats_core.repositories.data_catalog import PRODUCT_REPORT_ID

_MARKET_CACHE_SECONDS = 6 * 60 * 60
_DEFAULT_MARKET = "Olympia"


class ProductRefreshService:
    def __init__(self, repos, temporary_date, adapters):
        self.repos = repos
        self.temporary_date = temporary_date
        self.adapters = dict(adapters or {})
        self._lock = threading.Lock()

    def _fallback_markets(self):
        return sorted({
            str(row.get("home_branch") or "").strip()
            for row in self.repos.reps.list()
            if str(row.get("home_branch") or "").strip()
        }, key=str.casefold)

    def _context(self):
        settings = self.repos.settings.get()
        report = self.repos.data_catalog.report(PRODUCT_REPORT_ID)
        if not report:
            raise ValidationError("Product report is not configured.")
        source = self.repos.data_catalog.source(report.get("source_id"))
        if not source:
            raise ValidationError("Product report source is not configured.")
        adapter = self.adapters.get(str(source.get("adapter") or ""))
        if not adapter:
            raise ValidationError("Product report source adapter is not available.")
        secret = self.repos.source_credentials.get(source.get("id"))
        app_settings = adapter.with_secret(settings, secret)
        return report, source, adapter, app_settings, secret

    @staticmethod
    def _selected_market(report):
        runtime = report.get("runtime") if isinstance(report.get("runtime"), dict) else {}
        return str(runtime.get("market") or _DEFAULT_MARKET).strip() or _DEFAULT_MARKET

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

    def pull(self):
        report, source, adapter, app_settings, _secret = self._context()
        market = self._selected_market(report)
        regular = adapter.pull_products(
            app_settings, source, report, market=market,
            fallback_markets=self._fallback_markets(),
        )
        state = self.temporary_date.state()
        temporary_rows = None
        if state.get("active"):
            temporary = adapter.pull_products(
                app_settings, source, report,
                start=state["start"], end=state["end"], market=market,
                fallback_markets=self._fallback_markets(),
            )
            temporary_rows = temporary["rows"]
        return {
            "market": market, "start": regular["start"], "end": regular["end"],
            "rows": regular["rows"], "temporary_state": state,
            "temporary_rows": temporary_rows,
        }

    def commit(self, result):
        self._store_regular(result["rows"], result["start"], result["end"], result["market"])
        state = result.get("temporary_state") or {}
        if state.get("active") and result.get("temporary_rows") is not None:
            self.temporary_date.replace_product_rows(
                result["temporary_rows"], result["market"],
                expected_start=state.get("start"), expected_end=state.get("end"),
            )

    def refresh(self, settings=None, raise_errors=True):
        del settings
        try:
            _report, _source, _adapter, _app_settings, secret = self._context()
        except Exception:
            if raise_errors: raise
            return False
        if not str(secret or "").strip():
            if raise_errors: raise ValidationError("Enter the source credential first.")
            self.repos.meta.set("product_close_status", "Product close rate pull failed: source credential is not configured")
            return False
        if not self._lock.acquire(blocking=False):
            if raise_errors: raise BusyError("A product refresh is already running.")
            return False
        try:
            try:
                self.commit(self.pull())
                return True
            except Exception as exc:
                self.repos.meta.set("product_close_status", f"Product close rate pull failed: {exc}")
                if raise_errors: raise
                return False
        finally:
            self._lock.release()

    def _cached_markets(self):
        try: values = json.loads(str(self.repos.meta.get("product_markets", "[]") or "[]"))
        except Exception: values = []
        values = [str(value).strip() for value in values if str(value).strip()]
        try: cached_at = float(self.repos.meta.get("product_markets_at", "0") or 0)
        except Exception: cached_at = 0.0
        return list(dict.fromkeys(values)), cached_at

    def market_choices(self, settings=None, force=False):
        del settings
        report, source, adapter, app_settings, _secret = self._context()
        selected = self._selected_market(report)
        cached, cached_at = self._cached_markets()
        fresh = cached and time.time() - cached_at < _MARKET_CACHE_SECONDS
        warning = ""
        if force or not fresh:
            try:
                cached = adapter.product_markets(
                    app_settings, source, report, fallback_markets=self._fallback_markets()
                )
                cached_at = time.time()
                self.repos.meta.set("product_markets", json.dumps(cached))
                self.repos.meta.set("product_markets_at", cached_at)
            except Exception as exc:
                warning = str(exc)
        values = list(cached)
        if selected and selected.casefold() not in {value.casefold() for value in values}:
            values.append(selected)
        if not values: values = [selected or _DEFAULT_MARKET]
        return sorted(list(dict.fromkeys(values)), key=str.casefold), warning

    def change_market(self, requested):
        requested = str(requested or "").strip()
        if not requested: raise ValidationError("Choose a market.")
        choices, warning = self.market_choices()
        canonical = next((value for value in choices if value.casefold() == requested.casefold()), "")
        if not canonical: raise ValidationError("Choose a market from the dropdown.")
        if not self._lock.acquire(blocking=False): raise BusyError("A product refresh is already running.")
        try:
            report, _source, _adapter, _app_settings, _secret = self._context()
            catalog = self.repos.data_catalog.get()
            runtime = dict(report.get("runtime") or {})
            runtime["market"] = canonical
            updated = dict(report, runtime=runtime)
            catalog["reports"] = [
                updated if str(row.get("id")) == PRODUCT_REPORT_ID else row
                for row in catalog["reports"]
            ]
            self.repos.data_catalog.save(catalog)
            self.repos.meta.bump("settings_version")
            self.commit(self.pull())
            return self.repos.settings.get(), warning
        finally:
            self._lock.release()
