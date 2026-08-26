"""v118 runtime guard after shipped default theme artwork is removed.

Existing applied themes remain valid because v116 serves their verified copies
from the persistent applied-theme-assets store. This guard prevents any future
runtime fallback to shipped static artwork and makes new/implicit teams start
Classic instead of expecting a deleted bundled image preset.

For a Pi jumping directly from a pre-v116 release, install.sh temporarily
restores its *old installed* default pack long enough for v116 to migrate it.
This module deletes that compatibility copy only after the migration marker is
confirmed, then removes the staging copy as well.
"""
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from database import get_meta, set_meta
import applied_theme_assets_v116
import themes

_INSTALLED = False
_BASE_ASSET_URL = None
_BASE_DEFAULT_BASE = None
_STATIC_PREFIXES = ("/static/theme-packs/", "/static/asset-library/")
_COMPAT_STAGE = (
    Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
    / "v118-default-migration-source"
)


def _migration_complete():
    return str(get_meta(applied_theme_assets_v116.MIGRATION_META, "") or "") == "1"


def _remove_compatibility_defaults():
    """Remove temporary old-install defaults only after v116 is confirmed."""
    if not _migration_complete():
        return False
    try:
        shutil.rmtree(themes.BUILTIN_THEME_ROOT / "undisputed", ignore_errors=True)
        shutil.rmtree(_COMPAT_STAGE, ignore_errors=True)
        set_meta("v118_removed_default_assets_status", "Shipped default theme artwork removed")
        return True
    except Exception as exc:
        set_meta("v118_removed_default_assets_status", f"Default cleanup failed: {exc}")
        return False


def install():
    global _INSTALLED, _BASE_ASSET_URL, _BASE_DEFAULT_BASE
    if _INSTALLED:
        return False

    # Never activate the no-default runtime until the permanent migration has
    # actually completed on this Pi. Older installs keep their compatibility
    # copy intact until v116 succeeds.
    if not _migration_complete():
        set_meta(
            "v118_removed_default_assets_status",
            "Waiting for applied-theme asset migration before removing defaults",
        )
        return False

    _remove_compatibility_defaults()
    _BASE_ASSET_URL = themes._asset_url
    _BASE_DEFAULT_BASE = themes._default_base

    def asset_url_v118(scope, asset_key, config, base, version):
        url = _BASE_ASSET_URL(scope, asset_key, config, base, version)
        path = urlsplit(str(url or "")).path
        if any(path.startswith(prefix) for prefix in _STATIC_PREFIXES):
            return None
        return url

    def default_base_v118(team=None):
        # Existing themes migrated by v116 have an explicit stored base/assets.
        # Only a genuinely new/implicit theme reaches this default.
        return "classic"

    themes._asset_url = asset_url_v118
    themes._default_base = default_base_v118
    _INSTALLED = True
    return True
