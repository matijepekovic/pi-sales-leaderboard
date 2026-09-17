# Phone gallery: complete cards, dates and floating controls

The gallery is a single vertically scrolling feed, with full-width work-order
images grouped by their printed document date, newest first. Unknown dates have
their own group at the end. The entire stored image is displayed at its original
aspect ratio: no thumbnail grid, square crops, cover scaling, or new image files.
Opening a card shows the same full image. Retention and the border cutter are not
changed by this presentation update.

The floating controls are **Show related**, **Notes**, and **Search**. Tap a card
first to select it. Show related lists that lead's retained work orders across all
dates, vertically, newest first (including the selected card). It matches only the
explicit Lead Name header, not mentions in reps/notes, partial names or filenames.
Case and extra whitespace are ignored; different spellings are not silently merged.
No name is guessed when the header is unreadable. Confirm/correct it under Notes →
Card details; a Show related request without a name opens that field. Matching a
name alone is not proof that two records represent the same person.

Notes opens a bottom sheet for the selected card to read or add centrally saved
notes. Other open viewers refresh within five seconds. Notes remain per document,
not merged across related cards. Search opens a floating sheet and searches all
recognized printed text, corrected lead names, and shared notes. All cards restores
the date-grouped feed. Load more extends the same feed in bounded 24-card batches.
The information button contains storage, QR access, refresh and gallery settings.

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
