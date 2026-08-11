#!/usr/bin/env python3
"""Twice-daily Tableau refresh worker for the Raspberry Pi appliance.

Runs independently from the Flask/Waitress process so normal application
restarts do not cancel the schedule. One flock keeps duplicate kiosk launches
from creating duplicate workers. Times use the Raspberry Pi's local clock.
"""
import fcntl
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from database import get_meta, get_settings, init_db, replace_reps, set_meta
from sources.tableau import TableauError, TableauSource, resolve_dates

DATA_DIR = Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
LOCK_PATH = DATA_DIR / "tableau-scheduler.lock"
SCHEDULE_HOURS = (6, 14)
STARTUP_GRACE_MINUTES = 15


def _slot_key(dt):
    return dt.strftime("%Y-%m-%dT%H")


def _scheduled_slots(now):
    return [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in SCHEDULE_HOURS]


def _recent_due_slot(now):
    last_key = str(get_meta("scheduled_tableau_last_slot", "") or "")
    for slot in reversed(_scheduled_slots(now)):
        seconds = (now - slot).total_seconds()
        if 0 <= seconds <= STARTUP_GRACE_MINUTES * 60 and _slot_key(slot) != last_key:
            return slot
    return None


def _next_slot(now):
    for slot in _scheduled_slots(now):
        if slot > now:
            return slot
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=SCHEDULE_HOURS[0], minute=0, second=0, microsecond=0)


def _refresh(slot):
    slot_key = _slot_key(slot)
    set_meta("scheduled_tableau_last_attempt", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        settings = get_settings()
        if not str(settings.get("tableau_pat_secret") or "").strip():
            set_meta("scheduled_tableau_status", "Skipped scheduled pull — Tableau PAT is not configured")
            set_meta("scheduled_tableau_last_slot", slot_key)
            return

        source = TableauSource(settings)
        rows = source.fetch()
        if not rows:
            set_meta("scheduled_tableau_status", "Scheduled Tableau pull returned no matching people; existing data kept")
            set_meta("scheduled_tableau_last_slot", slot_key)
            return

        # Sales metrics only. Persistent Pi team assignments are preserved by replace_reps.
        replace_reps(rows)
        start, end = resolve_dates(settings)
        status = (
            f"Tableau — {len(rows)} people, {start} to {end}"
            + (f", office {settings.get('data_office')}" if settings.get("data_office") else ", all offices")
        )
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        set_meta("source_status", status)
        set_meta("last_source_refresh", now_text)
        set_meta("scheduled_tableau_status", f"Scheduled pull completed at {now_text}")
        set_meta("scheduled_tableau_last_slot", slot_key)
        set_meta("data_version", int(get_meta("data_version", "0")) + 1)
    except TableauError as exc:
        set_meta("scheduled_tableau_status", f"Scheduled Tableau error: {exc}")
        set_meta("source_status", f"Tableau error: {exc}")
        set_meta("scheduled_tableau_last_slot", slot_key)
    except Exception as exc:
        set_meta("scheduled_tableau_status", f"Scheduled Tableau refresh failed: {exc}")
        set_meta("scheduled_tableau_last_slot", slot_key)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0

    init_db()
    set_meta("scheduled_tableau_status", "Scheduler active — daily at 06:00 and 14:00")

    while True:
        now = datetime.now()
        due = _recent_due_slot(now)
        if due is not None:
            _refresh(due)
            time.sleep(65)
            continue

        target = _next_slot(now)
        delay = max(1.0, (target - now).total_seconds())
        # Wake periodically so timezone/clock changes on the Pi are respected.
        time.sleep(min(delay, 60.0))
        if datetime.now() >= target:
            if str(get_meta("scheduled_tableau_last_slot", "") or "") != _slot_key(target):
                _refresh(target)
            time.sleep(65)


if __name__ == "__main__":
    raise SystemExit(main())
