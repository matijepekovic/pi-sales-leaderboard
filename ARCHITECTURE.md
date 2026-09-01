# Stats architecture

Stats is a configurable competitive-display product. Companies connect a Source, pull Reports, turn Report fields into user-facing Display Values, build Screens, apply Themes and choose what the Display plays.

## Composition root

`app/stats_core/bootstrap.py` is the single application composition root. It creates repositories, Source adapters, services, HTTP blueprints, Theme and the Windows platform adapter. Feature modules do not construct or monkey-patch unrelated modules.

## Core flow

`Source -> Report -> Display Value -> Screen -> Display`

Data Filters are separate. They belong to Report/source configuration and affect what is pulled from the external Source.

## Sources and Reports

External integrations are replaceable adapters under `app/sources/`. Tableau-specific credentials, discovery, transport and parsing stay inside the Tableau adapter boundary.

`ReportService` owns normalized Report definitions and pulled snapshots. Downstream modules consume normalized fields and rows only.

## Display Values

`DisplayValueService` owns the user-facing naming layer over Report fields. Every normalized field automatically produces one deterministic Display Value. The underlying Report/field binding never changes when a user renames the Display Value.

Only rename overrides are persisted by `DisplayValueRepository`; there is no second copy of Report fields.

## Screens

`ScreenService` owns editable Screen definitions and Screen Templates. Screens choose Reports, Display Values, sorting, row limits, template grouping and theme policy. Template-specific grouping behavior remains in the Screen layer.

Whole Office, Per Team, Team vs Team, All Teams and Product Close are templates, not hard-coded application modes.

## Display

`DisplayService` owns playback only: active Screen, rotation membership and timing. It renders normalized Screen payloads and has no Source-vendor knowledge.

## Themes and assets

`stats_core/theme/` owns Screen visual configuration and assets. Theme changes do not alter Report, Display Value or Screen data contracts.

## Storage

Repositories own domain persistence. `app/stats_core/storage/sqlite.py` owns only connection, schema initialization and migrations.

## Platform

Windows-specific launching, update and OS integration remain under the Windows platform boundary. Platform-neutral services do not import Windows modules.

## Frontend ownership

Settings frontend code is grouped by current responsibility: Data, Display Values, Screens, Display and shared Runtime. Display frontend code consumes normalized Screen render payloads. Source-vendor behavior must not leak into Screens, Display Values, Display or Themes.

## Replaceability test

Before merging a module change, ask:

> Could this module be replaced without rewriting unrelated parts of Stats?

If the answer is no, fix the boundary before merging.
