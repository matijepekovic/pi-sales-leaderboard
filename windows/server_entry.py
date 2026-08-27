#!/usr/bin/env python3
"""Frozen Windows entrypoint for the Stats backend."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _persistent_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "pi-tableau-leaderboard"


def _install_file_logging() -> None:
    log_dir = _persistent_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / "windows-server.log").open("a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log


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

    from waitress import serve

    print(f"Starting Stats Windows server {server.software_version()} on port 8765")
    serve(server.app, host="0.0.0.0", port=8765, threads=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
