# Phase 0 — Production 1.0.18 recovery baseline

This document freezes the current Windows production state before any stabilization or future production work.

## Scope

Production only. Do not merge development/main into this baseline.

No refactors, renames, folder reorganization, features, or database schema changes are part of Phase 0.

## Frozen source baseline

- Production version: `1.0.18`
- Source commit: `111399f998686ad2aba94bae382c7302acc72d3e`
- Frozen baseline branch: `baseline/production-1.0.18`
- Phase 0 recovery branch: `backup/phase0-production-1.0.18-20260828`
- Stabilization branch: `stabilization/production-1.0.18-phase0`
- Live production branch remains: `production`

The public release repository contains the published Windows release `v1.0.18` and is the reinstall source for the current Windows installer.

Published installer identity:

- File: `Stats-Setup-1.0.18-windows-x64.exe`
- Size: `30220768` bytes
- SHA-256: `c6b37bcf64ef3ab0d2a7f0196f52bb9b0877e75b2329308c4e835bee773fa1f8`

## Current Windows installation

Stats is installed per user under:

`%LOCALAPPDATA%\Programs\Stats`

The package contains:

- `StatsServer.exe`
- `StatsLauncher.exe`
- `StatsUpdater.exe`
- production templates/static assets
- production `VERSION`
- the embedded Ed25519 public update-verification key

The installer does not require Python, Git, GitHub credentials, or administrator rights.

At sign-in, the Startup shortcut launches Stats. The launcher starts the packaged server on port 8765, waits for `/health`, then opens the fullscreen browser.

## Current Windows update process

Updates are user-triggered from Software using Check for Updates / Update.

1. Stats downloads `release-manifest.json` and `release-manifest.json.sig` from the public update release.
2. The manifest is verified with the embedded Ed25519 public key.
3. The manifest supplies the exact version, installer filename, byte size, and SHA-256.
4. The installer is downloaded into the persistent data directory under `updates/windows/<version>/`.
5. Stats verifies the installer size and SHA-256 again immediately before launch.
6. `StatsUpdater.exe` is copied outside the replaceable program directory and starts the verified Inno Setup installer.
7. The installer replaces the program files under `%LOCALAPPDATA%\Programs\Stats`.
8. The updater relaunches `StatsLauncher.exe`.

The legacy source-tree updater is disabled in the packaged Windows build.

## Persistent customer data

All customer-owned runtime data is deliberately outside the Windows program directory under:

`%USERPROFILE%\.local\share\pi-tableau-leaderboard\`

The entire directory must be backed up as one unit. This protects more safely than selecting individual files.

Known contents include:

- `leaderboard.db` — SQLite database
  - settings
  - Tableau server/site/PAT configuration
  - selected Tableau source/mapping
  - teams and assignments
  - theme configuration
  - other persisted application state
- `themes\` — persistent/custom theme files
- `asset-library\` — user-uploaded/recolored reusable assets
- `applied-theme-assets\` — permanent copies of assets currently applied to themes
- team logos and other customer-owned persistent files referenced by the database
- `updates\windows\` — downloaded verified Windows update installers/helpers when present

Because `leaderboard.db` includes the stored Tableau PAT secret, a backup of this directory is sensitive and must be kept private.

## Phase 0 backup procedure on the current Windows machine

Close Stats completely before copying the data directory so SQLite and asset files are captured consistently.

PowerShell:

```powershell
$Source = Join-Path $HOME ".local\share\pi-tableau-leaderboard"
$Backup = Join-Path $HOME "Desktop\Stats-Phase0-1.0.18-data"

if (-not (Test-Path -LiteralPath $Source)) {
    throw "Stats persistent data directory was not found: $Source"
}

if (Test-Path -LiteralPath $Backup) {
    throw "Backup destination already exists: $Backup"
}

Copy-Item -LiteralPath $Source -Destination $Backup -Recurse

Get-ChildItem -LiteralPath $Backup -Recurse -File |
    Get-FileHash -Algorithm SHA256 |
    Sort-Object Path |
    Format-Table -AutoSize
```

Do not delete or move the original persistent data directory after making the copy.

For strongest recovery protection, keep a second copy of `Stats-Phase0-1.0.18-data` on storage separate from the Windows PC.

## Restore procedure

If future production work fails completely:

1. Obtain the published `Stats-Setup-1.0.18-windows-x64.exe` installer.
2. Verify its SHA-256 is exactly:
   `c6b37bcf64ef3ab0d2a7f0196f52bb9b0877e75b2329308c4e835bee773fa1f8`
3. Install Stats 1.0.18.
4. Close Stats completely.
5. Preserve or rename any newly created `%USERPROFILE%\.local\share\pi-tableau-leaderboard\` directory.
6. Restore the complete Phase 0 backup directory to `%USERPROFILE%\.local\share\pi-tableau-leaderboard\`.
7. Launch Stats.
8. Confirm:
   - saved teams/assignments are present;
   - themes render correctly;
   - applied assets and uploaded library assets are present;
   - settings are retained;
   - Tableau configuration/source selection is retained;
   - the leaderboard loads normally.

## Phase 0 exit check

Phase 0 is complete only when all of the following are true:

- the 1.0.18 source commit remains preserved by immutable/pinned recovery references;
- the 1.0.18 installer is still recoverable and its hash is recorded;
- a copy of the current Windows persistent data directory exists outside the live data location;
- that backup contains the database, themes, applied assets, uploaded assets, settings, and Tableau configuration;
- a reinstall of 1.0.18 plus restoration of that full data directory is sufficient to return to the current production state.
