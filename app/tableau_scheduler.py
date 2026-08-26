#!/usr/bin/env python3
"""Twice-daily Tableau refresh worker for the Raspberry Pi appliance.

The Flask app starts this lazily on the first request after boot/restart.
Times use the Raspberry Pi's local clock. Only one daemon thread is created
per app process.
"""
import sys
import threading
import time
from datetime import datetime, timedelta

from database import (get_meta, get_settings, replace_product_close,
                      replace_reps, set_meta)
import source_picker
import pull_policy_v108
import remote_qr_v109
import qr_controls_v110
from sources.tableau import TableauError, TableauSource, resolve_dates
from sources.tableau_products import ProductCloseSource

# Install v108's pull policy during import. server.py imports this module before
# it calls database.init_db(), which is exactly when the legacy source-team sync
# must be disabled. source_picker.resolve_source is also wrapped here so both
# manual and scheduled rep pulls get the same fallback behavior.
pull_policy_v108.install(source_picker)

SCHEDULE_HOURS = (6, 14)
STARTUP_GRACE_MINUTES = 15
_START_LOCK = threading.Lock()
_STARTED = False


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


def refresh_product_close(settings):
    """Pull the beta product close rates. Never raises.

    Deliberately isolated from the rep refresh: this is a different workbook
    that the leaderboard does not depend on, so a failure here must not fail
    the rep pull, touch source_status, or affect the slot bookkeeping. It
    reports only into its own meta key.
    """
    try:
        start, end, rows = ProductCloseSource(settings).fetch_products()
        replace_product_close(rows)
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Stored separately from the status string so the screen can put the
        # range in its header without parsing prose.
        set_meta("product_close_start", start)
        set_meta("product_close_end", end)
        set_meta("product_close_status",
                 f"{len(rows)} products, {start} to {end} — updated {now_text}")
        return True
    except Exception as exc:
        set_meta("product_close_status", f"Product close rate pull failed: {exc}")
        return False


def _refresh(slot):
    slot_key = _slot_key(slot)
    set_meta("scheduled_tableau_last_attempt", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        settings = get_settings()
        if not str(settings.get("tableau_pat_secret") or "").strip():
            set_meta("scheduled_tableau_status", "Skipped scheduled pull — Tableau PAT is not configured")
            set_meta("scheduled_tableau_last_slot", slot_key)
            return

        source = source_picker.resolve_source(settings)
        rows = source.fetch()
        if not rows:
            set_meta("scheduled_tableau_status", "Scheduled Tableau pull returned no matching people; existing data kept")
            set_meta("scheduled_tableau_last_slot", slot_key)
            return

        # v108 policy has already removed Tableau organization text and merged
        # any same-scope missing reps before rows reach storage. Persistent Pi
        # team assignments remain separate and untouched.
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

        # Beta, and a separate workbook. Runs last and swallows its own
        # errors so the rep board above is already committed either way.
        refresh_product_close(settings)
    except TableauError as exc:
        set_meta("scheduled_tableau_status", f"Scheduled Tableau error: {exc}")
        set_meta("source_status", f"Tableau error: {exc}")
        set_meta("scheduled_tableau_last_slot", slot_key)
    except Exception as exc:
        set_meta("scheduled_tableau_status", f"Scheduled Tableau refresh failed: {exc}")
        set_meta("scheduled_tableau_last_slot", slot_key)


def _worker():
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


def start_tableau_scheduler():
    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return False

        # database.init_db() has completed by the time server.py calls us.
        # Seed the current-period fallback cache before removing any old source
        # team text from stored reps, then keep organization Pi-owned forever.
        pull_policy_v108.bootstrap(source_picker)

        # v110: server.py calls this only after its Flask app has been created.
        # Attach the PIN-protected QR save route without expanding server.py's
        # already-large settings endpoint.
        try:
            server_module = sys.modules.get("server")
            flask_app = getattr(server_module, "app", None) if server_module else None
            if flask_app is not None:
                qr_controls_v110.install_routes(flask_app)
            else:
                set_meta("remote_qr_controls_error", "Flask app was not available during startup")
        except Exception as exc:
            set_meta("remote_qr_controls_error", str(exc))

        # v109: generate the phone-remote QR after the Pi is fully initialized.
        # A QR failure must never stop the leaderboard from starting.
        try:
            url = remote_qr_v109.generate()
            set_meta("remote_qr_url", url)
        except Exception as exc:
            set_meta("remote_qr_url", "")
            set_meta("remote_qr_error", str(exc))

        _STARTED = True
        thread = threading.Thread(
            target=_worker,
            name="tableau-twice-daily",
            daemon=True,
        )
        thread.start()
        return True
