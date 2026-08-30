"""HTTPS trust for packaged Windows services."""
from __future__ import annotations

import ssl
import sys
from functools import lru_cache
from pathlib import Path

import certifi


@lru_cache(maxsize=1)
def _context_and_info():
    ca_bundle = Path(certifi.where())
    if not ca_bundle.is_file():
        raise RuntimeError("Bundled HTTPS CA certificate file is missing")

    context = ssl.create_default_context(cafile=str(ca_bundle))
    windows_loaded = 0
    store_errors = []

    if sys.platform == "win32" and hasattr(ssl, "enum_certificates"):
        for store_name in ("ROOT", "CA"):
            try:
                entries = ssl.enum_certificates(store_name)
            except Exception as exc:
                store_errors.append(f"{store_name}: {type(exc).__name__}: {exc}")
                continue

            for cert_bytes, encoding_type, _trust in entries:
                if encoding_type != "x509_asn":
                    continue
                try:
                    pem = ssl.DER_cert_to_PEM_cert(cert_bytes)
                    context.load_verify_locations(cadata=pem)
                    windows_loaded += 1
                except Exception:
                    continue

    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    info = {
        "provider": "certifi+windows" if sys.platform == "win32" else "certifi",
        "ca_bundle": str(ca_bundle),
        "ca_bundle_available": True,
        "windows_certificates_loaded": windows_loaded,
        "windows_store_errors": store_errors,
    }
    return context, info


def ssl_context():
    """Return the cached verified outbound HTTPS context."""
    return _context_and_info()[0]


def diagnostics():
    """Return non-secret trust information for the Software diagnostics UI."""
    _context, info = _context_and_info()
    return dict(info)
