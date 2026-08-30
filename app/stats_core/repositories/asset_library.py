from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from .applied_assets import AppliedAssetRepository


class AssetLibraryRepository:
    """Reusable user/built-in artwork, separate from currently applied copies."""

    def __init__(self, data_root: Path, static_root: Path):
        self.root = Path(data_root) / "asset-library"
        self.builtin_root = Path(static_root) / "asset-library"
        self.theme_pack_root = Path(static_root) / "theme-packs"

    def directory(self, asset_key):
        return self.root / str(asset_key)

    def read_index(self, asset_key):
        path = self.directory(asset_key) / "index.json"
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [row for row in rows if isinstance(row, dict)]

    def write_index(self, asset_key, rows):
        folder = self.directory(asset_key)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.json").write_text(json.dumps(list(rows), indent=2), encoding="utf-8")

    def item_path(self, asset_key, item_id):
        item_id = str(item_id or "").strip()
        if not item_id or not item_id.replace("-", "").isalnum():
            return None
        for row in self.read_index(asset_key):
            if str(row.get("id")) != item_id:
                continue
            ext = str(row.get("ext") or ".png").lower()
            if ext not in AppliedAssetRepository.USER_IMAGE_EXTENSIONS:
                return None
            candidate = self.directory(asset_key) / f"{item_id}{ext}"
            return candidate if candidate.exists() else None
        return None

    def add_file(self, asset_key, source_path, label, extension=None):
        source_path = Path(source_path)
        extension = (extension or source_path.suffix).lower()
        if extension not in AppliedAssetRepository.USER_IMAGE_EXTENSIONS:
            return ""
        item_id = uuid.uuid4().hex[:16]
        folder = self.directory(asset_key)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, folder / f"{item_id}{extension}")
        rows = self.read_index(asset_key)
        rows.insert(0, {
            "id": item_id,
            "label": str(label or "Untitled")[:120],
            "ext": extension,
            "created": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        })
        self.write_index(asset_key, rows[:200])
        return item_id

    def save_upload(self, asset_key, upload, extension, label):
        item_id = uuid.uuid4().hex[:16]
        folder = self.directory(asset_key)
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"{item_id}{extension}"
        upload.save(destination)
        rows = self.read_index(asset_key)
        rows.insert(0, {
            "id": item_id,
            "label": str(label or "Untitled")[:120],
            "ext": extension,
            "created": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        })
        self.write_index(asset_key, rows[:200])
        return item_id, destination

    def delete(self, asset_key, item_id):
        path = self.item_path(asset_key, item_id)
        if not path:
            return False
        path.unlink(missing_ok=True)
        self.write_index(
            asset_key,
            [row for row in self.read_index(asset_key) if str(row.get("id")) != str(item_id)],
        )
        return True

    def builtin_catalog(self):
        try:
            return json.loads((self.builtin_root / "catalog.json").read_text(encoding="utf-8"))
        except Exception:
            return {"collections": []}

    def resolve_builtin_url(self, url):
        clean = str(url or "").split("?", 1)[0]
        roots = {
            "/static/asset-library/": self.builtin_root,
            "/static/theme-packs/": self.theme_pack_root,
        }
        for prefix, root in roots.items():
            if not clean.startswith(prefix):
                continue
            candidate = (root / clean[len(prefix):]).resolve()
            try:
                candidate.relative_to(root.resolve())
            except Exception:
                return None
            if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in AppliedAssetRepository.EXTENSIONS:
                return candidate
        return None
