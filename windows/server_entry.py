#!/usr/bin/env python3
"""Frozen Windows entrypoint for the Stats backend."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path


def _persistent_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "pi-tableau-leaderboard"


def _install_file_logging() -> None:
    log_dir = _persistent_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / "windows-server.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log


def _start_remote_qr_refresh() -> None:
    """Keep the phone QR tied to the current Windows LAN address."""
    import remote_qr_v109

    def refresh_once() -> None:
        try:
            url = remote_qr_v109.generate()
            print(f"Stats phone remote QR: {url}")
        except Exception as exc:
            print(f"Stats phone remote QR refresh failed: {exc}")

    # Generate synchronously so the file exists before the launcher opens the
    # fullscreen browser. Then refresh periodically in case DHCP/VPN/Wi-Fi
    # changes the address while Stats stays open.
    refresh_once()

    def worker() -> None:
        while True:
            time.sleep(30)
            refresh_once()

    threading.Thread(target=worker, name="stats-remote-qr", daemon=True).start()


def main() -> int:
    _install_file_logging()
    os.environ["STATS_WINDOWS_BUILD"] = "1"

    # The app modules are collected as top-level modules from app/. In a
    # PyInstaller bundle their __file__ paths live directly under _MEIPASS,
    # so the frozen root is the equivalent of the repository root/app pair.
    import server

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(server.__file__).resolve().parent))
    server.APP_ROOT = bundle_root
    server.VERSION_FILE = bundle_root / "VERSION"

    # Install the same feature layers used by the appliance. The installer
    # uses production only, so the production gates/versioning remain active.
    import qr_controls_v110

    qr_controls_v110.install_routes(server.app)

    import windows_runtime

    windows_runtime.install(server.app, server)

    # Direct Theme Builder transforms are Windows-only. Reading the transform
    # state is public so the fullscreen display can apply it; writes remain
    # behind the normal Settings lock.
    import windows_theme_editor_v122

    windows_theme_editor_v122.install(server.app, server.PUBLIC_ENDPOINTS)
    _start_remote_qr_refresh()

    from waitress import serve

    print(f"Starting Stats Windows server {server.software_version()} on port 8765")
    serve(server.app, host="0.0.0.0", port=8765, threads=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
