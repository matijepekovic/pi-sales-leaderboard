#!/usr/bin/env python3
"""Verify a signed production release manifest and its local assets."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DEFAULT_PUBLIC_KEY_B64 = "5BKW4eUps39+GhTRnHHzqGz03VNembdmaYBoqagzqr4="


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="dist/release-manifest.json")
    parser.add_argument("--signature", default="dist/release-manifest.json.sig")
    parser.add_argument("--asset-dir", default="dist")
    parser.add_argument("--public-key-b64", default=DEFAULT_PUBLIC_KEY_B64)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    signature_path = Path(args.signature)
    asset_dir = Path(args.asset_dir)

    manifest_bytes = manifest_path.read_bytes()
    signature = base64.b64decode(signature_path.read_text(encoding="utf-8").strip(), validate=True)
    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(args.public_key_b64, validate=True))
    public_key.verify(signature, manifest_bytes)

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema") != 1:
        raise SystemExit("unsupported release manifest schema")

    for item in manifest.get("assets", []):
        name = item.get("name")
        if not name or Path(name).name != name:
            raise SystemExit("invalid asset name in release manifest")
        path = asset_dir / name
        if not path.is_file():
            raise SystemExit(f"missing asset: {name}")
        if path.stat().st_size != int(item.get("size", -1)):
            raise SystemExit(f"size mismatch: {name}")
        if _sha256(path) != item.get("sha256"):
            raise SystemExit(f"SHA-256 mismatch: {name}")

    print(f"verified release manifest for {manifest.get('version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
