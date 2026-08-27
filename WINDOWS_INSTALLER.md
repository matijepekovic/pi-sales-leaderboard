# Windows production installer

The Windows build is produced only from the `production` branch. Development/main is not part of the Windows package or installer workflow.

## What the installer contains

- A frozen Python/Flask/Waitress backend (`TablouStatsServer.exe`).
- A small Windows watchdog/kiosk launcher (`TablouStatsLauncher.exe`).
- All production templates, static assets, Starter theme assets, and production feature gates.
- The production `VERSION` file.

The customer does **not** need Python, Git, GitHub, a terminal, a GitHub token, or the update-signing private key.

## Installation behavior

The installer is per-user and does not require administrator rights. It installs program files under:

`%LOCALAPPDATA%\Programs\Tablou Stats`

By default it creates a current-user Startup shortcut. At Windows sign-in the launcher:

1. starts the packaged backend on port 8765;
2. waits for `/health` to become ready;
3. opens Microsoft Edge in dedicated fullscreen kiosk mode (Chrome is the fallback);
4. relaunches the browser if it exits;
5. restarts the backend if the app intentionally restarts or crashes;
6. honors the existing `restart-kiosk.request` mechanism used by the Fullscreen control.

A desktop shortcut is optional during setup.

## Persistent data

Installed program files and customer data are deliberately separate. Existing application data remains under the same per-user persistent path used by the appliance:

`~/.local/share/pi-tableau-leaderboard/`

On Windows this resolves inside the signed-in user's profile. This includes the database, Tableau configuration, team assignments, theme library, team logos, and the permanent applied-theme asset store.

Installing a newer Windows build replaces the program directory but does not delete this persistent data. Normal uninstall also leaves customer data in place.

## Windows-specific safety

The old source-tree ZIP updater is disabled inside the packaged Windows build. A frozen executable must not replace itself with raw repository source. The Windows release path will use the signed public installer/update repository instead.

The app's Linux labwc/systemd startup behavior is not used by the Windows launcher.

## CI validation

`.github/workflows/windows-installer.yml` runs on production pull requests and production pushes. It:

1. packages the backend with PyInstaller;
2. packages the kiosk launcher;
3. starts the frozen backend and verifies `/health`, the production version API, and the main display page;
4. compiles an Inno Setup installer;
5. silently installs it on a clean GitHub Windows runner and checks that both executables were installed;
6. uploads the tested installer as a GitHub Actions artifact.

No publishing token or signing private key is exposed to pull-request builds.

## Current signing note

The release-manifest Ed25519 system protects future published update artifacts. The Windows executable itself is not yet Authenticode-signed, so Windows SmartScreen may display an unknown-publisher warning until a Windows code-signing certificate is added. That is separate from the update-manifest signing key.
