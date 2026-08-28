# Stats — Fixed Project Phases

This file is the source of truth for the order of work on Stats.

## Rules

1. Phases are completed in order.
2. Do not begin the next phase until the current phase passes its exit criteria and is marked confirmed here.
3. Do not mix bug fixing, refactoring, new feature work, paywall work, or platform work across phases.
4. Windows is the only actively tested/reference platform until the Windows product is complete.
5. Core application code must remain platform-neutral so Linux, macOS, and web can be added later.
6. Refactoring must preserve behavior. A refactor is not an opportunity to add features or redesign the product.
7. Never use a paywall to hide a broken feature. All features must work unlocked before they are locked into plans.
8. Do not move or delete the Phase 0 baseline/recovery refs.

---

# Phase 0 — Protect the current production version

**Status: ✅ COMPLETE — CONFIRMED 2026-08-28**

## Goal

Keep a recoverable copy of the current Windows production application so future work cannot destroy the last known production version.

## Confirmed evidence

- [x] Production 1.0.18 source is pinned at commit `111399f998686ad2aba94bae382c7302acc72d3e`.
- [x] Frozen baseline ref exists: `baseline/production-1.0.18`.
- [x] Recovery ref exists: `backup/phase0-production-1.0.18-20260828`.
- [x] Dedicated stabilization branch exists: `stabilization/production-1.0.18-phase0`.
- [x] Published Windows release `v1.0.18` exists in `pi-sales-leaderboard-updates`.
- [x] Installer exists: `Stats-Setup-1.0.18-windows-x64.exe`.
- [x] Installer size is recorded: `30220768` bytes.
- [x] Installer SHA-256 is recorded: `c6b37bcf64ef3ab0d2a7f0196f52bb9b0877e75b2329308c4e835bee773fa1f8`.
- [x] Signed `release-manifest.json` and `release-manifest.json.sig` are published with the release.
- [x] Windows installation process is documented.
- [x] Windows update process is documented.
- [x] Recovery procedure is documented.
- [x] Recovery does not depend on `main`.
- [x] Customer/test-machine runtime data is intentionally outside the shipped product baseline and is not required for Phase 0 recovery.

## Exit criteria

- [x] We can return to and reinstall the preserved Production 1.0.18 application if future work fails.

---

# Phase 1 — Unlock every existing feature for testing

**Status: ✅ COMPLETE — CONFIRMED 2026-08-28**

## Goal

Make every feature that already exists in the code accessible on the Windows test build while preserving the ability to lock features again later.

## Work

- [x] Inventory every current feature restriction and `Coming eventually` gate.
- [x] Make Whole Office accessible.
- [x] Make Per Team accessible.
- [x] Make Team vs Team accessible.
- [x] Make All Teams accessible.
- [x] Make Product Close Rates accessible.
- [x] Make Temporary Date functionality accessible.
- [x] Make every existing Theme/Theme Editor capability accessible.
- [x] Make every existing control/settings capability accessible.
- [x] Remove the `Coming eventually` testing restriction/UX where it blocks existing features.
- [x] Preserve a central mechanism that can later allow/deny individual features.
- [x] Do not add new product functionality during this phase.

## Confirmed evidence

- [x] Production restrictions are centralized in `app/production_gates.py` and the matching production settings guard.
- [x] A central `FEATURE_ACCESS` policy and `can_use(feature)` interface now allow all existing Phase 1 features while preserving later per-feature restriction capability.
- [x] The production UI reads the central feature-access policy instead of hard-coding Whole Office / `Coming eventually` restrictions.
- [x] The Settings startup-loop safety guard remains intact after the unlock change.
- [x] Windows launcher regression tests passed: 14/14.
- [x] Windows signed-update tests passed: 3/3.
- [x] Packaged Windows backend, fullscreen launcher, and updater built successfully.
- [x] Packaged backend health/display/signed-update-feed smoke test passed.
- [x] Windows installer compiled successfully.
- [x] Silent Windows install/uninstall verification passed.
- [x] Release manifest signing and verification passed.
- [x] No new public `v1.0.18` release was published; the immutable-release guard correctly rejected replacing the preserved Phase 0 release with different assets.
- [x] Phase 1 implementation head before checklist confirmation: `2c6129fd2c9baec80b1d4fbdcf2d0c875d009134`.

## Exit criteria

- [x] Every feature already present in the codebase can be opened and tested on Windows.
- [x] Individual features can still be restricted later without deleting/rebuilding the feature.
- [x] Phase 1 confirmed.

---

# Phase 2 — Test and fix all existing functionality

**Status: ⬜ NOT STARTED**

## Goal

