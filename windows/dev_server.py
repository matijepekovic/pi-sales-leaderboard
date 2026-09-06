#!/usr/bin/env python3
"""Windows live-development server for Stats.

This is development tooling only. Application composition remains owned by
stats_core.bootstrap; this module only synchronizes the live-dev working tree
and runs the composed Flask app with local file reloading.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from stats_core.bootstrap import create_app


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
LIVE_BRANCH = "live-dev"
SYNC_INTERVAL_SECONDS = 10
BROWSER_RELOAD_INTERVAL_MS = 750
LIVE_RELOAD_SUFFIXES = {".css", ".html", ".js", ".mjs"}


def _port() -> int:
    raw = str(os.environ.get("STATS_DEV_PORT") or DEFAULT_PORT).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid STATS_DEV_PORT: {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise SystemExit(f"STATS_DEV_PORT must be between 1 and 65535, got {port}")
    return port


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _sync_once() -> bool:
    """Fast-forward live-dev from origin without touching local code changes."""
    try:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if branch != LIVE_BRANCH:
            print(f"Auto-sync paused: current branch is {branch!r}, not {LIVE_BRANCH!r}.")
            return False

        dirty = _git("status", "--porcelain", "--untracked-files=no").stdout.strip()
        if dirty:
            print("Auto-sync paused: local tracked changes are present.")
            return False

        _git("fetch", "--quiet", "origin", LIVE_BRANCH)
        local = _git("rev-parse", "HEAD").stdout.strip()
        remote = _git("rev-parse", f"origin/{LIVE_BRANCH}").stdout.strip()
        if local == remote:
            return False

        ancestor = _git(
            "merge-base", "--is-ancestor", local, remote, check=False
        ).returncode == 0
        if not ancestor:
            print("Auto-sync paused: local live-dev is ahead of or diverged from GitHub.")
            return False

        _git("merge", "--ff-only", f"origin/{LIVE_BRANCH}")
        print("\nAuto-synced latest live-dev changes from GitHub.")
        return True
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        print(f"Auto-sync retrying later: {exc}")
        return False


def _auto_sync_worker() -> None:
    while True:
        time.sleep(SYNC_INTERVAL_SECONDS)
        _sync_once()


def _start_auto_sync() -> None:
    threading.Thread(
        target=_auto_sync_worker,
        name="stats-live-dev-sync",
        daemon=True,
    ).start()


def _watched_files() -> list[str]:
    """Return authored frontend files only, never runtime/generated assets."""
    watched: list[str] = []
    for relative in ("app/templates", "app/static"):
        root = REPO_ROOT / relative
        if not root.exists():
            continue
        watched.extend(
            str(path)
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in LIVE_RELOAD_SUFFIXES
        )
    return watched


def _install_browser_reload(app) -> None:
    """Reload open HTML pages after the development server restarts."""
    revision = str(time.time_ns())
    script = f"""<script id="stats-live-reload">
(() => {{
  const loadedRevision = {revision!r};
  window.setInterval(() => {{
    fetch("/__stats_live_revision", {{cache: "no-store"}})
      .then(response => response.ok ? response.text() : "")
      .then(currentRevision => {{
        if (currentRevision && currentRevision !== loadedRevision) window.location.reload();
      }})
      .catch(() => {{}});
  }}, {BROWSER_RELOAD_INTERVAL_MS});
}})();
</script>"""

    @app.get("/__stats_live_revision")
    def stats_live_revision():
        return revision, 200, {"Cache-Control": "no-store"}

    @app.after_request
    def inject_stats_live_reload(response):
        content_type = str(response.content_type or "").lower()
        if response.status_code != 200 or response.direct_passthrough or "text/html" not in content_type:
            return response
        body = response.get_data(as_text=True)
        marker = body.lower().rfind("</body>")
        if marker < 0 or 'id="stats-live-reload"' in body:
            return response
        response.set_data(body[:marker] + script + body[marker:])
        response.headers["Cache-Control"] = "no-store"
        return response


def create_dev_app():
    app = create_app("windows", start_background=False)
    app.config.update(
        TEMPLATES_AUTO_RELOAD=True,
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    _install_browser_reload(app)
    return app


def main() -> int:
    reloader_child = os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    # The reloader supervisor owns Git synchronization. The serving child only
    # runs Stats, preventing duplicate fetch/pull loops after every reload.
    if not reloader_child:
        _sync_once()
        _start_auto_sync()

    app = create_dev_app()
    port = _port()

    if reloader_child:
        app.extensions["stats_runtime"].platform.start_remote_qr_refresh()
        app.extensions["stats_runtime"].report_updates.start()

    print("Stats live development server")
    print(f"Open http://{HOST}:{port}")
    print(f"GitHub {LIVE_BRANCH} auto-sync: every {SYNC_INTERVAL_SECONDS} seconds")
    print("Python, template, CSS, and JavaScript changes refresh the browser automatically.")
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
