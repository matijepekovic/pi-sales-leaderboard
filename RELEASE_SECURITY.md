# Production release security

Production releases are designed so customer machines never need GitHub credentials or a private signing key.

## Repositories

- Private/development source (eventually): `matijepekovic/pi-sales-leaderboard`
- Public release distribution: `matijepekovic/pi-sales-leaderboard-updates`
- Production source branch: `production`
- Development/Pi branch: `main`

## GitHub Actions secrets

The source repository stores these encrypted Actions secrets:

- `UPDATE_PUBLISH_TOKEN` — fine-grained token restricted to publishing release assets to `pi-sales-leaderboard-updates`.
- `UPDATE_SIGNING_PRIVATE_KEY` — Ed25519 private signing key. It must never be committed, logged, uploaded as an artifact, or shipped to a customer machine.

## Public verification key

The matching Ed25519 public key is compiled/distributed with the production app. It is safe to publish and is stored in `app/update_signing_public_key.py`.

## Release format

A release contains one or more prebuilt installer/update assets plus:

- `release-manifest.json`
- `release-manifest.json.sig`

The manifest records the production semantic version, filename, byte size, and SHA-256 hash of every release asset. The exact manifest bytes are signed with the private Ed25519 key.

`scripts/sign_release_manifest.py` creates the manifest and signature. `scripts/verify_release_manifest.py` verifies the signature and then verifies every local asset against the signed size and SHA-256 values.

## Customer update flow

1. The app checks the public update repository for the newest production release.
2. It downloads the signed manifest and signature.
3. It verifies the manifest with the built-in public key.
4. It downloads the correct platform asset.
5. It verifies that asset's size and SHA-256 hash against the signed manifest.
6. Only a fully verified asset may be installed.

Customer machines receive no GitHub token and no private signing key. No per-machine signing setup is required.

## Current boundary

This change establishes the signing foundation only. It does not publish a release and does not change `main` or the user's existing Pi updater. The current production updater remains an interim branch-pinned mechanism until the Windows/Linux installers and public-release updater are connected to this format.
