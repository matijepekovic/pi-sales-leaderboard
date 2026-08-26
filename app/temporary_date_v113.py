"""v113 temporary date-range override for the TV.

The override never writes to the reps table. It pulls a second in-memory row
set, lets the display use those rows for up to 60 minutes, then automatically
falls back to the regularly scheduled rows already stored on the Pi.

v114 also enforces the appliance's standard Tableau date-filter captions at
runtime. Older saved sources can contain blank date_start_field/date_end_field
values even though the remote has treated those fields as internal Start/End
keys since v106. Blank saved values must never make Tableau silently ignore a
requested date range.
"""
from datetime import date
import threading
import time

from flask import jsonify, request

from database import get_settings
import source_picker
from sources.tableau_configured import ConfiguredTableauSource

_ENDPOINT = "api_temporary_date_override_v113"
_LOCK = threading.RLock()
_PULL_LOCK = threading.Lock()
_INSTALLED = False
_BASE_PREVIEW_ROWS = None
_BASE_CONFIGURED_INIT = None
_STATE = {
    "rows": None,
    "until": 0.0,
    "mode": "",
    "start": "",
    "end": "",
    "minutes": 0,
}


def _expire_locked(now=None):
    now = time.time() if now is None else now
    if _STATE["rows"] is not None and now >= float(_STATE["until"] or 0):
        _STATE.update({
            "rows": None,
            "until": 0.0,
            "mode": "",
            "start": "",
            "end": "",
            "minutes": 0,
        })


def override_rows():
    """Return temporary rows while active, otherwise None."""
    with _LOCK:
        _expire_locked()
        if _STATE["rows"] is None:
            return None
        return list(_STATE["rows"])


def current_state():
    with _LOCK:
        now = time.time()
        _expire_locked(now)
        active = _STATE["rows"] is not None
        return {
            "active": active,
            "mode": _STATE["mode"] if active else "",
            "start": _STATE["start"] if active else "",
            "end": _STATE["end"] if active else "",
            "minutes": int(_STATE["minutes"] or 0) if active else 0,
            "seconds_left": max(0, int(float(_STATE["until"] or 0) - now)) if active else 0,
            "rows": len(_STATE["rows"] or []) if active else 0,
        }


def _install_standard_date_fields():
    """Make blank legacy source date fields behave as internal Start / End.

    Patch the configured source instance rather than source_picker.source_config
    so the v108 fallback scope signature does not change for existing installs.
    Nonblank explicitly saved field names are left alone for compatibility.
    """
    global _BASE_CONFIGURED_INIT
    if _BASE_CONFIGURED_INIT is not None:
        return False

    _BASE_CONFIGURED_INIT = ConfiguredTableauSource.__init__

    def init_with_standard_date_fields(self, config=None, source=None):
        _BASE_CONFIGURED_INIT(self, config, source)
        if not str(self.source.get("date_start_field") or "").strip():
            self.source["date_start_field"] = "Start"
        if not str(self.source.get("date_end_field") or "").strip():
            self.source["date_end_field"] = "End"

    ConfiguredTableauSource.__init__ = init_with_standard_date_fields
    return True


def install():
    """Layer the date override under the existing mapping-preview mechanism.

    Mapping preview stays highest priority. When it is not active, the TV sees
    the temporary date rows; after expiry it naturally returns to list_reps().
    """
    global _INSTALLED, _BASE_PREVIEW_ROWS
    with _LOCK:
        if _INSTALLED:
            return False

        # v114: all configured Tableau pulls get the internal Start/End defaults
        # when an older saved source left those implementation fields blank.
        _install_standard_date_fields()

        _BASE_PREVIEW_ROWS = source_picker.preview_rows

        def combined_preview_rows():
            preview = _BASE_PREVIEW_ROWS()
            if preview is not None:
                return preview
            return override_rows()

        source_picker.preview_rows = combined_preview_rows
        _INSTALLED = True
        return True


def _parse_custom_date(value, label):
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text)
    except Exception as exc:
        raise ValueError(f"Choose a valid {label} date.") from exc


def _requested_range(body):
    mode = str(body.get("mode") or "").strip().lower()
    today = date.today()

    if mode == "ytd":
        start = date(today.year, 1, 1)
        end = today
        return mode, start.isoformat(), end.isoformat()

    if mode == "custom":
        start = _parse_custom_date(body.get("start"), "start")
        end = _parse_custom_date(body.get("end"), "end")
        if start > end:
            raise ValueError("Start date must be before or equal to end date.")
        return mode, start.isoformat(), end.isoformat()

    raise ValueError("Choose Year to Date or Custom Range.")


def _requested_minutes(body):
    try:
        minutes = int(body.get("minutes"))
    except Exception as exc:
        raise ValueError("Enter a duration from 1 to 60 minutes.") from exc
    if minutes < 1 or minutes > 60:
        raise ValueError("Enter a duration from 1 to 60 minutes.")
    return minutes


def _apply_override():
    body = request.get_json(force=True, silent=True) or {}
    try:
        mode, start, end = _requested_range(body)
        minutes = _requested_minutes(body)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    # Pull into a separate row set. The saved date configuration and reps table
    # are never changed, so a failed temporary pull cannot damage the live board.
    trial = dict(get_settings())
    trial["data_date_mode"] = "custom"
    trial["data_date_start"] = start
    trial["data_date_end"] = end

    # v114: the temporary override must send the requested range to Tableau even
    # when an older saved source contains blank internal date-field captions.
    # These values exist only in the temporary settings copy and are never saved.
    source = dict(trial.get("source") or {})
    source["date_start_field"] = "Start"
    source["date_end_field"] = "End"
    trial["source"] = source

    try:
        with _PULL_LOCK:
            rows = source_picker.resolve_source(trial).fetch()
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Temporary pull failed: {exc}"}), 502

    if not rows:
        return jsonify({"ok": False, "error": "Temporary pull returned no people. Regular numbers were kept."}), 400

    with _LOCK:
        _STATE.update({
            "rows": list(rows),
            "until": time.time() + minutes * 60,
            "mode": mode,
            "start": start,
            "end": end,
            "minutes": minutes,
        })

    return jsonify({"ok": True, "override": current_state()})


def _state():
    return jsonify({"ok": True, "override": current_state()})


def install_routes(app):
    if _ENDPOINT in app.view_functions:
        return False
    app.add_url_rule(
        "/api/temporary-date-override",
        endpoint=_ENDPOINT,
        view_func=_apply_override,
        methods=["POST"],
    )
    app.add_url_rule(
        "/api/temporary-date-override",
        endpoint=f"{_ENDPOINT}_state",
        view_func=_state,
        methods=["GET"],
    )
    return True
