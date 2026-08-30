"""Signed Windows installer update client."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from flask import jsonify

from stats_core.windows import https
from stats_core.windows.signing_key import UPDATE_SIGNING_PUBLIC_KEY_B64

UPDATE_REPO = "matijepekovic/pi-sales-leaderboard-updates"
LATEST_MANIFEST_URL = (
    f"https://github.com/{UPDATE_REPO}/releases/latest/download/"
    "release-manifest.json"
)
LATEST_SIGNATURE_URL = (
    f"https://github.com/{UPDATE_REPO}/releases/latest/download/"
    "release-manifest.json.sig"
)
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_METADATA_BYTES = 512 * 1024
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
_INSTALLED = False


def _version_tuple(value: str) -> tuple[int, int, int]:
    value = str(value or "").strip()
    if not SEMVER_RE.fullmatch(value):
        raise ValueError("Invalid production version")
    return tuple(int(part) for part in value.split("."))


def _trusted_release_asset_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or ""))
    prefix = f"/{UPDATE_REPO}/releases/download/"
    return (
        parsed.scheme == "https"
        and parsed.netloc == "github.com"
        and parsed.path.startswith(prefix)
    )


def _read_url(url: str, *, max_bytes: int = MAX_METADATA_BYTES) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "Stats-Windows-Updater",
        },
    )
    with urllib.request.urlopen(
        request,
        timeout=30,
        context=https.ssl_context(),
    ) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Update metadata is too large")
    return data


def verify_manifest(
    manifest_bytes: bytes,
    signature_bytes: bytes,
    public_key_b64: str = UPDATE_SIGNING_PUBLIC_KEY_B64,
) -> dict:
    """Verify exact manifest bytes and return a validated schema-1 manifest."""
    try:
        signature = base64.b64decode(
            signature_bytes.decode("ascii").strip(), validate=True
        )
        public_raw = base64.b64decode(public_key_b64, validate=True)
        if len(public_raw) != 32:
            raise ValueError("Invalid update public key")
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            signature, manifest_bytes
        )
    except Exception as exc:
        raise ValueError("Update signature verification failed") from exc

    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid update manifest JSON") from exc

    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise ValueError("Unsupported update manifest")
    version = str(manifest.get("version") or "")
    _version_tuple(version)

    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("Update manifest has no assets")

    names: set[str] = set()
    for item in assets:
        if not isinstance(item, dict):
            raise ValueError("Invalid update asset entry")
        name = str(item.get("name") or "")
        if not name or Path(name).name != name or name in names:
            raise ValueError("Invalid update asset name")
        names.add(name)
        digest = str(item.get("sha256") or "").lower()
        if not SHA256_RE.fullmatch(digest):
            raise ValueError("Invalid update asset hash")
        try:
            size = int(item.get("size"))
        except Exception as exc:
            raise ValueError("Invalid update asset size") from exc
        if size <= 0 or size > MAX_INSTALLER_BYTES:
            raise ValueError("Invalid update asset size")
    return manifest


def _manifest_asset(manifest: dict, name: str) -> dict:
    matches = [item for item in manifest["assets"] if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Signed manifest does not contain exactly one {name}")
    return matches[0]


def latest_release_info(local_version: str) -> dict:
    """Read latest signed metadata without using the rate-limited GitHub API."""
    local_version = str(local_version or "").strip()
    _version_tuple(local_version)

    manifest_bytes = _read_url(LATEST_MANIFEST_URL)
    signature_bytes = _read_url(LATEST_SIGNATURE_URL, max_bytes=16 * 1024)
    manifest = verify_manifest(manifest_bytes, signature_bytes)
    remote_version = str(manifest["version"])

    installer_name = f"Stats-Setup-{remote_version}-windows-x64.exe"
    signed_installer = _manifest_asset(manifest, installer_name)
    installer_url = (
        f"https://github.com/{UPDATE_REPO}/releases/download/"
        f"v{remote_version}/{installer_name}"
    )
    if not _trusted_release_asset_url(installer_url):
        raise ValueError("Could not construct trusted installer URL")

    return {
        "current": local_version,
        "latest": remote_version,
        "available": _version_tuple(remote_version) > _version_tuple(local_version),
        "installer_name": installer_name,
        "installer_url": installer_url,
        "sha256": str(signed_installer["sha256"]).lower(),
        "size": int(signed_installer["size"]),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_installer(info: dict, destination: Path) -> None:
    if not _trusted_release_asset_url(info["installer_url"]):
        raise ValueError("Untrusted installer URL")
    expected_size = int(info["size"])
    if expected_size <= 0 or expected_size > MAX_INSTALLER_BYTES:
        raise ValueError("Invalid signed installer size")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        info["installer_url"],
        headers={"User-Agent": "Stats-Windows-Updater"},
    )
    written = 0
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(
            request,
            timeout=60,
            context=https.ssl_context(),
        ) as response, temporary.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > expected_size or written > MAX_INSTALLER_BYTES:
                    raise ValueError(
                        "Downloaded installer is larger than the signed size"
                    )
                digest.update(chunk)
                handle.write(chunk)
        if written != expected_size:
            raise ValueError(
                "Downloaded installer size does not match signed manifest"
            )
        if digest.hexdigest() != info["sha256"]:
            raise ValueError(
                "Downloaded installer SHA-256 does not match signed manifest"
            )
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _installed_root() -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Windows installer updates require the packaged Stats build")
    return Path(sys.executable).resolve().parent.parent


def _start_detached_updater(installer: Path, version: str) -> None:
    root = _installed_root()
    source_helper = root / "StatsUpdater.exe"
    launcher = root / "StatsLauncher.exe"
    if not source_helper.is_file() or not launcher.is_file():
        raise RuntimeError("Installed Stats update helper is missing")

    update_dir = installer.parent
    helper = update_dir / "StatsUpdater.exe"
    shutil.copy2(source_helper, helper)
    subprocess.Popen(
        [
            str(helper),
            "--installer",
            str(installer),
            "--launcher",
            str(launcher),
            "--version",
            version,
        ],
        cwd=str(update_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=(
            DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        ),
    )


def install(app, data_dir, version) -> bool:
    """Install the update routes. `version` is a callable returning the
    installed version string; `data_dir` is where downloads are cached."""
    global _INSTALLED
    if _INSTALLED:
        return False

    @app.post("/api/windows/update/check")
    def windows_update_check():
        try:
            info = latest_release_info(version())
            return jsonify({
                "ok": True,
                "current": info["current"],
                "latest": info["latest"],
                "available": info["available"],
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    @app.post("/api/windows/update/install")
    def windows_update_install():
        try:
            info = latest_release_info(version())
            if not info["available"]:
                return jsonify({
                    "ok": True,
                    "installed": False,
                    "current": info["current"],
                    "latest": info["latest"],
                })

            update_root = (
                Path(data_dir)
                / "updates"
                / "windows"
                / info["latest"]
            )
            installer = update_root / info["installer_name"]
            valid_cached = (
                installer.is_file()
                and installer.stat().st_size == info["size"]
                and _sha256(installer) == info["sha256"]
            )
            if not valid_cached:
                installer.unlink(missing_ok=True)
                _download_installer(info, installer)

            if (
                installer.stat().st_size != info["size"]
                or _sha256(installer) != info["sha256"]
            ):
                raise ValueError("Verified installer changed before launch")

            _start_detached_updater(installer, info["latest"])
            return jsonify({
                "ok": True,
                "installed": True,
                "installing": True,
                "version": info["latest"],
            }), 202
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502

    _INSTALLED = True
    return True
