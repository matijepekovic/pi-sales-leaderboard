# Stats data/display contracts

Stats is composed as:

`Source -> Report -> Filter -> Screen -> Display`

The arrows describe application flow, not ownership leakage.

## Source

A Source is an external connection handled by a replaceable adapter. Vendor-specific transport, credentials, discovery and parsing stay behind that adapter.

## Report

A Report defines data pulled from a Source and exposes normalized Stats fields and rows. Data Filters belong to the Report/source configuration and affect what is pulled.

## Filter

A Filter is a reusable human-facing concept such as Team, Office, Product or Rep. A Filter contains no Source, vendor, Report-field or Tableau knowledge.

## Screen

A Screen selects one or more Reports. Its Display Filter mappings explicitly match reusable Filters to concrete fields in each selected Report. The Screen may select a display value for each matched Filter. These mappings filter already-pulled data and never change the source pull.

The Screen also owns its table composition and theme policy (`inherited` or `custom`).

## Display

Display owns playback only: active Screen, Screen rotation order and rotation timing. Temporary data/date override remains a data/runtime concern and is not a Display Filter.

## Replaceability invariant

Replacing Tableau or another external Source adapter must not require changes to Filters, Screens, Display, themes, controls, repositories unrelated to source persistence, or normalized downstream data contracts.
