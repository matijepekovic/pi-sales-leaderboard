"""Scheduling only: decide when to call refresh services."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta


class SchedulerService:
    SCHEDULE_HOURS = (6, 14)
    STARTUP_GRACE_MINUTES = 15

    def __init__(self, repos, rep_refresh, product_service):
        self.repos = repos
        self.rep_refresh = rep_refresh
        self.product_service = product_service
        self._lock = threading.Lock()
        self._started = False

    @staticmethod
    def _slot_key(dt):
        return dt.strftime("%Y-%m-%dT%H")

    def _slots(self, now):
        return [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in self.SCHEDULE_HOURS]

    def _recent_due(self, now):
        last_key = str(self.repos.meta.get("scheduled_tableau_last_slot", "") or "")
        for slot in reversed(self._slots(now)):
            seconds = (now - slot).total_seconds()
            if 0 <= seconds <= self.STARTUP_GRACE_MINUTES * 60 and self._slot_key(slot) != last_key:
                return slot
        return None

    def _next(self, now):
        for slot in self._slots(now):
            if slot > now:
                return slot
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=self.SCHEDULE_HOURS[0], minute=0, second=0, microsecond=0)

    def run_slot(self, slot):
        slot_key = self._slot_key(slot)
        self.repos.meta.set("scheduled_tableau_last_attempt", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        settings = self.repos.settings.get()
        if not str(settings.get("tableau_pat_secret") or "").strip():
            self.repos.meta.set("scheduled_tableau_status", "Skipped scheduled pull — Tableau PAT is not configured")
            self.repos.meta.set("scheduled_tableau_last_slot", slot_key)
            return False
        try:
            result = self.rep_refresh.refresh(settings)
            if not result.get("ok"):
                self.repos.meta.set("scheduled_tableau_status", result.get("error") or "Scheduled Tableau pull failed")
                self.repos.meta.set("scheduled_tableau_last_slot", slot_key)
                return False
            now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.repos.meta.set("scheduled_tableau_status", f"Scheduled pull completed at {now_text}")
            self.repos.meta.set("scheduled_tableau_last_slot", slot_key)
            self.product_service.refresh(settings, raise_errors=False)
            return True
        except Exception as exc:
            self.repos.meta.set("scheduled_tableau_status", f"Scheduled Tableau refresh failed: {exc}")
            self.repos.meta.set("scheduled_tableau_last_slot", slot_key)
            return False

    def _worker(self):
        self.repos.meta.set("scheduled_tableau_status", "Scheduler active — daily at 06:00 and 14:00")
        while True:
            now = datetime.now()
            due = self._recent_due(now)
            if due is not None:
                self.run_slot(due)
                time.sleep(65)
                continue
            target = self._next(now)
            delay = max(1.0, (target - now).total_seconds())
            time.sleep(min(delay, 60.0))
            if datetime.now() >= target:
                if str(self.repos.meta.get("scheduled_tableau_last_slot", "") or "") != self._slot_key(target):
                    self.run_slot(target)
                time.sleep(65)

    def start(self):
        with self._lock:
            if self._started:
                return False
            self._started = True
            threading.Thread(target=self._worker, name="tableau-twice-daily", daemon=True).start()
            return True
