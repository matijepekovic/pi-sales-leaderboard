# Live-dev architecture implementation

This records the first working implementation of the approved architecture. It is
not a claim that the full SaaS roadmap or every future editor capability is done.
Application wiring stays in `app/stats_core/bootstrap.py`.

## Active ownership

| Owner | Stores / decides | Public boundary |
| --- | --- | --- |
| Data | Connections, saved Report pulls, default and isolated period snapshots, missing-row retention | Report service, `/api/data` |
| Fields | Global names, display types, rounding, calculations, row-resolved Group asset Fields, reusable row matching | Field IDs, catalogue, resolution/evaluation, `/api/fields` |
| Widgets | Unstyled visualization definition, ordered Field IDs, filters, explicit per-value calculations | Definition, contextual preview/render, `/api/widgets` |
| Groups | Types, exclusive membership within a type, configurable roles, Theme/asset selections, Widget visual refinements | Membership and appearance contracts, `/api/groups`, `/api/group-types` |
| Themes / Assets | Reusable Theme definitions, asset library, resolution of Group appearance | Effective appearance and placeable asset slots, `/api/themes` |
| Screens | Widget instances, Group scope, ranking, timeframe requests, canvas placement and fit overrides | Validated definition and resolved render payload, `/api/screens` |
| Display | Active Screen and existing rotation controls; rendering the resolved payload | `/api/display`, `/api/display/render` |

Group appearance does **not** bypass Themes. Bootstrap supplies Group appearance
to the Theme owner; Theme resolution supplies colors and artwork to Screen
composition. Theme code does not read Group or Screen repositories.

## Evaluation

1. Screen supplies Widget ID plus selected Groups, ranking priorities and the
   effective timeframe request. Instance timeframe wins over Screen timeframe;
   absent overrides use the saved Data timeframe.
2. Widget asks Fields for its selected, filter and ranking Field IDs. Fields
   resolves their lineage internally. Widget definitions never store Report IDs,
   source IDs, provider settings or styling.
3. Data executes any date request in a separate cached snapshot. Saving a Widget
   or Screen validates metadata without contacting the provider.
4. Fields supplies normalized ID-keyed values and row membership. Every asset
   Field resolves from its own row, including first-place rank artwork.
5. Widget filters, ranks and aggregates. A combined selection produces one
   visualization; separate Groups produce instances of the same definition.
6. The designated winner-driving Widget supplies its first ranked **member**.
   The chosen Group Type resolves that member's Group for Screen-level branding.
   This is not an aggregate team competition. Up to three sort priorities and a
   deterministic final order handle ties.
7. Themes resolves selected/inherited appearance. Screen-owned geometry and fit
   remain independent of Group colors and artwork. Separate Group visualizations
   can use their own appearance in inherited mode.
8. The shared renderer draws table, pie, bar and line Widgets in Settings, Theme
   preview and Display. Reference-canvas geometry scales proportionally; Display
   has no scrolling. Table row targets and manual fit controls belong to the
   placed instance, not its reusable Widget definition.

## Editing and safety

- Widget creation starts with a working canvas of real, individual rows. The user
  chooses Fields, opens a column to edit it, and uses Show as to change the visual.
  Each value keeps its own calculation and units;
  incompatible scales use separate panels. Changing the visual does not change
  the calculation, and returning to Table preserves the dormant chart settings.
  A pending or invalid edit retains the clearly identified last valid preview;
  Save waits for the current definition to validate. Undo restores the draft.
- Field selection stays in a searchable, persistent browser with scoped bulk
  selection. Checkbox edits batch/cancel preview requests without replacing the
  editor, its active picker, or table scroll positions. One result slot displays
  the Widget, its real data, or inspected contributing rows. Changing this view
  does not change the saved Widget. Column headings open a compact editor without
  issuing calculation requests. A changed chart summary uses the normal single
  Widget preview; the old parallel calculation-card requests are removed.
  Newly selected numeric Fields start with individual chart values. Explicit
  "Not used" choices survive visual changes; an empty measure list is not
  silently repopulated. A formula finishing after its editor is closed may add
  its saved Field to the catalog, but cannot dismiss a newer editor or alter a
  different Widget draft.
- The Fields-owned inline formula editor builds named row expressions from
  immutable Report Field keys and operator tokens. The read-only
  `POST /api/fields/<report_id>/preview` route uses the same compiler/evaluator as
  saved Fields, against cached Report rows, without saving or refreshing Data.
  The Widget receives only the created public Field ID through the editor's
  callback. Numeric operands are currently from one Report; cross-Report math
  and generic total-scope expressions are not implied. Existing chart ratios
  separately support dividing totals versus dividing each row.
