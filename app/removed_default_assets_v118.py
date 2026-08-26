"""v118 runtime guard after shipped default theme artwork is removed.

Existing applied themes remain valid because v116 serves their verified copies
from the persistent applied-theme-assets store. This guard prevents any future
runtime fallback to shipped static artwork and makes new/implicit teams start
Classic instead of expecting a deleted bundled image preset.
"""
from urllib.parse import urlsplit

import themes

_INSTALLED = False
_BASE_ASSET_URL = None
_BASE_DEFAULT_BASE = None
_STATIC_PREFIXES = ("/static/theme-packs/", "/static/asset-library/")


def install():
    global _INSTALLED, _BASE_ASSET_URL, _BASE_DEFAULT_BASE
    if _INSTALLED:
        return False

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