Make the current feature set function correctly before any architecture refactor begins.

## Test/fix areas

- [ ] Windows startup, shutdown, restart, reboot, and recovery.
- [ ] Tableau authentication and connection.
- [ ] Tableau workbook/view/column discovery.
- [ ] Tableau mapping, filters, dates, manual refresh, and failed-refresh behavior.
- [ ] Rep data, calculations, rankings, sorting, missing/new/duplicate reps, and persistence.
- [ ] Team Builder: create, edit, rename, delete, leaders, assignments, logos, unassigned reps.
- [ ] Verify Tableau refresh cannot destroy local team organization.
- [ ] Whole Office display.
- [ ] Per Team display.
- [ ] Team vs Team display.
- [ ] All Teams display.
- [ ] Product Close Rates display.
- [ ] Number/currency/percentage formatting and totals.
- [ ] Physical/keyboard/mouse control actions and repeated-fast-input stability.
- [ ] Themes, Starter theme, custom themes, per-team themes, colors, backgrounds, rows, champion, corners, totals, and transforms.
- [ ] Applied asset persistence across restart/update/reinstall and removal of the original library/default asset.
- [ ] Theme Editor upload/select/position/scale/stretch/rotate/opacity/save/reset/reopen behavior.
- [ ] Product Close Rates source, market, dates, refresh, storage, icons, rotation, missing/failure states.
- [ ] Temporary Date start/end, activation, cancellation, regular/product data, preview interaction, and restart behavior.
- [ ] Scheduler timing, duplicate prevention, failure behavior, database update, and display refresh.
- [ ] Every Settings control; changing one setting must not corrupt unrelated settings.
- [ ] Windows updater: check, download, signature/hash verification, install, file-lock retry, failed-update recovery, relaunch, and status.

## Rules

During Phase 2, issues are classified as:

- blocker — fix now;
- functional bug — fix now;
- cosmetic issue — record for later;
- feature enhancement — record for later;
- architecture issue — record for Phase 4.

No architecture cleanup or new features during Phase 2.

## Exit criteria

- [ ] No known blockers in the existing feature set.
- [ ] No known functional bugs in the existing feature set that prevent the intended behavior.
- [ ] All critical asset/data/update recovery checks pass.
- [ ] Phase 2 confirmed.

---

# Phase 3 — Freeze the known-good pre-refactor Windows baseline

**Status: ⬜ NOT STARTED**

## Goal

Create the exact working reference version against which the refactor will be compared.

## Work

- [ ] Pin the known-good source commit.
- [ ] Create baseline/recovery refs for this version.
- [ ] Preserve a working Windows installer/build.
- [ ] Record version, commit, installer identity, size, and hash.
- [ ] Capture representative API outputs.
- [ ] Capture representative leaderboard/product results.
- [ ] Capture representative settings/database state.
- [ ] Capture representative theme/display output.
- [ ] Add automated contract/regression tests where practical.

## Exit criteria

- [ ] A known-good Windows build can be installed and reproduced.
- [ ] We have comparison evidence for detecting refactor regressions.
- [ ] Phase 3 confirmed.

---

# Phase 4 — Refactor the architecture without changing behavior

**Status: ⬜ NOT STARTED**

## Goal

Separate the current application into clear modules so one area can be worked on without breaking unrelated areas.

**No new features. No intentional UI changes. No database redesign unless absolutely unavoidable.**

## 4.1 Storage interfaces

- [ ] Add `RepRepository`.
- [ ] Add `OrganizationRepository`.
- [ ] Add `SettingsRepository`.
- [ ] Add `ProductRepository`.
- [ ] Add `ThemeRepository`.
- [ ] Add `AssetRepository` / applied-asset storage interface.
- [ ] Keep the current database/files and behavior initially.

## 4.2 Leaderboard service

- [ ] Extract leaderboard calculations/business logic from `server.py` into `LeaderboardService`.
- [ ] Preserve exact existing outputs.

## 4.3 Organization service

- [ ] Extract teams, leaders, assignments, team lifecycle, and organization rules into `OrganizationService`.

## 4.4 Rep refresh service

- [ ] Create one `RepRefreshService`.
- [ ] Make manual refresh call it.
- [ ] Make scheduled refresh call it.

## 4.5 Pull policy

- [ ] Convert pull policy into an explicit normalization/policy step.
- [ ] Remove runtime monkey-patching used to enforce pull policy.

## 4.6 Scheduler

- [ ] Reduce scheduler responsibility to scheduling refresh services only.
- [ ] Remove QR/theme/control/feature installation from scheduler startup.

## 4.7 Data snapshot provider

