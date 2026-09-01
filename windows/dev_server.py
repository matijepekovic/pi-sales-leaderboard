#!/usr/bin/env python3
"""Windows live-development server for Stats.

This is development tooling only. Application composition remains owned by
stats_core.bootstrap; this module only runs the composed Flask app with a local
file reloader and development-friendly cache settings.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from stats_core.bootstrap import create_app


HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _port() -> int:
    raw = str(os.environ.get("STATS_DEV_PORT") or DEFAULT_PORT).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid STATS_DEV_PORT: {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise SystemExit(f"STATS_DEV_PORT must be between 1 and 65535, got {port}")
    return port


def _watched_files() -> list[str]:
    watched: list[str] = []
    for relative in ("app/templates", "app/static"):
        root = REPO_ROOT / relative
        if not root.exists():
            continue
        watched.extend(str(path) for path in root.rglob("*") if path.is_file())
    return watched


def create_dev_app():
    app = create_app("windows", start_background=False)
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    return app


def main() -> int:
    app = create_dev_app()
    port = _port()

    # Werkzeug creates a supervising process plus the serving child when the
    # reloader is enabled. Start the QR background worker only in the serving
    # child so development reloads do not duplicate application workers.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        app.extensions["stats_runtime"].platform.start_remote_qr_refresh()

    print("Stats live development server")
    print(f"Open http://{HOST}:{port}")
    print("Python, template, CSS, and JavaScript changes are watched locally.")
    print("Press Ctrl+C to stop.")

    app.run(
        host=HOST,
        port=port,
        debug=False,
        use_reloader=True,
        extra_files=_watched_files(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
