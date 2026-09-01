# Stats Live Development

This branch is for building and testing Stats directly from source on Windows.
It does not require building or installing a new Stats installer for every change.

## Safety rules

- Work on `live-dev`.
- `live-dev` was created from `production`.
- Do not use or modify `main` for this workflow.
- Close the installed Stats application before starting live development. The live server intentionally uses the normal local Stats data and port so you are testing the real application behavior.
- Publishing and installer work remain separate and happen only after the live build is ready.

## First-time setup

1. Install GitHub Desktop if it is not already installed.
2. In GitHub Desktop, clone `matijepekovic/pi-sales-leaderboard`.
3. Switch the repository branch to `live-dev`.
4. Install Python 3 if Windows does not already have the `py` launcher.
5. In File Explorer, open the cloned repository.
6. Double-click `windows\live-dev.bat`.
7. When the window says the server is running, open `http://127.0.0.1:8765` in the browser.

The first launch creates a local `.venv` and installs the Python dependencies from `requirements.txt`. The `.venv` is ignored by Git.

## Normal editing loop

1. Keep `windows\live-dev.bat` running.
2. Ask for a Stats change.
3. The change is committed to `live-dev` on GitHub.
4. In GitHub Desktop, click **Fetch origin** and then **Pull origin** when a change is available.
5. Python changes restart the local server automatically.
6. Refresh the browser to see template, CSS, or JavaScript changes.
7. Test the change immediately and continue iterating.

No installer, release, or production version bump is required during this loop.

## Architecture

`windows/dev_server.py` is development tooling only. It owns local serving/reload behavior and delegates all application construction to `app/stats_core/bootstrap.py`, which remains the single composition root.

The live server uses the normal Stats persistent data location by default, so existing local settings, teams, themes, and source configuration remain available. `STATS_DATA_DIR` continues to be the existing explicit override boundary if isolated development data is ever needed.

The development server binds only to `127.0.0.1`, so it is accessible from the local Windows machine rather than being exposed to the network.
