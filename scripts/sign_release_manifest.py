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
PRIVATE_KEY_BEGIN = "-----BEGIN PRIVATE KEY-----"
PRIVATE_KEY_END = "-----END PRIVATE KEY-----"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_private_key_pem(value: str) -> str:
    """Normalize safe GitHub-secret formatting without changing key bytes.

    GitHub preserves multiline secrets, but copy/paste from some mobile/file
    viewers can flatten PEM line breaks into spaces or literal ``\\n`` text.
    Rebuild the standard PKCS#8 PEM framing from the existing BEGIN/END markers
    so the same private key works in all of those representations.
    """
    value = (value or "").strip().lstrip("\ufeff")
    value = value.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")

    begin = value.find(PRIVATE_KEY_BEGIN)
    end = value.find(PRIVATE_KEY_END)
    if begin >= 0 and end > begin:
        body = value[begin + len(PRIVATE_KEY_BEGIN):end]
        body = re.sub(r"\s+", "", body)
        if not body or re.fullmatch(r"[A-Za-z0-9+/=]+", body) is None:
            raise SystemExit("UPDATE_SIGNING_PRIVATE_KEY has invalid PEM content")
        wrapped = "\n".join(body[i:i + 64] for i in range(0, len(body), 64))
        return f"{PRIVATE_KEY_BEGIN}\n{wrapped}\n{PRIVATE_KEY_END}\n"

    return value


def _load_private_key() -> Ed25519PrivateKey:
    pem = os.environ.get("UPDATE_SIGNING_PRIVATE_KEY", "")
    if not pem.strip():
        raise SystemExit("UPDATE_SIGNING_PRIVATE_KEY is not set")

    normalized = _canonical_private_key_pem(pem)
    try:
        key = serialization.load_pem_private_key(
            normalized.encode("utf-8"), password=None
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit(
            "UPDATE_SIGNING_PRIVATE_KEY could not be read as a PKCS#8 PEM key"
        ) from exc

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
    signature_path.write_text(
        base64.b64encode(signature).decode("ascii") + "\n",
        encoding="utf-8",
    )

    print(manifest_path)
    print(signature_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
