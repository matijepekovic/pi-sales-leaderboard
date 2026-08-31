# Stats Engineering Rules

These rules apply to all code changes in this repository.

## Keep modules replaceable

Stats must remain modular and responsibility-based. Every feature has one clear owner and communicates with the rest of the application through an explicit boundary or contract.

Before merging a change, ask: **Could this module be replaced without rewriting unrelated parts of Stats?** If the answer is no, fix the coupling before merging.

## Ownership boundaries

- `app/stats_core/bootstrap.py` is the single application composition root. Wire dependencies there; do not secretly construct, patch, or replace them elsewhere.
- `app/stats_core/storage/sqlite.py` owns only SQLite connection, schema initialization, and migrations.
- Domain SQL and persistence belong in `app/stats_core/repositories/`.
- Business rules and workflows belong in `app/stats_core/services/`.
- Display-mode-specific payload behavior belongs in `app/stats_core/screens/`.
- HTTP/API concerns belong in `app/stats_core/web/`.
- Theme behavior belongs in `app/stats_core/theme/` and its repositories.
- Product Close behavior stays behind its product/source/repository/service/screen boundaries.
- Windows-specific behavior belongs in `app/stats_core/platform/`, `app/stats_core/windows/`, or `windows/` as appropriate. Core domain code must not depend on OS-specific modules.
- Frontend code must live under its responsibility-based Display, Settings, or shared Runtime owner.

## External integrations are adapters

External systems such as Tableau are replaceable adapters, not application architecture.

- Tableau-specific transport, parsing, workbook/view discovery, filters, parameters, and source behavior belong in the Tableau/source boundary.
- Downstream leaderboard, screen, repository, theme, control, and settings logic must depend on normalized Stats data/contracts rather than Tableau-specific structures.
- If Tableau is replaced or another source is added, prefer implementing a new source adapter that satisfies the existing application contract instead of changing unrelated downstream modules.
- Do not spread vendor-specific conditionals across the application.

## Do not recreate the old architecture

Do not introduce:

- version-numbered replacement modules or JavaScript files;
- monkey-patch chains;
- duplicate implementations of the same feature;
- compatibility wrappers with no active compatibility requirement;
- direct database bypasses around repositories;
- source-specific logic inside unrelated leaderboard/screens/themes/controls code;
- platform-specific imports in platform-neutral core modules;
- temporary patch files that become permanent architecture;
- speculative service layers or abstractions without a real current responsibility.

Prefer deleting obsolete code over keeping parallel implementations.

## How to handle a feature that does not fit

Do not bypass the architecture because a shortcut is faster. If a new requirement does not fit cleanly, improve the relevant boundary first, then implement the feature through that boundary.

Preserve external behavior and existing data compatibility unless the task explicitly requires a product behavior or data-contract change.

When a change establishes a new architectural invariant, add or strengthen a CI architecture test so the old shape cannot silently return.

## Branch safety

For production work, branch from `production` and merge back to `production`. Do not modify `main` unless the user explicitly asks for work on `main`.