- [ ] Add an explicit data snapshot provider for mapping preview, temporary data, and stored data.
- [ ] Remove preview/source monkey-patching.

## 4.8 Screen registry

- [ ] Add a central screen registry/interface.
- [ ] Register Whole Office.
- [ ] Register Per Team.
- [ ] Register Team vs Team.
- [ ] Register All Teams.
- [ ] Register Product Close Rates.

## 4.9 Product service

- [ ] Separate Product Source.
- [ ] Separate Product Repository.
- [ ] Separate Product Refresh Service.
- [ ] Separate Product Screen.
- [ ] Remove Product monkey-patches against server/scheduler/controls.

## 4.10 Theme service

- [ ] Separate Theme Service.
- [ ] Separate Theme Repository.
- [ ] Separate Asset Library.
- [ ] Separate Applied Asset Store.
- [ ] Remove scheduler dependency from theme handling.

## 4.11 Applied asset protection

- [ ] Make persistent materialization/hash verification part of the normal Theme/Asset API.
- [ ] Remove monkey-patching of theme save internals.
- [ ] Preserve all existing applied assets exactly.

## 4.12 Controls

- [ ] Add `ControlsService` / `ScreenController`.
- [ ] Controls emit actions instead of modifying screen implementations directly.

## 4.13 Authentication

- [ ] Move PIN/security behavior out of the central server module into a defined auth component.

## 4.14 Feature entitlement interface

- [ ] Add one central `can_use(feature)`-style interface.
- [ ] Keep the development/test entitlement set to all features allowed.
- [ ] Do not add payment/account logic yet.

## 4.15 Windows platform layer

- [ ] Isolate Windows launching/fullscreen/filesystem/updater/OS-specific operations behind a Windows platform layer.
- [ ] Keep core application/business logic platform-neutral.

## 4.16 Display frontend cleanup

- [ ] Consolidate the versioned display JS patch stack gradually.
- [ ] Establish clear Display, Theme, Layout, Formatting, Controls, and Product runtimes.
- [ ] Remove one legacy patch at a time only after replacement behavior is verified.

## 4.17 Settings frontend cleanup

- [ ] Separate settings UI code by feature/module.
- [ ] Prevent one settings feature from rewriting another feature's behavior.

## 4.18 Remove obsolete runtime patch architecture

- [ ] Remove obsolete replacement/monkey-patching of server payload functions.
- [ ] Remove obsolete replacement/monkey-patching of source preview behavior.
- [ ] Remove obsolete replacement/monkey-patching of scheduler functions.
- [ ] Remove obsolete replacement/monkey-patching of theme internals.
- [ ] Remove obsolete external mutation of control/screen lists.
- [ ] Replace accidental composition through QR controls with an explicit app bootstrap/composition root.

## Exit criteria

- [ ] Major app functions have defined ownership and interfaces.
- [ ] Features no longer modify unrelated feature internals at runtime.
- [ ] Core behavior matches the Phase 3 baseline.
- [ ] Phase 4 confirmed.

---

# Phase 5 — Full post-refactor verification

**Status: ⬜ NOT STARTED**

## Goal

Prove the refactored application still behaves like the known-good Phase 3 application.

## Work

- [ ] Repeat the full Phase 2 test checklist.
- [ ] Compare API results against Phase 3 contracts.
- [ ] Compare leaderboard/product calculations against Phase 3.
- [ ] Compare team organization behavior against Phase 3.
- [ ] Compare theme/assets against Phase 3.
- [ ] Compare controls against Phase 3.
- [ ] Compare updater/runtime behavior against Phase 3.

## Exit criteria

- [ ] No refactor regression remains unresolved.
- [ ] All Phase 3 expected behavior is preserved unless an explicitly documented correction was required.
- [ ] Phase 5 confirmed.

---

# Phase 6 — Add and finish all planned product features

**Status: ⬜ NOT STARTED**

## Goal

Build/finish the product feature set on top of the clean architecture.

## Work

- [ ] Finish any incomplete existing feature.
- [ ] Add approved new leaderboard screens/features.
- [ ] Add approved Theme Editor improvements.
- [ ] Add approved data/Tableau improvements.
- [ ] Add approved Product Close improvements.
- [ ] Add approved control/scheduling/settings features.
- [ ] Give each new feature a stable entitlement key from the start.
- [ ] Keep features unlocked for development/testing.

## Exit criteria

- [ ] The planned feature set is complete.
- [ ] All features can be tested while unlocked.
- [ ] Phase 6 confirmed.

---

# Phase 7 — Stabilize the complete unlocked product

**Status: ⬜ NOT STARTED**

## Goal

Prove the complete product works before any commercial restrictions are enabled.

