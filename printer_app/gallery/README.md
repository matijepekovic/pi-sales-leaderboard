# Phone gallery: complete cards, dates and floating controls

The gallery is a single vertically scrolling feed, with full-width work-order
images grouped by their printed document date, newest first. Unknown dates have
their own group at the end. The entire stored image is displayed at its original
aspect ratio: no thumbnail grid, square crops, cover scaling, or new image files.
Opening a card shows the same full image. Retention and the border cutter are not
changed by this presentation update.

The floating controls are **Show related**, **Notes**, and **Search**. Notes and
Related automatically target the complete, unobscured card in view; opening a card
pins that record while its viewer is open. Related takes the explicit printed
Lead Name automatically and searches that phrase across all retained printed text,
corrected names and notes, newest dates first. It clears the current search/date
filter and never opens a name-entry prompt. Unreadable or ambiguous names show a
clear message, not a guessed match. Optional corrections remain in Card details.
A matching name alone is not proof that two records represent the same person.

Notes opens a bottom sheet for the selected card to read or add centrally saved
notes. That target remains pinned while editing. Other open viewers refresh within five seconds. Notes remain per document,
not merged across related cards. Search opens a floating sheet and searches all
recognized printed text, corrected lead names, and shared notes. All cards restores
the date-grouped feed. Load more extends the same feed in bounded 24-card batches.
The information button contains storage, QR access and refresh, with no exit to
Settings or Print Control. Administrative URLs remain directly accessible.

The gallery repository performs an additive, transactional lead-name/index upgrade
using already-saved search text. Existing images, notes, dates and import receipts
are preserved; no OCR rerun, source reimport or new print jobs. New imports populate
the same index. This feature stays within gallery policy/service/repository/web and
its own frontend assets. Stats, Gmail polling, print scheduling, CUPS, credentials,
cleanup rules, and other printer pages are untouched. Deploy through the existing
leaderboard Update button; reopen the gallery afterward.


## Tap a date or swipe between days

Tap a printed date heading, the date at the top, or the date in an open image to
choose a day in the calendar sheet. Only days with matching retained work orders
are selectable; the month selector jumps between months that contain records.
Choosing a date filters the feed to that day. **All dates** restores the grouped
feed without clearing the current search or related-lead filter. **Dates need
checking** shows undated images separately; it never invents a date for them.
This is a browsing filter, not a change to a document's saved date or retention.

Swipe **left for the next newer date**, **right for the previous older date** on
the card feed, or use the arrow buttons next to the date. Empty days are skipped.
From All dates, a swipe starts at the touched card's group; the buttons use the
visible group. There is no wrapping at the first/last date. Undated cards do not
participate in chronological swipes; use the calendar to return to dated cards.
Vertical scrolling, pinch-to-zoom, edge navigation and gestures inside image or
notes/search dialogs do not switch dates. Nothing is resized into a thumbnail.

Starting Search or Show related resets the day filter, so matches still span all
retained dates. The calendar and swipes then use the dates in those results, not
unrelated cards. Date counts come from the entire result set, including records
beyond the first 24-card batch. Load more still appends full cards. An expired or
newly emptied day displays an empty state with access to All dates/the calendar.

The repository owns date-scoped SQL and a read snapshot of counts/rows. Policy
validates the optional `date` query parameter (YYYY-MM-DD, empty, or `undated`).
The service and gallery HTTP layer pass the normalized filter; `gallery_dates.js`
owns calendar/gesture behavior, and `gallery.js` continues to own retrieval and
card rendering. No schema migration, OCR/crop changes, files or dates rewritten,
printer mutations, new dependencies, or new service lifecycle.


## Gallery-only email routing

In printer Settings, matching PDFs now default to **Gallery only — do not print
matching PDFs**. Other attachments keep normal printing behavior. Subject and PDF
filename keywords are separate optional selectors (at least one is required); all
filled selectors and the optional sender restriction must match. Set filename to
`redlines` and clear subject to distinguish that PDF from another report in the same
email. These are literal case-insensitive substrings, not regular expressions.

**Import and also use normal print rules** deliberately allows both routes. Disabling
imports stops matching NEW messages; it is not a blanket no-print filter. Incomplete
handoffs keep their original exclusion even after a restart/settings change and wait
while imports are disabled. No fallback printing on gallery errors and no automatic
cancellation of existing print jobs. Intake failures are visible on Print Control and
in gallery settings; processing failures remain in the gallery information panel.

Classification lives at the ingestion boundary, not in the gallery worker or print
engine. The optional PDF consumer receives bytes only after the decision is durable.
No PDF reimport, recropping, notes/date migration or frontend gallery changes required.

## Queue controls and gallery actions

Print Control includes **Gallery Queue**, which lists pending email handoffs and
separate gallery imports. **View gallery jobs** opens processing status; each PDF
links to its own log, timestamps, progress, and retained full-card images.

**Remove from print queue** opens a confirmation for one waiting attachment. The
POST uses existing same-origin/CSRF protection and the dispatch service's durable
cancellation boundary. Once submission is reserved, removal is rejected; this is
not a CUPS cancellation button. Other reports and gallery data are unchanged.

In the sales gallery, **Notes** and **Show related** automatically use the fully
visible, unobscured card. Notes remain pinned to that record while the panel is
open, including keyboard/viewport changes. Related uses its automatically read
lead name as a phrase search across all saved printed text, lead names and notes;
it starts across all dates, not just the current date or loaded page. It never
opens a name-entry prompt. Unreadable/ambiguous names show an error instead of
inventing a match. Missing names in legacy flattened OCR are backfilled once;
user-confirmed names and existing images/notes are preserved.

The gallery's links back to Print Control and Settings are removed. This is a
navigation-only change, **not access control**: direct administrative URLs still
work. No login, browser-history manipulation, Stats or permission changes.

PR #117 shipped backend helpers but omitted their web/template/action connections.
This completes those connections. The updater uses the existing installation
mechanism; already-stored incorrect crops are not silently deleted or rebuilt.
