#!/usr/bin/env python3
"""Frozen Windows process entrypoint for Stats.

All application composition lives in stats_core.bootstrap. This file owns only
process logging and serving the already-composed Flask application.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _persistent_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "pi-tableau-leaderboard"


def _install_file_logging() -> None:
    log_dir = _persistent_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / "windows-server.log").open(
        "a", encoding="utf-8", buffering=1
    )
    sys.stdout = log
    sys.stderr = log


def main() -> int:
    _install_file_logging()

    from stats_core.bootstrap import create_app
    from waitress import serve

    app = create_app("windows")
    runtime = app.extensions["stats_runtime"]
    print(
        f"Starting Stats Windows server {runtime.version.current()} on port 8765"
    )
    serve(app, host="0.0.0.0", port=8765, threads=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
