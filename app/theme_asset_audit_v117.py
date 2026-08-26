"""v117 runtime audit and temporary default-asset isolation test.

The audit runs against the Pi's real persistent filesystem, not the repository.
It proves that every image currently referenced by a saved/effective team theme
is readable from the v116 applied-theme store and that no effective theme URL
still depends on shipped static artwork.

The test switch is intentionally non-destructive. For ten minutes it makes the
shipped theme/library image roots unavailable and forces fresh URLs for any
remaining static dependency, then restores them automatically. This simulates
removing default artwork without renaming or deleting a single file.
"""
from pathlib import Path
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import abort, jsonify, request

from database import get_meta, get_settings, get_team_definitions, set_meta
import applied_theme_assets_v116
import themes

_AUDIT_ENDPOINT = "api_theme_asset_protection_v117"
_TEST_ENDPOINT = "api_theme_defaults_test_v117"
_TEST_UNTIL_META = "v117_theme_defaults_test_until"
_TEST_SECONDS = 10 * 60
_STATIC_DEFAULT_PREFIXES = ("/static/theme-packs/", "/static/asset-library/")

_LOCK = threading.RLock()
_INSTALLED = False
_BASE_ASSET_URL = None
_TEST_UNTIL = 0.0


def _bump(key):
    try:
        value = int(get_meta(key, "0") or 0) + 1
    except Exception:
        value = 1
    set_meta(key, value)
    return value


def _bump_tv():
    _bump("settings_version")
    _bump("tv_refresh_version")


def _read_until():
    try:
        return float(get_meta(_TEST_UNTIL_META, "0") or 0)
    except Exception:
        return 0.0


def _set_until(value, refresh=True):
    global _TEST_UNTIL
    _TEST_UNTIL = max(0.0, float(value or 0))
    set_meta(_TEST_UNTIL_META, _TEST_UNTIL)
    if refresh:
        _bump_tv()


def _expire_if_needed(now=None):
    now = time.time() if now is None else now
    with _LOCK:
        if _TEST_UNTIL and now >= _TEST_UNTIL:
            _set_until(0.0, refresh=True)
            return True
    return False


def test_state():
    now = time.time()
    _expire_if_needed(now)
    with _LOCK:
        active = _TEST_UNTIL > now
        return {
            "active": active,
            "seconds_left": max(0, int(_TEST_UNTIL - now)) if active else 0,
            "minutes": 10,
        }


def _is_default_url(url):
    path = urlsplit(str(url or "")).path
    return any(path.startswith(prefix) for prefix in _STATIC_DEFAULT_PREFIXES)


