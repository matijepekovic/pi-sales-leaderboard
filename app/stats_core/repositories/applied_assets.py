from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path


class AppliedAssetRepository:
    """Persistent copies of artwork that is actively used by a theme."""

    USER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
    EXTENSIONS = USER_IMAGE_EXTENSIONS | {".svg"}

    def __init__(self, data_root: Path, static_root: Path):
        self.data_root = Path(data_root)
        self.static_root = Path(static_root)
        self.legacy_theme_root = self.data_root / "themes"
        self.root = self.data_root / "applied-theme-assets"
        self.theme_pack_root = self.static_root / "theme-packs"

    @staticmethod
    def sha256(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def copy_verified(self, source, destination, replace_existing=False):
        source = Path(source)
        destination = Path(destination)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(str(source))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_hash = self.sha256(source)
        if destination.exists() and not replace_existing:
            return destination
        if destination.exists() and self.sha256(destination) == source_hash:
            return destination
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex[:10]}.tmp")
        try:
            shutil.copy2(source, temporary)
            if self.sha256(temporary) != source_hash:
                raise IOError(f"Verification failed while copying {source.name}.")
            os.replace(temporary, destination)
            if self.sha256(destination) != source_hash:
                raise IOError(f"Verification failed after saving {destination.name}.")
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    @classmethod
    def safe_filename(cls, value):
        filename = Path(str(value or "")).name
        if not filename or Path(filename).suffix.lower() not in cls.EXTENSIONS:
            return ""
        return filename

    def path(self, scope, filename):
        filename = self.safe_filename(filename)
        if not filename:
            return None
        root = self.root / scope
        path = root / filename
        try:
            path.resolve().relative_to(root.resolve())
        except Exception:
            return None
        return path

    def legacy_path(self, scope, filename):
        filename = self.safe_filename(filename)
        if not filename:
            return None
        root = self.legacy_theme_root / scope
        path = root / filename
        try:
            path.resolve().relative_to(root.resolve())
        except Exception:
            return None
        return path

    def remove(self, scope, asset_key):
        folder = self.root / scope
        if not folder.exists():
            return
        for candidate in folder.glob(f"{asset_key}*"):
            if candidate.is_file() and candidate.suffix.lower() in self.EXTENSIONS:
                candidate.unlink(missing_ok=True)

    def save_upload(self, scope, asset_key, upload, extension):
        folder = self.root / scope
        folder.mkdir(parents=True, exist_ok=True)
        self.remove(scope, asset_key)
        filename = f"{asset_key}{extension}"
        destination = folder / filename
        upload.save(destination)
        return destination, filename

    def copy(self, scope, asset_key, source):
        source = Path(source)
        folder = self.root / scope
        folder.mkdir(parents=True, exist_ok=True)
        self.remove(scope, asset_key)
        filename = f"{asset_key}{source.suffix.lower()}"
        destination = folder / filename
        self.copy_verified(source, destination, replace_existing=True)
        return destination, filename
