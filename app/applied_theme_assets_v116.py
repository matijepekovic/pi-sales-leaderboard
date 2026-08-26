"""v116 permanent storage for assets that are actually applied to themes.

The shipped asset catalog is a source for choosing artwork, never the runtime
source of an applied theme.  Every applied file lives under the persistent data
directory, outside APP_ROOT, so GitHub/ZIP updates and reinstalling the app
cannot remove artwork that a team is already using.

Upgrade safety is deliberately conservative:
- migrate and verify copies before changing any saved theme references;
- do not delete legacy theme files during migration;
- if a required copy cannot be made, leave the old theme runtime untouched;
- after migration, every future theme save materializes any built-in artwork
  into the persistent applied store before the configuration is committed.
"""
import hashlib
import os
import shutil
import threading
import uuid
from pathlib import Path

from database import (
    get_meta,
    get_settings,
    get_team_definitions,
    save_settings,
    set_meta,
)
import themes

DATA_ROOT = Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
APPLIED_THEME_ASSET_ROOT = DATA_ROOT / "applied-theme-assets"
LEGACY_THEME_ROOT = themes.PERSISTENT_THEME_ROOT
MIGRATION_META = "v116_applied_theme_assets_migrated"
STATUS_META = "v116_applied_theme_assets_status"

_LOCK = threading.RLock()
_INSTALLED = False
_BASE_SET_CONFIG = None
_LAST_ORGANIZATION_VERSION = None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source, destination, replace_existing=False):
    """Atomically copy one image and verify its bytes before it becomes live."""
    source = Path(source)
    destination = Path(destination)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))

    destination.parent.mkdir(parents=True, exist_ok=True)
    source_hash = _sha256(source)
    if destination.exists() and not replace_existing:
        # Once v116 owns the destination, it is the authoritative applied copy.
        # A stale legacy file must never overwrite a newer applied asset.
        return destination
    if destination.exists() and _sha256(destination) == source_hash:
        return destination

    temporary = destination.with_name(
        f".{destination.name}.v116-{uuid.uuid4().hex[:10]}.tmp"
    )
    try:
        shutil.copy2(source, temporary)
        if _sha256(temporary) != source_hash:
            raise IOError(f"Verification failed while copying {source.name}.")
        os.replace(temporary, destination)
        if _sha256(destination) != source_hash:
            raise IOError(f"Verification failed after saving {destination.name}.")
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except Exception:
            pass
    return destination


def _safe_filename(value):
    filename = Path(str(value or "")).name
    if not filename or Path(filename).suffix.lower() not in themes.VALID_EXTENSIONS:
        return ""
    return filename


def _builtin_source(base, asset_key):
    if base != "undisputed":
        return None
    definition = themes.ASSETS.get(asset_key) or {}
    filename = str(definition.get("builtin") or "").strip()
    if not filename:
        return None
    candidate = themes.BUILTIN_THEME_ROOT / "undisputed" / filename
    return candidate if candidate.exists() else None


def _materialize_config(scope, team, config, initial_migration=False):
    """Return a config whose effective image assets all live in v116 storage."""
    result = dict(config or {})
    base = str(result.get("base") or themes._default_base(team)).strip().lower()
    if base not in {"classic", "undisputed"}:
        base = "classic"
    result["base"] = base

    raw_assets = result.get("assets") if isinstance(result.get("assets"), dict) else {}
    assets = dict(raw_assets)
    changed = assets != raw_assets

    for asset_key in themes.ASSETS:
        configured = _safe_filename(assets.get(asset_key))
        destination = (
            APPLIED_THEME_ASSET_ROOT / scope / configured
            if configured else None
        )

        # Existing v116 file is already authoritative after the first completed
        # migration. During the first migration we still compare/copy from the
        # legacy source so a partial earlier attempt cannot commit wrong bytes.
        if destination is not None and destination.exists() and not initial_migration:
            continue

        legacy_source = None
        if configured:
            candidate = LEGACY_THEME_ROOT / scope / configured
            if candidate.exists() and candidate.is_file():
                legacy_source = candidate

        if legacy_source is not None:
            _copy_verified(
                legacy_source,
                destination,
                replace_existing=bool(initial_migration),
            )
            continue

        # If an explicit override disappeared under the old runtime, an
        # UNDISPUTED theme already fell back to its shipped built-in. Preserve
        # that exact effective appearance by materializing the built-in now.
        builtin = _builtin_source(base, asset_key)
        if builtin is not None:
            ext = builtin.suffix.lower()
            filename = f"{asset_key}{ext}"
            target = APPLIED_THEME_ASSET_ROOT / scope / filename
            _copy_verified(
                builtin,
                target,
                replace_existing=bool(initial_migration),
            )
            if assets.get(asset_key) != filename:
                assets[asset_key] = filename
                changed = True
            continue

        # Classic has no built-in image fallback. A missing old override was
        # already visually absent, so leaving its stale reference is harmless
        # and preserves the config rather than inventing a replacement.

    result["assets"] = assets
    return result, changed