def _cache_bust(url):
    parts = urlsplit(str(url or ""))
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["v117-default-test"] = str(int(_TEST_UNTIL or time.time()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _patch_asset_urls():
    """Force a cache miss for any static dependency while the test is active."""
    global _BASE_ASSET_URL
    if _BASE_ASSET_URL is not None:
        return
    _BASE_ASSET_URL = themes._asset_url

    def asset_url_v117(scope, asset_key, config, base, version):
        url = _BASE_ASSET_URL(scope, asset_key, config, base, version)
        if url and _TEST_UNTIL > time.time() and _is_default_url(url):
            return _cache_bust(url)
        return url

    themes._asset_url = asset_url_v117


def _readable_nonempty(path):
    try:
        if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return False
        with open(path, "rb") as handle:
            return bool(handle.read(1))
    except Exception:
        return False


def audit():
    """Audit all saved/effective team theme image dependencies on this Pi."""
    settings = get_settings()
    root = applied_theme_assets_v116.APPLIED_THEME_ASSET_ROOT
    marker = str(get_meta(applied_theme_assets_v116.MIGRATION_META, "") or "") == "1"
    migration_status = str(get_meta(applied_theme_assets_v116.STATUS_META, "") or "")

    try:
        root_resolved = root.resolve()
        runtime_root = Path(themes.PERSISTENT_THEME_ROOT).resolve()
        runtime_store_active = runtime_root == root_resolved
    except Exception:
        root_resolved = root
        runtime_store_active = False

    issues = []
    protected = 0
    total = 0
    default_dependencies = 0
    teams_checked = 0
    version = int(get_meta("settings_version", "0") or 0)

    for team in get_team_definitions(include_inactive=True):
        teams_checked += 1
        team_id = int(team["team_id"])
        team_name = str(team.get("name") or f"Team {team_id}")
        scope = f"team-{team_id}"
        config = themes._stored_config(settings, scope, team)
        base = str(config.get("base") or themes._default_base(team)).strip().lower()
        if base not in {"classic", "undisputed"}:
            base = "classic"
        assets = config.get("assets") if isinstance(config.get("assets"), dict) else {}

        for asset_key, definition in themes.ASSETS.items():
            filename = Path(str(assets.get(asset_key) or "")).name
            effective_url = themes._asset_url(scope, asset_key, config, base, version)
            has_effective_asset = bool(filename or effective_url)
            if not has_effective_asset:
                continue

            total += 1
            label = str(definition.get("label") or asset_key)

            if _is_default_url(effective_url):
                default_dependencies += 1
                issues.append({
                    "team": team_name,
                    "asset": label,
                    "problem": "Still depends on a shipped default asset.",
                })

            if not filename:
                issues.append({
                    "team": team_name,
                    "asset": label,
                    "problem": "No permanent applied-file reference is saved.",
                })
                continue

            path = root / scope / filename
            try:
                resolved = path.resolve()
                inside = resolved == root_resolved or root_resolved in resolved.parents
            except Exception:
                inside = False

            if not inside:
                issues.append({
                    "team": team_name,
                    "asset": label,
                    "problem": "Saved file resolves outside permanent storage.",
                })
                continue

            if not _readable_nonempty(path):
                issues.append({
                    "team": team_name,
                    "asset": label,
                    "problem": "Permanent applied file is missing, empty, or unreadable.",
                })
                continue

            if not str(effective_url or "").startswith(f"/api/theme-assets/{scope}/"):
                issues.append({
                    "team": team_name,
                    "asset": label,
                    "problem": "Theme is not serving the permanent applied copy.",
                })
                continue

            protected += 1

    if not marker:
        issues.insert(0, {
            "team": "Migration",
            "asset": "v116",
            "problem": "The v116 migration-complete marker is missing.",
        })
    if not root.exists() or not root.is_dir():
        issues.insert(0, {
            "team": "Storage",
            "asset": "Applied assets",
            "problem": "The permanent applied-theme-assets folder is missing.",
        })
    if not runtime_store_active:
        issues.insert(0, {
            "team": "Runtime",
            "asset": "Applied assets",
            "problem": "The running theme engine is not using the permanent v116 store.",
        })

    safe = bool(marker and root.exists() and runtime_store_active and total == protected and not issues)
    return {
        "safe": safe,
        "migration_complete": marker,
        "migration_status": migration_status,
        "runtime_store_active": runtime_store_active,
        "storage_path": str(root),
        "teams_checked": teams_checked,
        "assets_total": total,
        "assets_protected": protected,
        "default_dependencies": default_dependencies,
        "issues": issues,
    }


def _status_route():
    return jsonify({"ok": True, "audit": audit(), "test": test_state()})


def _test_route():
    body = request.get_json(force=True, silent=True) or {}
    enabled = body.get("enabled") is True
    with _LOCK:
        if enabled:
            _set_until(time.time() + _TEST_SECONDS, refresh=True)
        else:
            _set_until(0.0, refresh=True)
    return jsonify({"ok": True, "audit": audit(), "test": test_state()})


def _before_request():
    _expire_if_needed()
    if _TEST_UNTIL <= time.time():
        return None
    path = str(request.path or "")
    if any(path.startswith(prefix) for prefix in _STATIC_DEFAULT_PREFIXES):
        abort(404)
    return None


def install(app):
    global _INSTALLED, _TEST_UNTIL
    with _LOCK:
        if _INSTALLED:
            return False
        _TEST_UNTIL = _read_until()
        if _TEST_UNTIL and _TEST_UNTIL <= time.time():
            _set_until(0.0, refresh=False)

        _patch_asset_urls()
        app.before_request(_before_request)
        app.add_url_rule(
            "/api/theme-asset-protection",
            endpoint=_AUDIT_ENDPOINT,
            view_func=_status_route,
            methods=["GET"],
        )
        app.add_url_rule(
            "/api/theme-defaults-test",
            endpoint=_TEST_ENDPOINT,
            view_func=_test_route,
            methods=["POST"],
        )
        _INSTALLED = True
        return True
