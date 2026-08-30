# Stats architecture

The application has explicit runtime ownership while preserving the production SQLite schema and external behavior.

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

`app/stats_core/storage/sqlite.py` owns SQLite connection, schema initialization and migrations. Domain SQL belongs to repositories. Persistent data locations remain compatible with pre-refactor installs through the data-path migration.

## Data and Tableau

`TableauService` is the Tableau connection boundary. `RepPullPolicy` normalizes pulled rows and applies retention rules explicitly. `RepRefreshService` is the one rep refresh path used by both manual and scheduled refreshes. `PreviewService`, `TemporaryDateService` and `DataSnapshotService` explicitly choose preview, temporary or stored display data.

Shared Tableau HTTP and parsing primitives live in `sources/tableau_base.py`. Configured rep sources, the rep-summary parser, Product Close, mapped CSV and Crosstab modules depend on that stable source boundary; version-numbered Tableau base modules are retired.

Product Close Rates has separate source, repository, refresh service and screen ownership under `stats_core/product`, `stats_core/repositories`, `stats_core/services`, and `stats_core/screens`.

## Screens and controls

`ScreenRegistry` owns the five display modes: Whole Office, Per Team, Team vs Team, All Teams and Product Close Rates. `LeaderboardService` owns shared calculations. Individual screen modules own mode-specific payload shape. `ControlsService` gets valid screen choices from the registry rather than mutating display implementations.

## Themes and assets

`stats_core/theme/` owns the Theme API. Theme configuration, reusable library assets and currently-applied assets are separate repositories. Applied artwork is stored outside the application directory and built-in materialization uses hash-verified copies. The old runtime monkey-patch chain is not part of application composition.

## Access and security

`EntitlementService` is the single feature-access boundary and currently grants every existing feature for testing. It contains no account, subscription or payment logic. `AuthService` owns settings PIN behavior and throttling.

## Platform

Core services are platform-neutral. `stats_core/platform/windows.py` owns Windows launching/restart/update registration and Windows-specific integrations. The top-level `app/server.py` and `windows/server_entry.py` are thin entrypoints.

## Frontend ownership

`templates/display.html` and `templates/settings.html` are thin runtime manifests. Their base markup lives under `templates/display/` and `templates/settings/`, and scripts are grouped by responsibility under `static/display/`, `static/settings/` and `static/runtime/`.

The numbered frontend patch stack is retired. Active frontend files have stable responsibility-based names, obsolete superseded files are deleted, and CI rejects versioned root JavaScript or old versioned base templates from returning.
