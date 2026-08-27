#!/usr/bin/env python3
"""Create and sign a production release manifest.

The private key is supplied only through UPDATE_SIGNING_PRIVATE_KEY.
The manifest contains hashes and sizes for prebuilt release assets. The exact
manifest bytes are signed with Ed25519 and written beside the manifest as a
base64 signature.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_private_key() -> Ed25519PrivateKey:
    pem = os.environ.get("UPDATE_SIGNING_PRIVATE_KEY", "").strip()
    if not pem:
        raise SystemExit("UPDATE_SIGNING_PRIVATE_KEY is not set")
    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("UPDATE_SIGNING_PRIVATE_KEY is not an Ed25519 private key")
    return key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("assets", nargs="+")
    args = parser.parse_args()

    if not SEMVER_RE.fullmatch(args.version):
        raise SystemExit("version must be MAJOR.MINOR.PATCH")

    assets = [Path(value).resolve() for value in args.assets]
    missing = [str(path) for path in assets if not path.is_file()]
    if missing:
        raise SystemExit("missing release assets: " + ", ".join(missing))

    names = [path.name for path in assets]
    if len(set(names)) != len(names):
        raise SystemExit("release asset filenames must be unique")

    manifest = {
        "schema": 1,
        "version": args.version,
        "assets": [
            {
                "name": path.name,
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
            for path in sorted(assets, key=lambda item: item.name.lower())
        ],
    }

    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "release-manifest.json"
    signature_path = output_dir / "release-manifest.json.sig"

    manifest_path.write_bytes(manifest_bytes)
    signature = _load_private_key().sign(manifest_bytes)
    signature_path.write_text(base64.b64encode(signature).decode("ascii") + "\n", encoding="utf-8")

    print(manifest_path)
    print(signature_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
