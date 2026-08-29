"""Application identity/version service."""
from __future__ import annotations

from pathlib import Path


class VersionService:
    def __init__(self, app_root: Path):
        self.app_root = Path(app_root)
        self.version_file = self.app_root / "VERSION"

    def current(self):
        try:
            return self.version_file.read_text(encoding="utf-8").strip() or "unknown"
        except Exception:
            return "unknown"
