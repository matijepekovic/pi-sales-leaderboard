"""v115 Product Close Rates controls and TV promotion.

This module keeps product data independent from the rep table while promoting
its existing preview screen into the physical screen rotation. It also owns the
persistent market selector and makes the temporary date override serve matching
product rows without overwriting the regular scheduled product snapshot.
"""
import json
import sys
import threading
import time

from flask import jsonify, request

from database import (
    get_meta,
    get_product_close,
    get_settings,
    replace_product_close,
    save_settings,
    set_meta,
)
import keyboard_controls_v112
from product_source_v115 import ProductCloseSourceV115, selected_market
import temporary_date_v113

PRODUCT_MODE = "product_close"
PRODUCT_LABEL = "Product Close Rates"
_MARKETS_ENDPOINT = "api_product_markets_v115"
_MARKET_ENDPOINT = "api_product_market_v115"
_MARKET_CACHE_SECONDS = 6 * 60 * 60
_REFRESH_LOCK = threading.Lock()
_PATCHED = False
_BASE_GET_MODE_PAYLOAD = None


def _bump_meta(key):
    try:
        value = int(get_meta(key, "0") or 0) + 1
    except Exception:
        value = 1
    set_meta(key, value)
    return value


def _store_regular(rows, start, end, market):
    replace_product_close(rows)
    now_text = time.strftime("%Y-%m-%d %H:%M:%S")
    set_meta("product_close_start", start)
    set_meta("product_close_end", end)
    set_meta("product_close_market", market)
    set_meta(
        "product_close_status",
        f"{market} — {len(rows)} products, {start} to {end} — updated {now_text}",
    )
    _bump_meta("product_close_version")
    return now_text


def refresh_product_close(settings):
    """Scheduled product refresh. Never raises, matching the legacy contract."""
    try:
        market = selected_market(settings)
        start, end, rows = ProductCloseSourceV115(settings).fetch_products(
            market=market
        )
        _store_regular(rows, start, end, market)
        return True
    except Exception as exc:
        set_meta("product_close_status", f"Product close rate pull failed: {exc}")
        return False


def _regular_payload(settings=None):
    settings = settings or get_settings()
    rows = get_product_close()
    market = str(get_meta("product_close_market", "") or "").strip()
    if not market:
        # Every pre-v115 stored product snapshot was Olympia-only.
        market = "Olympia"
    start = str(get_meta("product_close_start", "") or "")
    end = str(get_meta("product_close_end", "") or "")
    context = f"regular|{market}|{start}|{end}|{get_meta('product_close_version','0')}"
    decorated = [dict(row, _display_context=context) for row in rows]
    return {
        "rows": decorated,
        "market": market,
        "start": start,
        "end": end,
        "temporary": False,
        "seconds_left": 0,
        "updated_at": rows[0]["updated_at"] if rows else "",
        "status": get_meta("product_close_status", ""),
        "icons": settings.get("product_icons") or {},
    }


def current_product_payload(settings=None):
    settings = settings or get_settings()
    temporary = temporary_date_v113.product_override_payload()
    if temporary is not None:
        context = (
            f"temporary|{temporary['market']}|{temporary['start']}|"
            f"{temporary['end']}|{temporary['seconds_left']}"
        )
        rows = [
            dict(row, _display_context=context)
            for row in temporary.get("rows") or []
        ]
        return {
            "rows": rows,
            "market": temporary.get("market") or selected_market(settings),
            "start": temporary.get("start") or "",
            "end": temporary.get("end") or "",
            "temporary": True,
            "seconds_left": int(temporary.get("seconds_left") or 0),
            "updated_at": "",
            "status": "Temporary date override active",
            "icons": settings.get("product_icons") or {},
        }
    return _regular_payload(settings)


def _pull_regular_and_temporary(settings):
    """Pull the saved market for regular range and, when active, temp range."""
    market = selected_market(settings)
    source = ProductCloseSourceV115(settings)
    start, end, rows = source.fetch_products(market=market)

    state = temporary_date_v113.current_state()
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


def _commit_pulled(result):
    _store_regular(
        result["rows"], result["start"], result["end"], result["market"]
    )
    state = result.get("temporary_state") or {}
    if state.get("active") and result.get("temporary_rows") is not None:
        temporary_date_v113.replace_product_override(
            result["temporary_rows"],
            result["market"],
            expected_start=state.get("start"),
            expected_end=state.get("end"),
        )


def _refresh_route():
    if not _REFRESH_LOCK.acquire(blocking=False):
        return jsonify({"ok": False, "error": "A product refresh is already running."}), 409
    try:
        settings = get_settings()
        if not str(settings.get("tableau_pat_secret") or "").strip():
            return jsonify({"ok": False, "error": "Enter the Tableau PAT secret first."}), 400
        try:
            result = _pull_regular_and_temporary(settings)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Product pull failed: {exc}"}), 400
        _commit_pulled(result)
        return jsonify({"ok": True, **current_product_payload(settings)})
    finally:
        _REFRESH_LOCK.release()


def _product_route():
    return jsonify({"ok": True, "beta": False, **current_product_payload()})


def _cached_markets():
    try:
        values = json.loads(str(get_meta("product_markets_v115", "[]") or "[]"))
    except Exception:
        values = []
    values = [str(value).strip() for value in values if str(value).strip()]
    try:
        cached_at = float(get_meta("product_markets_v115_at", "0") or 0)
    except Exception:
        cached_at = 0.0
    return list(dict.fromkeys(values)), cached_at