## Work

- [ ] Full regression test of every feature.
- [ ] Test combinations/interactions between features.
- [ ] Test clean install and upgrades.
- [ ] Test failure/recovery cases.
- [ ] Test data/assets/settings persistence.
- [ ] Test performance and long-running stability.

## Exit criteria

- [ ] All features are built.
- [ ] All features are unlocked.
- [ ] All features are working.
- [ ] Phase 7 confirmed.

---

# Phase 8 — Build the permanent entitlement/paywall system

**Status: ⬜ NOT STARTED**

## Goal

Add the commercial access layer without putting payment/subscription logic inside product features.

## Work

- [ ] Define stable feature entitlement keys.
- [ ] Implement central entitlement service.
- [ ] Connect entitlement service to the feature gates created earlier.
- [ ] Add the selected license/account/subscription source.
- [ ] Preserve an internal/dev `ALL` entitlement.
- [ ] Define safe offline/error behavior where required.

## Exit criteria

- [ ] Features only ask whether an entitlement is granted.
- [ ] Feature code does not contain plan/payment logic.
- [ ] Development build can still unlock everything.
- [ ] Phase 8 confirmed.

---

# Phase 9 — Lock features into product plans

**Status: ⬜ NOT STARTED**

## Goal

Assign working features to commercial plans using entitlements only.

## Work

- [ ] Define final plan names.
- [ ] Define which entitlement keys each plan receives.
- [ ] Test upgrades/downgrades/access loss/access restoration.
- [ ] Confirm locked features do not break unlocked features.
- [ ] Confirm development/internal entitlement still grants all features.

## Exit criteria

- [ ] Plans can change feature access without changing feature implementation.
- [ ] Locked/unlocked behavior is reliable.
- [ ] Phase 9 confirmed.

---

# Phase 10 — Finalize Windows as the reference production platform

**Status: ⬜ NOT STARTED**

## Goal

Ship the complete, refactored, entitlement-aware Windows product.

## Work

- [ ] Final Windows installer.
- [ ] Final uninstall behavior.
- [ ] Final launcher/startup behavior.
- [ ] Final updater/recovery behavior.
- [ ] Final first-run experience.
- [ ] Final entitlement/account/license behavior.
- [ ] Final production signing/versioning/release process.
- [ ] Full Windows regression.

## Exit criteria

- [ ] Windows is production-ready and becomes the reference platform behavior.
- [ ] Phase 10 confirmed.

---

# Phase 11 — Linux application

**Status: ⬜ NOT STARTED**

## Goal

Add Linux packaging/runtime without changing core Stats business logic.

## Work

- [ ] Linux platform adapter.
- [ ] Linux installer/package.
- [ ] Linux launcher/runtime.
- [ ] Linux updater strategy.
- [ ] Linux filesystem/display integration.
- [ ] Full Linux regression when a Linux testing environment is available.

## Exit criteria

- [ ] Linux works without platform-specific changes leaking into core leaderboard/data/theme/product logic.
- [ ] Phase 11 confirmed.

---

# Phase 12 — macOS application

**Status: ⬜ NOT STARTED**

## Goal

Add macOS packaging/runtime without changing core Stats business logic.

## Work

- [ ] macOS platform adapter.
- [ ] macOS application packaging.
- [ ] macOS launcher/runtime.
- [ ] macOS update strategy.
- [ ] macOS permissions/signing/notarization.
- [ ] Full macOS regression when a macOS testing environment is available.

## Exit criteria

- [ ] macOS works without platform-specific changes leaking into core leaderboard/data/theme/product logic.
- [ ] Phase 12 confirmed.

---

# Phase 13 — Website / hosted Stats

**Status: ⬜ NOT STARTED**

## Goal

Reuse the modular Stats core/services/UI for a hosted web product.

## Work

- [ ] Define hosted deployment architecture.
- [ ] Replace local-only platform assumptions with hosted equivalents.
- [ ] Add multi-user/account/organization model as required.
- [ ] Add hosted persistence/database model as required.
- [ ] Add multi-tenant security/isolation as required.
- [ ] Add hosted Tableau/data connection strategy.
- [ ] Reuse the existing entitlement system for web plans.
- [ ] Full hosted security/reliability/regression testing.

## Exit criteria

- [ ] Hosted Stats is production-ready.
- [ ] Desktop and web share core behavior where appropriate rather than becoming separate products/codebases.
- [ ] Phase 13 confirmed.

---

# Current position

`Phase 0 ✅` → `Phase 1 ✅` → **Phase 2 is next.**

Do not begin Phase 3 until Phase 2 has been completed, tested, and explicitly confirmed in this file.