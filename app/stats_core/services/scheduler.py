"""Scheduling only: decide when to refresh normalized reports."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from stats_core.repositories.data_catalog import PRODUCT_REPORT_ID, REP_REPORT_ID


class SchedulerService:
    SCHEDULE_HOURS = (6, 14)
    STARTUP_GRACE_MINUTES = 15

    def __init__(self, repos, reports):
        self.repos = repos
        self.reports = reports
        self._lock = threading.Lock()
        self._started = False

    @staticmethod
    def _slot_key(dt): return dt.strftime("%Y-%m-%dT%H")
    def _slots(self, now): return [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in self.SCHEDULE_HOURS]

    def _recent_due(self, now):
        last_key = str(self.repos.meta.get("scheduled_tableau_last_slot", "") or "")
        for slot in reversed(self._slots(now)):
            seconds = (now - slot).total_seconds()
            if 0 <= seconds <= self.STARTUP_GRACE_MINUTES * 60 and self._slot_key(slot) != last_key:
                return slot
        return None

    def _next(self, now):
        for slot in self._slots(now):
            if slot > now: return slot
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=self.SCHEDULE_HOURS[0], minute=0, second=0, microsecond=0)

    def run_slot(self, slot):
        slot_key = self._slot_key(slot)
        self.repos.meta.set("scheduled_tableau_last_attempt", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            result = self.reports.refresh(REP_REPORT_ID)
            if not result.get("ok"):
                self.repos.meta.set("scheduled_tableau_status", result.get("error") or "Scheduled report refresh failed")
                self.repos.meta.set("scheduled_tableau_last_slot", slot_key)
                return False
            now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.repos.meta.set("scheduled_tableau_status", f"Scheduled report refresh completed at {now_text}")
            self.repos.meta.set("scheduled_tableau_last_slot", slot_key)
            try:
                self.reports.refresh(PRODUCT_REPORT_ID)
            except Exception as exc:
                self.repos.meta.set("product_close_status", f"Product close rate pull failed: {exc}")
            return True
        except Exception as exc:
            self.repos.meta.set("scheduled_tableau_status", f"Scheduled report refresh failed: {exc}")
            self.repos.meta.set("scheduled_tableau_last_slot", slot_key)
            return False

    def _worker(self):
        self.repos.meta.set("scheduled_tableau_status", "Scheduler active — daily at 06:00 and 14:00")
        while True:
            now = datetime.now()
            due = self._recent_due(now)
            if due is not None:
                self.run_slot(due); time.sleep(65); continue
            target = self._next(now)
            delay = max(1.0, (target - now).total_seconds())
            time.sleep(min(delay, 60.0))
            if datetime.now() >= target:
                if str(self.repos.meta.get("scheduled_tableau_last_slot", "") or "") != self._slot_key(target):
                    self.run_slot(target)
                time.sleep(65)

    def start(self):
        with self._lock:
            if self._started: return False
            self._started = True
            threading.Thread(target=self._worker, name="report-refresh-scheduler", daemon=True).start()
            return True