- Formula, global Field, filter and column editors occupy one active panel.
  Calculate explicitly opens the Fields-owned formula editor, replacing the
  previous edit. Its real-data formula result temporarily replaces the main
  preview. Widget saving waits until the Field edit is closed or completed.
- Table preview and saved rendering share the same raw-row contract, including
  dormant chart settings. The obsolete prepared-calculation payload is removed.
- Show as lists compatible visuals without a separate intent workflow or
  suggestion cards. Composition asks whether values are parts of one whole;
  line setup asks for labels and explicit ordering. Date ordering
  accepts unambiguous ISO dates, numeric ordering sorts numerically, and legacy
  definitions preserve source order. Sorting keeps original contributor indexes
  and never fabricates historical data or reorders the source table.
- Chart meaning and aggregation live in `services/widget_charts.py`. Percentage
  circles have a fixed 100% whole; composition pies compare nonnegative parts of
  a total. Rates cannot be summed or share a numeric axis with ordinary numbers.
  Source numeric blanks count as zero, including in averages. Invalid text or
  a failed calculation remains unavailable, not zero. Whole missing rows remain
  Data's retention responsibility. Ratios explicitly choose totals, average of
  individual ratios, or individual row ratios, and Number or Percentage display.
  Division by zero is unavailable with a reason. Payloads carry result formats,
  contributing row indexes/counts and calculation evidence. A rate of 14.3%
  occupies 14.3% of its circle, with the remainder explicitly shown.
- `static/runtime/widget-charts.js` draws that evaluated contract identically in
  every preview and Display. It never fetches or aggregates source rows. The chart
  labels retain calculation and sample context outside the editor as well.
  In Widget and Screen editors, clicking a mark opens its contributing records.
  Timeline inspection uses that point's dated snapshot and row selection, not
  today's rows. Inspection is read-only; Display has no editor controls.
- Percentage input interpretation belongs to global Fields, not individual
  Widgets. Explicit fractional/percentage-point choices disambiguate numeric
  input; legacy automatic interpretation remains the compatibility default.
  A string with a percent sign is already explicit.

- Widget, Group and Screen builders summon the shared Theme Editor with real data.
  Theme changes save through Themes; Group appearance saves through Groups.
- Field editing uses the Fields owner and propagates globally. Screen fit edits
  do not rewrite Fields, Widgets or Group identity.
- Fields owns reusable, explicitly saved row matches. `/api/fields/matches`
  provides CRUD; `/matches/preview` is read-only. `/compatibility` explains missing
  relationships; `/identity-options` supplies candidate period identities.
  Widgets can open `StatsFields.openMatching`, but do not store joins. Full outer
  matching preserves unmatched records, blank keys never match, and repeating
  keys or ambiguous paths are rejected rather than duplicating totals.
- A Screen instance stores named `field_variants` and `identity_field_id`.
  Custom period columns receive local placement IDs; original global Fields and
  reusable Widgets are unchanged. Fields/Data executes each period request;
  real calendar bins form timelines, not refresh dates or invented history.
  Period rows match verified identities, never their positions. Validation does
  not contact the source. Each instance is bounded to 12 versions and 120 period
  queries; cached requests are reused within evaluation.
- Deleting a used Field, Widget, Group, Group Type, Theme, asset or Report is
  blocked by relevant dependency checks. A Widget update that would invalidate a
  referencing Screen's Group scope or ranking is rejected before saving.
- Display polls resolved data without reloading the page. The development
  browser reload mechanism responds to code changes, not UI settings changes.
- Legacy Report/table Screen definitions migrate once into Widgets and instances.
  Screen IDs survive. Original definitions are retained by ScreenRepository in
  `screen_legacy_backup:*` records. Invalid migrations retain the original and
  report the error. Old Table Presets remain migration/input compatibility;
  new Screen rendering does not execute the old table-building pipeline.
- The retired Theme canvas editor is removed from runtime source. Its pre-refactor
  local backup is at `tmp/refactor-backups/theme-layout-editor.js.txt`; that
  backup is not part of the Git checkout.

## Still to implement separately

- Temporary, expiring timeframe/display takeovers and richer display controls.
- One-to-many relationships and explicit regrouping of differently grained
  datasets. The current matching contract requires unique keys on both sides.
- Persistent source-schema history and a guided repair workflow for renamed or
  removed upstream columns; missing references currently fail explicitly.
- Broader reusable Widget templates, additional visualizations and richer asset
  layering/editor refinement beyond the initial placement controls.
- SaaS tenancy, accounts/permissions, API versioning and deployment isolation.

Regression coverage lives under `windows/test_*contract.py`, including Widget,
Screen composition, migration, Group appearance and period-query tests. These
use isolated test storage and mocked sources, not the live Tableau connection.
