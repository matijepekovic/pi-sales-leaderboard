"""Read-only diagnostics for the signed Windows update path."""
from __future__ import annotations

import ssl
import sys

from flask import jsonify

from stats_core.windows import https, update

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
        lambda: f"{update._version_tuple(installed_version)} ({installed_version})",
    ))
    checks.append(_check(
        "https_trust",
        lambda: (
            f"provider={https.diagnostics()['provider']}; "
            "windows_certificates_loaded="
            f"{https.diagnostics()['windows_certificates_loaded']}"
        ),
    ))

    state = {}

    def read_manifest():
        data = update._read_url(update.LATEST_MANIFEST_URL)
        state["manifest"] = data
        return f"Downloaded {len(data)} bytes"

    def read_signature():
        data = update._read_url(update.LATEST_SIGNATURE_URL, max_bytes=16 * 1024)
        state["signature"] = data
        return f"Downloaded {len(data)} bytes"

    checks.append(_check("manifest_download", read_manifest))
    checks.append(_check("signature_download", read_signature))

    def verify_signature():
        if "manifest" not in state or "signature" not in state:
            raise RuntimeError(
                "Skipped because update metadata could not be downloaded"
            )
        manifest = update.verify_manifest(state["manifest"], state["signature"])
        state["verified_manifest"] = manifest
        return f"Verified signed manifest for {manifest['version']}"

    checks.append(_check("signature_verification", verify_signature))

    def resolve_latest():
        info = update.latest_release_info(installed_version)
        return (
            f"Latest {info['latest']}; available={str(info['available']).lower()}; "
            f"installer={info['installer_name']}"
        )

    checks.append(_check("latest_release_resolution", resolve_latest))

    try:
        trust = https.diagnostics()
    except Exception as exc:
        trust = {"provider": "unavailable", "error": _error_text(exc)}

    return {
        "ok": all(item["ok"] for item in checks),
        "installed_version": installed_version,
        "checks": checks,
        "environment": {
            "packaged": bool(getattr(sys, "frozen", False)),
            "openssl": ssl.OPENSSL_VERSION,
            "https_trust": trust,
        },
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
