"""Temporary display-only date override."""
from __future__ import annotations

from datetime import date
import threading
import time

from stats_core.errors import BusyError, ValidationError
from stats_core.product.source import ProductCloseSource, selected_market


class TemporaryDateService:
    def __init__(self, repos, rep_refresh):
        self.repos = repos
        self.rep_refresh = rep_refresh
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
            if self._state["rows"] is None:
                return False
            if expected_start and str(expected_start) != str(self._state["start"]):
                return False
            if expected_end and str(expected_end) != str(self._state["end"]):
                return False
            self._state["product_rows"] = [dict(row) for row in (rows or [])]
            self._state["product_market"] = str(market or "").strip()
            return True

    def state(self):
        with self._lock:
            now = time.time()
            self._expire_locked(now)
            active = self._state["rows"] is not None
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
        try:
            return date.fromisoformat(str(value or "").strip())
        except Exception as exc:
            raise ValidationError(f"Choose a valid {label} date.") from exc

    def _requested_range(self, body):
        mode = str(body.get("mode") or "").strip().lower()
        today = date.today()
        if mode == "ytd":
            return mode, date(today.year, 1, 1).isoformat(), today.isoformat()
        if mode == "custom":
            start = self._parse_date(body.get("start"), "start")
            end = self._parse_date(body.get("end"), "end")
            if start > end:
                raise ValidationError("Start date must be before or equal to end date.")
            return mode, start.isoformat(), end.isoformat()
        raise ValidationError("Choose Year to Date or Custom Range.")

    @staticmethod
    def _requested_minutes(body):
        try:
            minutes = int(body.get("minutes"))
        except Exception as exc:
            raise ValidationError("Enter a duration from 1 to 60 minutes.") from exc
        if not 1 <= minutes <= 60:
            raise ValidationError("Enter a duration from 1 to 60 minutes.")
        return minutes

    def _fallback_markets(self):
        return sorted({
            str(row.get("home_branch") or "").strip()
            for row in self.repos.reps.list()
            if str(row.get("home_branch") or "").strip()
        }, key=str.casefold)

    def activate(self, body):
        mode, start, end = self._requested_range(body)
        minutes = self._requested_minutes(body)
        trial = dict(self.repos.settings.get())
        trial["data_date_mode"] = "custom"
        trial["data_date_start"] = start
        trial["data_date_end"] = end
        source = dict(trial.get("source") or {})
        source["date_start_field"] = str(source.get("date_start_field") or "Start")
        source["date_end_field"] = str(source.get("date_end_field") or "End")
        trial["source"] = source
        market = selected_market(trial)
        if not self._pull_lock.acquire(blocking=False):
            raise BusyError("A temporary pull is already running.")
        try:
            rows, _source = self.rep_refresh.pull(trial)
            if not rows:
                raise ValidationError("Temporary pull returned no people. Regular numbers were kept.")
            product_source = ProductCloseSource(trial, fallback_markets=self._fallback_markets())
            _start, _end, product_rows = product_source.fetch_products(
                start=start, end=end, market=market
            )
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
        with self._lock:
            self._clear_locked()
        return self.state()