def _market_choices(settings=None, force=False):
    settings = settings or get_settings()
    selected = selected_market(settings)
    cached, cached_at = _cached_markets()
    fresh = cached and time.time() - cached_at < _MARKET_CACHE_SECONDS
    warning = ""

    if force or not fresh:
        try:
            cached = ProductCloseSourceV115(settings).fetch_markets()
            cached_at = time.time()
            set_meta("product_markets_v115", json.dumps(cached))
            set_meta("product_markets_v115_at", cached_at)
        except Exception as exc:
            warning = str(exc)

    values = list(cached)
    if selected and selected.casefold() not in {v.casefold() for v in values}:
        values.append(selected)
    if not values:
        # Keep the appliance usable if Tableau cannot enumerate the filter
        # domain right now; the legacy/default market is still known-good.
        values = [selected or "Olympia"]
    values = sorted(list(dict.fromkeys(values)), key=str.casefold)
    return values, warning


def _markets_route():
    values, warning = _market_choices()
    payload = {
        "ok": True,
        "markets": values,
        "selected": selected_market(get_settings()),
    }
    if warning:
        payload["warning"] = warning
    return jsonify(payload)


def _market_route():
    body = request.get_json(force=True, silent=True) or {}
    requested = str(body.get("market") or "").strip()
    if not requested:
        return jsonify({"ok": False, "error": "Choose a market."}), 400

    settings = get_settings()
    choices, warning = _market_choices(settings)
    canonical = next(
        (value for value in choices if value.casefold() == requested.casefold()),
        "",
    )
    if not canonical:
        return jsonify({"ok": False, "error": "Choose a market from the dropdown."}), 400

    if not _REFRESH_LOCK.acquire(blocking=False):
        return jsonify({"ok": False, "error": "A product refresh is already running."}), 409
    try:
        candidate = dict(settings)
        candidate["product_market"] = canonical
        try:
            result = _pull_regular_and_temporary(candidate)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not load {canonical}: {exc}"}), 400

        # Commit only after both the regular range and active temporary range
        # (when one exists) have pulled successfully.
        save_settings(candidate)
        _bump_meta("settings_version")
        _commit_pulled(result)
        payload = {"ok": True, **current_product_payload(candidate)}
        if warning:
            payload["warning"] = warning
        return jsonify(payload)
    finally:
        _REFRESH_LOCK.release()


def _product_mode_payload():
    product = current_product_payload()
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


def _patch_server(app):
    global _PATCHED, _BASE_GET_MODE_PAYLOAD
    if _PATCHED:
        return
    server_module = sys.modules.get("server") or sys.modules.get("__main__")
    if server_module is None:
        raise RuntimeError("Server module is unavailable for Product Close Rates setup.")

    _BASE_GET_MODE_PAYLOAD = getattr(server_module, "get_mode_payload")

    def get_mode_payload_v115(
        mode=None, sort_metric_override=None, team_vs_team_override=None
    ):
        settings = get_settings()
        raw = mode if mode is not None else settings.get("active_mode", "whole_office")
        if str(raw or "").strip() == PRODUCT_MODE:
            return _product_mode_payload()
        return _BASE_GET_MODE_PAYLOAD(
            mode,
            sort_metric_override=sort_metric_override,
            team_vs_team_override=team_vs_team_override,
        )

    server_module.get_mode_payload = get_mode_payload_v115

    # Preserve the original Flask endpoint names so the existing PIN/public
    # allow-list behavior remains exactly the same.
    if "api_product_close" in app.view_functions:
        app.view_functions["api_product_close"] = _product_route
    if "api_product_close_refresh" in app.view_functions:
        app.view_functions["api_product_close_refresh"] = _refresh_route

    _PATCHED = True


def _patch_scheduler():
    scheduler = sys.modules.get("tableau_scheduler")
    if scheduler is not None:
        scheduler.refresh_product_close = refresh_product_close


def _install_rotation():
    if PRODUCT_MODE not in keyboard_controls_v112.FIXED_VIEWS:
        keyboard_controls_v112.FIXED_VIEWS = (
            *keyboard_controls_v112.FIXED_VIEWS,
            PRODUCT_MODE,
        )

    # Existing installs already have an explicit rotation list that predates
    # this screen. Add Product Close Rates once; after that, the user's checkbox
    # choice is authoritative and will not be re-added after they turn it off.
    if str(get_meta("v115_product_rotation_migrated", "") or "") == "1":
        return
    settings = get_settings()
    raw = settings.get("keyboard_cycle_views")
    if isinstance(raw, list) and raw:
        views = [str(value) for value in raw]
        if PRODUCT_MODE not in views:
            views.append(PRODUCT_MODE)
            settings["keyboard_cycle_views"] = views
            save_settings(settings)
            _bump_meta("settings_version")
    set_meta("v115_product_rotation_migrated", "1")


def install_routes(app):
    """Install protected market routes and promote the product TV mode."""
    changed = False
    _install_rotation()
    _patch_server(app)
    _patch_scheduler()

    if _MARKETS_ENDPOINT not in app.view_functions:
        app.add_url_rule(
            "/api/product-markets",
            endpoint=_MARKETS_ENDPOINT,
            view_func=_markets_route,
            methods=["GET"],
        )
        changed = True
    if _MARKET_ENDPOINT not in app.view_functions:
        app.add_url_rule(
            "/api/product-market",
            endpoint=_MARKET_ENDPOINT,
            view_func=_market_route,
            methods=["POST"],
        )
        changed = True
    return changed
