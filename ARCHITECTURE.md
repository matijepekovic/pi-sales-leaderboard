# Stats architecture

Phase 4 establishes explicit ownership without changing the Phase 3 product behavior or SQLite schema.

## Composition root

`app/stats_core/bootstrap.py` is the only application composition root. It creates repositories, domain services, the screen registry, HTTP blueprints and the Windows platform adapter. Feature modules do not install or monkey-patch one another.

## Storage

`app/stats_core/repositories/` owns persistence adapters:

- reps and pull-retention cache
- organization / teams
- settings and metadata
- Product Close rows
- theme configuration
- reusable asset library
- protected applied-theme assets

The underlying database tables and persistent data locations remain compatible with the pre-refactor application.

## Data and Tableau

`TableauService` is the Tableau connection boundary. `RepPullPolicy` normalizes pulled rows and applies retention rules explicitly. `RepRefreshService` is the one rep refresh path used by both manual and scheduled refreshes. `PreviewService`, `TemporaryDateService` and `DataSnapshotService` explicitly choose preview, temporary or stored display data.

Product Close Rates has separate source, repository, refresh service and screen ownership under `stats_core/product`, `stats_core/repositories`, `stats_core/services`, and `stats_core/screens`.

## Screens and controls

`ScreenRegistry` owns the five existing display modes: Whole Office, Per Team, Team vs Team, All Teams and Product Close Rates. `LeaderboardService` owns shared calculations. Individual screen modules own mode-specific payload shape. `ControlsService` gets valid screen choices from the registry rather than mutating display implementations.

## Themes and assets

`stats_core/theme/` owns the Theme API. Theme configuration, reusable library assets and currently-applied assets are separate repositories. Applied artwork is stored outside the application directory and built-in/legacy materialization uses hash-verified copies. The old v116/v119/v127 runtime monkey-patch chain is not part of application composition.

## Access and security

`EntitlementService` is the single feature-access boundary and currently grants every existing feature for testing. It contains no account, subscription or payment logic. `AuthService` owns settings PIN behavior.

## Platform

Core services are platform-neutral. `stats_core/platform/windows.py` owns Windows launching/restart/update registration and Windows-specific integrations. The top-level `app/server.py` and `windows/server_entry.py` are thin entrypoints.

## Frontend ownership

Display and Settings templates group scripts by runtime responsibility. The precision-formatting override and Team Builder workflow are stable modules under `static/runtime/` and `static/settings/` instead of inline template patches. Existing versioned scripts remain in their Phase 3 order until each can be replaced and verified individually.
