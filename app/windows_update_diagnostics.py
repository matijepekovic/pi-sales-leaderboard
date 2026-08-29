"""Windows updater diagnostics.

This module owns read-only diagnostics for the signed Windows update path.
It is intentionally separate from windows_update.py so diagnostics can later
move behind a Windows platform/service interface without changing updater
behavior.
"""
from __future__ import annotations

import ssl
import sys
from pathlib import Path

from flask import jsonify

import windows_update

_INSTALLED = False


def _error_text(exc):
    text = str(exc).strip() or repr(exc)
    return f"{type(exc).__name__}: {text}"[:800]


def _check(name, action):
    try:
        detail = action()
        return {"name": name, "ok": True, "detail": str(detail or "OK")[:800]}
    except Exception as exc:
        return {"name": name, "ok": False, "error": _error_text(exc)}


def collect_diagnostics(server_module):
    """Run the update-check path in observable stages without changing state."""
    installed_version = str(server_module.software_version() or "").strip()
    checks = []

    checks.append(_check(
        "installed_version",
        lambda: f"{windows_update._version_tuple(installed_version)} ({installed_version})",
    ))

    state = {}

    def read_manifest():
        data = windows_update._read_url(windows_update.LATEST_MANIFEST_URL)
        state["manifest"] = data
        return f"Downloaded {len(data)} bytes"

    def read_signature():
        data = windows_update._read_url(
            windows_update.LATEST_SIGNATURE_URL,
            max_bytes=16 * 1024,
        )
        state["signature"] = data
        return f"Downloaded {len(data)} bytes"

    checks.append(_check("manifest_download", read_manifest))
    checks.append(_check("signature_download", read_signature))

    def verify_signature():
        if "manifest" not in state or "signature" not in state:
            raise RuntimeError("Skipped because update metadata could not be downloaded")
        manifest = windows_update.verify_manifest(
            state["manifest"],
            state["signature"],
        )
        state["verified_manifest"] = manifest
        return f"Verified signed manifest for {manifest['version']}"

    checks.append(_check("signature_verification", verify_signature))

    def resolve_latest():
        info = windows_update.latest_release_info(installed_version)
        return (
            f"Latest {info['latest']}; available={str(info['available']).lower()}; "
            f"installer={info['installer_name']}"
        )

    checks.append(_check("latest_release_resolution", resolve_latest))

    verify_paths = ssl.get_default_verify_paths()
    environment = {
        "packaged": bool(getattr(sys, "frozen", False)),
        "openssl": ssl.OPENSSL_VERSION,
        "default_cafile_available": bool(
            verify_paths.cafile and Path(verify_paths.cafile).is_file()
        ),
        "default_capath_available": bool(
            verify_paths.capath and Path(verify_paths.capath).is_dir()
        ),
    }

    return {
        "ok": all(item["ok"] for item in checks),
        "installed_version": installed_version,
        "checks": checks,
        "environment": environment,
    }


def install(app, server_module):
    global _INSTALLED
    if _INSTALLED:
        return False

    @app.get("/api/windows/update/diagnostics")
    def windows_update_diagnostics():
        return jsonify(collect_diagnostics(server_module))

    _INSTALLED = True
    return True
