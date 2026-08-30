# Stats

Stats is a Windows fullscreen sales leaderboard backed by Tableau data and a persistent local SQLite database.

The `production` branch is the Windows product. It builds a tested installer containing the backend, fullscreen launcher, update helper, templates, static assets, and production version metadata.

## Runtime

There is one application composition path:

```text
windows/server_entry.py
        ↓
stats_core.bootstrap.create_app("windows")
        ↓
repositories + services + screens + web blueprints
        ↓
Waitress on port 8765
        ↓
StatsLauncher.exe → fullscreen Edge/Chrome
```

`app/stats_core/bootstrap.py` is the composition root. Feature modules do not install or monkey-patch one another at startup.

The packaged Windows runtime is built from `windows/server_entry.py`; there is no separate Pi/Linux runtime in production.

## Source layout

- `app/stats_core/` — application domains, repositories, services, screens, HTTP routes, themes, and Windows platform integration.
- `app/sources/` — Tableau connection, discovery, parsing, mapped exports, Crosstab handling, and Product Close source logic.
- `app/templates/` — display and settings manifests/markup.
- `app/static/display/` — TV/display JavaScript.
- `app/static/settings/` — settings JavaScript.
- `app/static/runtime/` — shared browser runtime helpers.
- `windows/server_entry.py` — packaged backend entrypoint.
- `windows/launcher.py` — fullscreen Windows launcher.
- `windows/updater.py` — detached signed-installer update helper.
- `windows/Stats.iss` — Inno Setup definition.

See `ARCHITECTURE.md` for ownership details.

## Data ownership

Tableau supplies sales data. Local application state owns the things that should survive source refreshes, including:

- teams and team assignments;
- settings and display configuration;
- Product Close rows;
- theme configuration;
- reusable theme assets;
- currently applied theme assets;
- Tableau credentials/configuration.

Customer data is stored outside the installed program directory. Installing or updating Stats replaces application files without deleting persistent customer data.

## Main display modes

Stats currently has five registered display modes:

1. Whole Office
2. Per Team
3. Team vs Team
4. All Teams
5. Product Close Rates

Shared leaderboard calculations live in `LeaderboardService`; each registered screen owns its mode-specific payload.

## Tableau

The Tableau source layer supports saved connection configuration, workbook/view discovery, candidate pulls, column/mapping discovery, report filters, scheduled/manual rep refreshes, and Product Close refreshes.

Rep refreshes preserve locally owned organization data rather than allowing Tableau metrics to overwrite team assignments.

## Themes

Theme configuration, the reusable asset library, and applied assets have separate persistence ownership. Applied artwork is copied into persistent storage so a software update or removal from the built-in library does not break a currently applied theme.

## Windows installation and updates

The Windows installer is built and validated by `.github/workflows/windows-installer.yml`.

A production pull request must pass runtime, auth, path/storage, launcher, signed-update, packaged-backend, installer compile, and install/uninstall checks before it is merged.

Published in-app updates are verified against an Ed25519-signed release manifest before the installer is launched.

See `WINDOWS_INSTALLER.md` and `RELEASE_SECURITY.md` for the installation/update design.

## Local development

On Windows, install dependencies and run the same server entrypoint used by the packaged backend:

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH="app"
python windows/server_entry.py
```

Then open:

- `http://127.0.0.1:8765/` — leaderboard
- `http://127.0.0.1:8765/settings` — settings
- `http://127.0.0.1:8765/health` — health check

## Verification

The focused Windows checks live under `windows/`. The production installer workflow runs them before packaging and then verifies the frozen application and installer itself.

The architecture smoke test is:

```powershell
python windows/test_restructured_runtime.py
```

The production goal is simple: one obvious runtime, one canonical implementation per feature, persistent customer data, and no legacy patch stack hidden underneath the current code.