def _theme_store(settings):
    return themes._theme_store(settings)


def _save_migrated_store(settings, store):
    settings["theme_config"] = store
    save_settings(settings)
    set_meta("settings_version", int(get_meta("settings_version", "0") or 0) + 1)


def ensure_all_applied_assets(initial_migration=False):
    """Materialize every existing team theme, including implicit presets."""
    with _LOCK:
        settings = get_settings()
        store = _theme_store(settings)
        changed = False

        for team in get_team_definitions(include_inactive=True):
            team_id = int(team["team_id"])
            scope = f"team-{team_id}"
            key = str(team_id)
            current = dict(store["teams"].get(key, {}))
            materialized, config_changed = _materialize_config(
                scope,
                team,
                current,
                initial_migration=initial_migration,
            )

            # An implicit UNDISPUTED preset has no row in theme_config yet. It
            # still uses shipped artwork, so persist it even when no previous
            # custom config existed.
            should_store = bool(current) or materialized.get("assets")
            if should_store and (config_changed or store["teams"].get(key) != materialized):
                store["teams"][key] = materialized
                changed = True

        if changed:
            _save_migrated_store(settings, store)
        return changed


def _install_set_config_guard():
    global _BASE_SET_CONFIG
    if _BASE_SET_CONFIG is not None:
        return
    _BASE_SET_CONFIG = themes._set_config

    def persistent_set_config(settings, scope, team, config):
        materialized, _changed = _materialize_config(
            scope,
            team,
            config,
            initial_migration=False,
        )
        return _BASE_SET_CONFIG(settings, scope, team, materialized)

    themes._set_config = persistent_set_config


def _organization_guard():
    """Catch teams created after startup without doing filesystem work per poll."""
    global _LAST_ORGANIZATION_VERSION
    version = str(get_meta("organization_version", "0") or "0")
    if version == _LAST_ORGANIZATION_VERSION:
        return None
    _LAST_ORGANIZATION_VERSION = version
    try:
        ensure_all_applied_assets(initial_migration=False)
    except Exception as exc:
        set_meta(STATUS_META, f"Applied theme asset repair failed: {exc}")
    return None


def install(app):
    """Migrate safely, then make the persistent applied store authoritative."""
    global _INSTALLED, _LAST_ORGANIZATION_VERSION
    with _LOCK:
        if _INSTALLED:
            return False

        first_migration = str(get_meta(MIGRATION_META, "") or "") != "1"
        try:
            APPLIED_THEME_ASSET_ROOT.mkdir(parents=True, exist_ok=True)
            ensure_all_applied_assets(initial_migration=first_migration)
        except Exception as exc:
            # Do not switch the runtime root or rewrite the migration marker.
            # The legacy persistent theme folder and built-ins continue to work.
            set_meta(STATUS_META, f"Migration not activated: {exc}")
            return False

        # Only after every required copy has succeeded do theme URLs start
        # resolving against the permanent applied store.
        themes.PERSISTENT_THEME_ROOT = APPLIED_THEME_ASSET_ROOT
        _install_set_config_guard()
        set_meta(MIGRATION_META, "1")
        set_meta(
            STATUS_META,
            f"Applied theme assets protected in {APPLIED_THEME_ASSET_ROOT}",
        )
        _LAST_ORGANIZATION_VERSION = str(
            get_meta("organization_version", "0") or "0"
        )

        # A newly-created team can have an implicit preset before anyone opens
        # Theme Studio. Materialize it on the next request after organization
        # changes so even that case never depends on shipped artwork long-term.
        app.before_request(_organization_guard)
        _INSTALLED = True
        return True
