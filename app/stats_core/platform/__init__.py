"""Platform adapters for Stats.

Adapters are resolved by name here rather than imported by the composition
root, so importing stats_core.bootstrap does not drag in an operating system.
The import of a concrete adapter happens inside create_platform, at the moment
one is actually asked for.
"""
from __future__ import annotations

from stats_core.platform.base import Platform

PLATFORMS = ("windows",)


def create_platform(name, repos, data_dir, version_service) -> Platform:
    """Build the adapter for `name`, importing only that adapter."""
    key = str(name or "").strip().lower()
    if key == "windows":
        from stats_core.platform.windows import WindowsPlatform

        return WindowsPlatform(repos, data_dir, version_service)
    raise ValueError(
        f"Unknown platform {name!r}. Available: {', '.join(PLATFORMS)}."
    )


__all__ = ["Platform", "PLATFORMS", "create_platform"]
