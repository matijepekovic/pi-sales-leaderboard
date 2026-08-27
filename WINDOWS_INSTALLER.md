# Windows production installer

The Windows build is produced only from the `production` branch. Development/main is not part of the Windows package or installer workflow.

## What the installer contains

- A frozen Python/Flask/Waitress backend (`StatsServer.exe`).
- A small Windows fullscreen launcher (`StatsLauncher.exe`).
- All production templates, static assets, Starter theme assets, and production feature gates.
- The production `VERSION` file.

The customer does **not** need Python, Git, GitHub, a terminal, a GitHub token, or the update-signing private key.

## Installation behavior

The installer is per-user and does not require administrator rights. It installs program files under:

`%LOCALAPPDATA%\Programs\Stats`

By default it creates a current-user Startup shortcut. At Windows sign-in the launcher:

1. starts the packaged backend on port 8765;
2. waits for `/health` to become ready;
3. opens Microsoft Edge in dedicated fullscreen mode (Chrome is the fallback);
4. stays running while the fullscreen window is open;
5. shuts down the backend and exits when the user closes the fullscreen window;
6. only relaunches the fullscreen browser for an explicit in-app Fullscreen request;
7. may restart the backend after a backend crash while the fullscreen app is still open.

Closing the fullscreen window is therefore a real user exit. It does not reopen until the user launches Stats again or Windows starts it at a later sign-in.

A desktop shortcut is optional during setup.

## 1.0.0 rename migration

The 1.0.1 installer keeps the same application identity so an existing installation is recognized. It stops the older running launcher/backend, removes the retired program folder and shortcuts, then installs the current Stats files and shortcuts. Persistent customer data is not part of that program-folder cleanup.

## Persistent data

Installed program files and customer data are deliberately separate. Existing application data remains under the same per-user persistent path used by the appliance:

`~/.local/share/pi-tableau-leaderboard/`

On Windows this resolves inside the signed-in user's profile. This includes the database, Tableau configuration, team assignments, theme library, team logos, and the permanent applied-theme asset store.

Installing a newer Windows build replaces the program directory but does not delete this persistent data. Normal uninstall also leaves customer data in place.

## Windows-specific safety

The old source-tree ZIP updater is disabled inside the packaged Windows build. A frozen executable must not replace itself with raw repository source. The Windows release path uses the signed public installer/update repository instead.

The app's Linux labwc/systemd startup behavior is not used by the Windows launcher.

## CI validation

`.github/workflows/windows-installer.yml` runs on production pull requests and production pushes. It:

1. tests that closing the fullscreen browser exits the launcher instead of relaunching it;
2. packages the backend and launcher with PyInstaller;
3. starts the frozen backend and verifies `/health`, the production version API, and the main display page;
4. compiles the Inno Setup installer;
5. simulates the 1.0.0 program-folder migration and verifies it is removed;
6. silently installs the current build and verifies the Stats executable names and Startup shortcut;
7. starts the installed backend, silently uninstalls Stats, and verifies the running backend is stopped and the program files/Startup shortcut are removed;
8. signs and publishes production release assets only after those checks pass.

No publishing token or signing private key is exposed to pull-request builds.

## Current signing note

The release-manifest Ed25519 system protects published update artifacts. The Windows executable itself is not yet Authenticode-signed, so Windows SmartScreen may display an unknown-publisher warning until a Windows code-signing certificate is added. That is separate from the update-manifest signing key.
