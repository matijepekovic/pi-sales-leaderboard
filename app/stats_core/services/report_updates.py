"""Automatic update timing for saved normalized Reports."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta


class ReportUpdateService:
    """Refresh saved Reports when their configured interval becomes due."""

    CHECK_SECONDS = 15
    _STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

    def __init__(self, reports):
        self.reports = reports
        self._last_attempt = {}
        self._lock = threading.Lock()
        self._started = False

    @staticmethod
    def _interval(report):
        runtime = report.get("runtime") if isinstance(report.get("runtime"), dict) else {}
        try:
            return max(0, int(runtime.get("update_interval_minutes") or 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _last_refresh(cls, report):
        value = str(report.get("last_refresh") or "").strip()
        if not value:
            return None
        try:
            return datetime.strptime(value, cls._STAMP_FORMAT)
        except ValueError:
            return None

    def run_due(self, now=None):
        """Run one due-check pass and return the attempted Report ids."""
        now = now or datetime.now()
        attempted = []
        for report in self.reports.list():
            interval = self._interval(report)
            report_id = str(report.get("id") or "").strip()
            if not report_id or interval <= 0:
                continue
            reference = self._last_refresh(report)
            previous_attempt = self._last_attempt.get(report_id)
            if previous_attempt and (reference is None or previous_attempt > reference):
                reference = previous_attempt
            if reference is not None and now < reference + timedelta(minutes=interval):
                continue
            self._last_attempt[report_id] = now
            attempted.append(report_id)
            try:
                self.reports.refresh(report_id)
            except Exception:
                # A failed pull waits for the Report's interval before retrying.
                # Manual Refresh continues to return the detailed error to the UI.
                continue
        return attempted

    def _worker(self):
        while True:
            try:
                self.run_due()
            except Exception:
                # Catalog or storage failures are retried on the next pass;
                # one bad check must not permanently stop automatic updates.
                pass
            time.sleep(self.CHECK_SECONDS)

    def start(self):
        with self._lock:
            if self._started:
                return False
            self._started = True
            threading.Thread(
                target=self._worker,
                name="saved-report-updates",
                daemon=True,
            ).start()
            return True
