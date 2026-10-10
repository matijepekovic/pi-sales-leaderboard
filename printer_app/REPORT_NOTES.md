# Handwriting notes under report tables

Report Printing > edit a printing job > the report's **Edit** button >
**Print selected columns below the table**.

Load the report columns, select fields and order them with the arrow buttons.
Set text size in points, blank space after each job in millimetres, and the gap
below the table in millimetres. Build and open the PDF preview. Save report
settings, then save the printing job. Each report has its own settings. Existing
jobs start with notes disabled; disabling notes preserves the original printing
path and does not parse or change the original PDF.

The preview uses the same preparation path as scheduled printing, but never
queues a print. It reports the number of job rows and smallest page scale.
Preview exports are temporary and the response is not cached. Saved schedules
still download a fresh report at execution time.

## Placement and fitting

The reader uses native text and vector cell borders in the already-rendered PDF,
not OCR, AI, a second report query, or guessed spreadsheet page breaks. Values
therefore belong to the actual page being printed. Headers, subtotal/aggregate
rows and hidden spreadsheet records are not repeated as jobs. Distinct jobs
with the same name remain distinct rows. Blank selected fields do not drop an
otherwise populated job. Merged grouping values are carried only across their
actual merged cells.

Notes begin after the bottom table rule and any overlapping glyphs, followed by
the requested gap. A fixed start position is never used. When there is room,
the original report is unchanged. Otherwise the original upper report block
and notes shrink uniformly together, including the requested spacing, until
both fit above the footer/bottom margin. Writing rules still use the page width.
Page size, page count and job order are preserved. Footers stay in place.
Values wrap instead of being truncated. Very crowded pages can produce small
text: the preview warns below 6-point effective text. Reduce spacing/columns or
select larger paper to improve it.

Field selections match normalized headings, not column numbers. Missing or
ambiguous headings, unsupported characters or an unreadable/borderless table
fail explicitly rather than printing wrong names or silently omitting the
overlay. The current feature requires a text-based report with table borders;
it does not process photographs or scanned reports. Native source text already
clipped by the report export cannot be recovered by an overlay.

## Ownership

- `report_notes_contract.py` owns validated settings and normalized page rows/bounds.
- `report_table_pdf.py` reads native PDF table geometry and returns that contract.
- `report_notes_pdf.py` renders the normalized data; it does not depend on the table reader or a source vendor.
- `report_printing_service.py` owns conversion, optional notes preparation, preview lifecycle and queue submission.
- Existing repositories persist settings; web owns HTTP.
- `report_notes_editor.js` owns notes controls behind an explicit open/read boundary; the existing report picker owns report selection and saving.

The source adapter, existing Office converter, printer dispatch, Gmail, Gallery
and leaderboard are unchanged. No schema changes are required: the existing
report-job JSON stores notes options, with a disabled default for older data.

CI covers actual Office conversion, per-page row mapping, physical PDF bounds,
rendered-pixel parity without shrinking, shrink/footers, source preservation,
queue idempotence, saved settings, CSRF/admin checks, and Chromium/WebKit flows.
Only invented customer data is checked into the test fixtures.
