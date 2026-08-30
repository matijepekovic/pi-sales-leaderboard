"""Persistent application paths and one-time legacy migration."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

LEGACY_DATA_RELATIVE = Path(".local") / "share" / "pi-tableau-leaderboard"
MIGRATION_MARKER = ".stats-data-migrated"


def legacy_data_dir() -> Path:
    return Path.home() / LEGACY_DATA_RELATIVE


def persistent_data_dir() -> Path:
    """Return the canonical persistent data directory for this machine."""
    override = str(os.environ.get("STATS_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser()

    if os.name == "nt":
        local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
        root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return root / "Stats" / "data"

    return legacy_data_dir()


def _copy_missing(source: Path, target: Path) -> None:
    """Copy a tree without replacing anything already present at the target."""
    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source)
        target_path = target / relative
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        elif not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


def migrate_legacy_data(source: Path, target: Path) -> bool:
    """Copy missing legacy data once, leaving the old directory as a backup."""
    source = Path(source)
    target = Path(target)
    if source == target or not source.exists():
        return False

    target.mkdir(parents=True, exist_ok=True)
    marker = target / MIGRATION_MARKER
    if marker.exists():
        return False

    _copy_missing(source, target)
    marker.write_text(str(source), encoding="utf-8")
    return True


def prepare_data_dir() -> Path:
    """Create the canonical directory and migrate the former Windows path once."""
    target = persistent_data_dir()
    target.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("STATS_DATA_DIR") and os.name == "nt":
        migrate_legacy_data(legacy_data_dir(), target)

    return target
