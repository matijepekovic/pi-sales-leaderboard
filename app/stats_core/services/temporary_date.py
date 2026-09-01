"""Temporary display-only date override over normalized reports."""
from __future__ import annotations

from datetime import date
import threading
import time

from stats_core.errors import BusyError, ValidationError
from stats_core.repositories.data_catalog import PRODUCT_REPORT_ID, REP_REPORT_ID


class TemporaryDateService:
    def __init__(self, repos, rep_refresh, adapters):
        self.repos = repos
        self.rep_refresh = rep_refresh
        self.adapters = dict(adapters or {})
        self._lock = threading.RLock()
        self._pull_lock = threading.Lock()
        self._state = {
            "rows": None, "product_rows": None, "product_market": "",
            "until": 0.0, "mode": "", "start": "", "end": "", "minutes": 0,
        }

    def _clear_locked(self):
        self._state.update({
            "rows": None, "product_rows": None, "product_market": "",
            "until": 0.0, "mode": "", "start": "", "end": "", "minutes": 0,
        })

    def _expire_locked(self, now=None):
        now = time.time() if now is None else now
        if self._state["rows"] is not None and now >= float(self._state["until"] or 0):
            self._clear_locked()

    def rep_rows(self):
        with self._lock:
            self._expire_locked()
            return None if self._state["rows"] is None else [dict(row) for row in self._state["rows"]]

    def product_payload(self):
        with self._lock:
            self._expire_locked()
            if self._state["rows"] is None or self._state["product_rows"] is None:
                return None
            return {
                "rows": [dict(row) for row in self._state["product_rows"]],
                "market": self._state["product_market"], "start": self._state["start"],
                "end": self._state["end"],
                "seconds_left": max(0, int(float(self._state["until"] or 0) - time.time())),
            }

    def replace_product_rows(self, rows, market, expected_start=None, expected_end=None):
        with self._lock:
            self._expire_locked()
            if self._state["rows"] is None: return False
            if expected_start and str(expected_start) != str(self._state["start"]): return False
            if expected_end and str(expected_end) != str(self._state["end"]): return False
            self._state["product_rows"] = [dict(row) for row in (rows or [])]
            self._state["product_market"] = str(market or "").strip()
            return True

    def state(self):
        with self._lock:
            now = time.time(); self._expire_locked(now); active = self._state["rows"] is not None
            return {
                "active": active, "mode": self._state["mode"] if active else "",
                "start": self._state["start"] if active else "", "end": self._state["end"] if active else "",
                "minutes": int(self._state["minutes"] or 0) if active else 0,
                "seconds_left": max(0, int(float(self._state["until"] or 0) - now)) if active else 0,
                "rows": len(self._state["rows"] or []) if active else 0,
                "products": len(self._state["product_rows"] or []) if active else 0,
                "product_market": self._state["product_market"] if active else "",
            }

    @staticmethod
    def _parse_date(value, label):
        try: return date.fromisoformat(str(value or "").strip())
        except Exception as exc: raise ValidationError(f"Choose a valid {label} date.") from exc

    def _requested_range(self, body):
        mode = str(body.get("mode") or "").strip().lower(); today = date.today()
        if mode == "ytd": return mode, date(today.year, 1, 1).isoformat(), today.isoformat()
        if mode == "custom":
            start = self._parse_date(body.get("start"), "start"); end = self._parse_date(body.get("end"), "end")
            if start > end: raise ValidationError("Start date must be before or equal to end date.")
            return mode, start.isoformat(), end.isoformat()
        raise ValidationError("Choose Year to Date or Custom Range.")

    @staticmethod
    def _requested_minutes(body):
        try: minutes = int(body.get("minutes"))
        except Exception as exc: raise ValidationError("Enter a duration from 1 to 60 minutes.") from exc
        if not 1 <= minutes <= 60: raise ValidationError("Enter a duration from 1 to 60 minutes.")
        return minutes

    def _fallback_markets(self):
        return sorted({str(row.get("home_branch") or "").strip() for row in self.repos.reps.list() if str(row.get("home_branch") or "").strip()}, key=str.casefold)

    def _context(self, report_id):
        settings = self.repos.settings.get(); report = self.repos.data_catalog.report(report_id)
        if not report: raise ValidationError("Required report is not configured.")
        source = self.repos.data_catalog.source(report.get("source_id"))
        if not source: raise ValidationError("Required report source is not configured.")
        adapter = self.adapters.get(str(source.get("adapter") or ""))
        if not adapter: raise ValidationError("Required report source adapter is not available.")
        secret = self.repos.source_credentials.get(source.get("id"))
        return report, source, adapter, adapter.with_secret(settings, secret)

    @staticmethod
    def _with_dates(report, start, end):
        runtime = dict(report.get("runtime") or {})
        runtime.update({"date_mode": "custom", "date_start": start, "date_end": end})
        return dict(report, runtime=runtime)

    def activate(self, body):
        mode, start, end = self._requested_range(body); minutes = self._requested_minutes(body)
        if not self._pull_lock.acquire(blocking=False): raise BusyError("A temporary pull is already running.")
        try:
            rep_report, rep_source, rep_adapter, rep_settings = self._context(REP_REPORT_ID)
            rows, _result = self.rep_refresh.pull(rep_adapter, rep_settings, rep_source, self._with_dates(rep_report, start, end))
            if not rows: raise ValidationError("Temporary pull returned no people. Regular numbers were kept.")

            product_report, product_source, product_adapter, product_settings = self._context(PRODUCT_REPORT_ID)
            runtime = dict(product_report.get("runtime") or {})
            market = str(runtime.get("market") or "Olympia").strip() or "Olympia"
            product_result = product_adapter.pull_products(
                product_settings, product_source, product_report,
                start=start, end=end, market=market, fallback_markets=self._fallback_markets(),
            )
            product_rows = product_result["rows"]
        finally:
            self._pull_lock.release()
        with self._lock:
            self._state.update({
                "rows": list(rows), "product_rows": [dict(row) for row in product_rows],
                "product_market": market, "until": time.time() + minutes * 60,
                "mode": mode, "start": start, "end": end, "minutes": minutes,
            })
        return self.state()

    def cancel(self):
        with self._lock: self._clear_locked()
        return self.state()
