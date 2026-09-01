# Stats data/display contracts

Stats is composed as:

`Source -> Report -> Display Value -> Screen -> Display`

The arrows describe application flow, not ownership leakage.

## Source

A Source is an external connection handled by a replaceable adapter. Vendor-specific transport, credentials, discovery and parsing stay behind that adapter.

## Report

A Report defines data pulled from a Source and exposes normalized Stats fields and rows. Data Filters belong to the Report/source configuration and affect what is pulled.

## Display Value

Every normalized Report field automatically becomes one Display Value. A Display Value keeps the permanent binding to its Report and field key while owning the human-facing name used by Screens.

For example, the Report field `sr-rep name` can be renamed to `Name` without changing the underlying field or Source configuration.

Display Values are generated from Report fields rather than manually created. Only rename overrides are persisted.

## Screen

A Screen selects one or more Reports and chooses which Display Values appear, their ranking/sort order, row limit and theme policy. Screen Templates may group rows by a selected Display Value for competitive layouts such as Per Team, Team vs Team and All Teams.

Screens depend only on normalized Reports and Display Values. They do not know Source-vendor field structures.

## Display

Display owns playback only: active Screen, Screen rotation order and rotation timing.

## Replaceability invariant

Replacing Tableau or another external Source adapter must not require changes to Display Values, Screens, Display, themes or unrelated repositories. A different Source adapter only needs to produce the normalized Report field/row contract.
