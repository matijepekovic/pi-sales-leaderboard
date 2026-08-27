# Windows production installer

The Windows build is produced only from the `production` branch. Development/main is not part of the Windows package or installer workflow.

## What the installer contains

- A frozen Python/Flask/Waitress backend (`StatsServer.exe`).
- A Windows fullscreen launcher (`StatsLauncher.exe`).
- A detached update helper (`StatsUpdater.exe`).
- All production templates, static assets, Starter theme assets, production feature gates, and the public Ed25519 update-verification key.
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
6. only relaunches the fullscreen browser for an explicit in-app Fullscreen request.

Closing the fullscreen window is a real user exit. It does not reopen until the user launches Stats again or Windows starts it at a later sign-in.

A desktop shortcut is optional during setup.

## Signed in-app Windows updates

The Software card remains user-controlled with **Check for Updates** and **Update**. After the user presses Update, the rest of the process is automatic:

1. Stats reads the latest public release from `matijepekovic/pi-sales-leaderboard-updates` without credentials.
2. It downloads `release-manifest.json` and `release-manifest.json.sig`.
3. It verifies the exact manifest bytes with the embedded Ed25519 public key.
4. It requires the release tag, signed manifest version, Windows installer filename, size, and SHA-256 to agree.
5. It downloads the installer to the persistent updates directory and verifies its signed size and SHA-256 again immediately before launch.
6. It copies and starts `StatsUpdater.exe` outside the replaceable program directory.
7. The helper lets the API response return, silently runs the verified Inno Setup installer, then relaunches the new `StatsLauncher.exe`.

No reusable secret is shipped to the customer. A malicious or corrupted installer from the public release location is rejected unless it matches the Ed25519-signed manifest.

The legacy source-tree ZIP updater remains disabled in the packaged Windows build.

## Persistent data

Installed program files and customer data are deliberately separate. Existing application data remains under the same per-user persistent path used by the appliance:

`~/.local/share/pi-tableau-leaderboard/`

On Windows this resolves inside the signed-in user's profile. This includes the database, Tableau configuration, team assignments, theme library, team logos, and the permanent applied-theme asset store.

Installing a newer Windows build replaces the program directory but does not delete this persistent data. Normal uninstall also leaves customer data in place.

## CI validation

`.github/workflows/windows-installer.yml` runs on production pull requests and production pushes. It:

1. rejects the retired product name anywhere in tracked production files;
2. tests that closing the fullscreen browser exits the launcher instead of relaunching it;
3. unit-tests Ed25519 manifest verification and trusted release URL handling;
4. packages the backend, launcher, and detached updater helper with PyInstaller;
5. starts the frozen backend and verifies `/health`, the production version API, the main display page, and the currently published signed update feed;
6. compiles the Inno Setup installer;
7. silently installs the current build and verifies all three Stats executables and the Startup shortcut;
8. starts the installed backend, silently uninstalls Stats, and verifies the running backend is stopped and the program files/Startup shortcut are removed;
9. signs and publishes production release assets only after those checks pass.

No publishing token or signing private key is exposed to pull-request builds.

## Current signing note

The release-manifest Ed25519 system protects published update artifacts. The Windows executable itself is not yet Authenticode-signed, so Windows SmartScreen may display an unknown-publisher warning until a Windows code-signing certificate is added. That is separate from the update-manifest signing key.
