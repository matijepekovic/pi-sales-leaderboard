# Phase 0 — Production 1.0.18 recovery baseline

## Goal

Preserve the current working Windows production release so we can always return to it.

Production only. Development/main is out of scope.

## Do not change during Phase 0

- no refactors
- no file renames
- no folder reorganization
- no new features
- no database-structure changes

## Frozen production source

- Production version: `1.0.18`
- Source commit: `111399f998686ad2aba94bae382c7302acc72d3e`
- Frozen baseline ref: `baseline/production-1.0.18`
- Recovery ref: `backup/phase0-production-1.0.18-20260828`
- Stabilization branch: `stabilization/production-1.0.18-phase0`
- Live branch: `production`

`baseline/production-1.0.18` points to the exact production 1.0.18 source commit and must not be used for ongoing work.

## Published Windows baseline

The public update repository contains the current published Windows release `v1.0.18`.

Installer identity:

- File: `Stats-Setup-1.0.18-windows-x64.exe`
- Size: `30220768` bytes
- SHA-256: `c6b37bcf64ef3ab0d2a7f0196f52bb9b0877e75b2329308c4e835bee773fa1f8`

The release also contains:

- `release-manifest.json`
- `release-manifest.json.sig`

These provide the signed production update baseline.

## What is protected by the source baseline

The frozen 1.0.18 source preserves everything that actually ships with the app, including:

- Windows packaging/build configuration
- `StatsServer.exe` source/package inputs
- `StatsLauncher.exe` source/package inputs
- `StatsUpdater.exe` source/package inputs
- Flask templates and static files
- built-in themes and built-in assets
- Starter/default assets
- application defaults
- SQLite schema/default-setting code
- Tableau configuration logic
- production feature gates
- production `VERSION`
- embedded Ed25519 public update-verification key
- release-signing/verification workflow code

## Customer runtime data is not part of the Phase 0 product baseline

Stats keeps customer-created runtime data under:

`%USERPROFILE%\.local\share\pi-tableau-leaderboard\`

That may include a customer's database, saved settings, Tableau credentials/configuration, teams, uploaded themes, uploaded assets and applied-theme assets.

This data is deliberately separate from the installed program and is **not shipped with Stats**. It is therefore not required to define or preserve the production 1.0.18 application baseline.

Phase 0 does not require backing up the current development/test Windows machine's customer data.

## Current Windows installation process

Stats installs per user under:

`%LOCALAPPDATA%\Programs\Stats`

The installer contains the packaged production application and does not require Python, Git, GitHub credentials or administrator rights.

The package includes:

- `StatsServer.exe`
- `StatsLauncher.exe`
- `StatsUpdater.exe`
- production templates/static assets
- production `VERSION`
- embedded Ed25519 public update-verification key

At Windows sign-in, the Startup shortcut launches Stats. The launcher starts the packaged backend on port 8765, waits for `/health`, then opens the fullscreen browser.

## Current Windows update process

Updates are user-triggered from Software using **Check for Updates** / **Update**.

1. Stats downloads `release-manifest.json` and `release-manifest.json.sig` from the public release repository.
2. The manifest is verified with the embedded Ed25519 public key.
3. The signed manifest supplies the exact production version, installer filename, byte size and SHA-256.
4. Stats downloads the installer.
5. Stats verifies its signed size and SHA-256 immediately before installation.
6. `StatsUpdater.exe` runs outside the replaceable program directory.
7. The verified Inno Setup installer replaces the installed program files.
8. The updater relaunches `StatsLauncher.exe`.

The packaged Windows application does not use the legacy source-tree ZIP updater.

## Recovery procedure

If future stabilization work fails completely:

1. Reset/recover the source from `baseline/production-1.0.18` or commit `111399f998686ad2aba94bae382c7302acc72d3e`.
2. Use the published `Stats-Setup-1.0.18-windows-x64.exe` installer.
3. Confirm its SHA-256 is exactly:
   `c6b37bcf64ef3ab0d2a7f0196f52bb9b0877e75b2329308c4e835bee773fa1f8`
4. Install Stats 1.0.18 normally.
5. Confirm the packaged application launches and reports production version 1.0.18.

Customer/runtime data restoration is a separate concern and is not required to recover the application itself.

## Phase 0 exit criteria

Phase 0 passes when:

- the exact 1.0.18 production source is pinned and recoverable;
- a dedicated stabilization branch exists from that baseline;
- the published 1.0.18 Windows installer remains available;
- the exact installer filename, size and SHA-256 are recorded;
- the signed release manifest/signature are preserved in the published release;
- the Windows installation process is documented;
- the Windows update process is documented;
- rebuilding/reinstalling 1.0.18 does not depend on development/main;
- no Phase 0 work changed app behavior, file organization or database structures.
